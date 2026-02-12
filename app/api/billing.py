from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.billing import topup_wallet
from app.db.models import InfluencerWallet
from app.schemas.billing import TopUpRequest
from app.db.session import get_db
from app.utils.auth.dependencies import get_current_user

import httpx
from decimal import Decimal
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from app.services.paypal import paypal_access_token
from app.services.firstpromoter import fp_track_sale_v2
from app.db.models import PayPalTopUp, Influencer, InfluencerCreditTransaction
from app.core.config import settings
from datetime import date
from sqlalchemy import and_
import traceback
from fastapi.responses import JSONResponse
from app.utils.infrastructure.rate_limiter import rate_limit
from app.utils.infrastructure.idempotency import idempotent

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/balance")
async def get_balance(
    influencer_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    is_18: bool = True,
):
    infl = await db.get(Influencer, influencer_id)
    if not infl:
        raise HTTPException(status_code=404, detail="Influencer not found")

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(is_18),
        )
    )

    return {
        "influencer_id": influencer_id,
        "balance_cents": wallet.balance_cents if wallet else 0,
    }

@router.post("/topup")
@rate_limit(max_requests=settings.RATE_LIMIT_BILLING_MAX, window_seconds=settings.RATE_LIMIT_BILLING_WINDOW, key_prefix="billing:topup")
@idempotent(ttl=settings.IDEMPOTENCY_TTL, key_prefix="topup")
async def topup(
    request: Request,
    req: TopUpRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not req.influencer_id:
        raise HTTPException(status_code=400, detail="Missing influencer_id")

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == req.influencer_id,
            InfluencerWallet.is_18 == False,
        )
    )

    if not wallet:
        wallet = InfluencerWallet(
            user_id=user.id,
            influencer_id=req.influencer_id,
            balance_cents=0,
        )
        db.add(wallet)
        await db.flush()

    wallet.balance_cents = (wallet.balance_cents or 0) + int(req.cents)
    db.add(wallet)

    await db.commit()
    await db.refresh(wallet)

    return {
        "ok": True,
        "user_id": user.id,
        "influencer_id": wallet.influencer_id,
        "balance_cents": wallet.balance_cents,
    }

class PayPalCreateReq(BaseModel):
    cents: PositiveInt
    influencer_id: str
    currency: str | None = None

@router.post("/paypal/create-order")
@rate_limit(max_requests=settings.RATE_LIMIT_BILLING_MAX, window_seconds=settings.RATE_LIMIT_BILLING_WINDOW, key_prefix="billing:paypal-create")
@idempotent(ttl=settings.IDEMPOTENCY_TTL, key_prefix="paypal-create")
async def paypal_create_order(request: Request, req: PayPalCreateReq, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    token = await paypal_access_token()

    influencer_id = (req.influencer_id or "").strip()
    if not influencer_id:
        raise HTTPException(status_code=400, detail="Missing influencer_id")
    infl = await db.get(Influencer, influencer_id)
    if not infl:
        raise HTTPException(status_code=404, detail="Influencer not found")

    currency = (req.currency or settings.PAYPAL_CURRENCY or "AUD").strip().upper()
    value = f"{(Decimal(req.cents) / Decimal(100)):.2f}"

    if not settings.PAYPAL_BASE_URL:
        raise HTTPException(status_code=500, detail="PAYPAL_BASE_URL not configured")

    return_url = (settings.PAYPAL_RETURN_URL or "").strip() or None
    cancel_url = (settings.PAYPAL_CANCEL_URL or "").strip() or None

    payload: dict = {
        "intent": "CAPTURE",
        "purchase_units": [{"amount": {"currency_code": currency, "value": value}}],
    }
    # Only include redirect URLs if they're configured; sending nulls causes PayPal 400.
    if return_url and cancel_url:
        payload["application_context"] = {
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        }

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(
                f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            # PayPal returns helpful JSON (name/message/details/debug_id). Bubble it up.
            try:
                paypal_body = e.response.json()
            except Exception:
                paypal_body = {"raw": e.response.text}
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "PayPal create order failed",
                    "paypal_status": e.response.status_code,
                    "paypal": paypal_body,
                },
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail="PayPal request failed") from e

    order_id = data["id"]
    approve_url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
    if not approve_url:
        raise HTTPException(500, "PayPal approve url missing")

    db.add(PayPalTopUp(
        user_id=user.id,
        influencer_id=influencer_id,
        order_id=order_id,
        cents=req.cents,
        status="CREATED",
        credited=False
    ))
    await db.commit()

    return {"order_id": order_id, "approve_url": approve_url}

class PayPalCaptureReq(BaseModel):
    order_id: str
    influencer_id: str | None = None

@router.post("/paypal/capture")
@rate_limit(max_requests=settings.RATE_LIMIT_BILLING_MAX, window_seconds=settings.RATE_LIMIT_BILLING_WINDOW, key_prefix="billing:paypal-capture")
async def paypal_capture(
    request: Request,
    req: PayPalCaptureReq,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        # Capture PayPal (safe to call multiple times; PayPal returns completed on repeats)
        token = await paypal_access_token()
        if not settings.PAYPAL_BASE_URL:
            raise HTTPException(status_code=500, detail="PAYPAL_BASE_URL not configured")

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                r = await client.post(
                    f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{req.order_id}/capture",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                r.raise_for_status()
                cap = r.json()
            except httpx.HTTPStatusError as e:
                try:
                    paypal_body = e.response.json()
                except Exception:
                    paypal_body = {"raw": e.response.text}
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "PayPal capture failed",
                        "paypal_status": e.response.status_code,
                        "paypal": paypal_body,
                    },
                ) from e
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail="PayPal request failed") from e

        status = cap.get("status", "UNKNOWN")
        if status != "COMPLETED":
            try:
                locked = await db.scalar(
                    select(PayPalTopUp).where(PayPalTopUp.order_id == req.order_id).with_for_update()
                )
                if not locked:
                    raise HTTPException(404, "Unknown order_id")
                if locked.user_id != user.id:
                    raise HTTPException(403, "Order does not belong to this user")
                locked.status = status
                db.add(locked)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
            return {"ok": False, "status": status, "credited": False}

        source = f"paypal:{req.order_id}"
        new_balance: int
        cents: int

        # Credit + ledger (idempotent, concurrency-safe)
        try:
            locked = await db.scalar(
                select(PayPalTopUp).where(PayPalTopUp.order_id == req.order_id).with_for_update()
            )
            if not locked:
                raise HTTPException(404, "Unknown order_id")
            if locked.user_id != user.id:
                raise HTTPException(403, "Order does not belong to this user")

            influencer_id = (locked.influencer_id or req.influencer_id or "").strip()
            if not influencer_id:
                raise HTTPException(status_code=400, detail="Missing influencer_id for this PayPal order")

            if not locked.influencer_id:
                locked.influencer_id = influencer_id
                db.add(locked)

            if locked.credited:
                wallet = await db.scalar(
                    select(InfluencerWallet).where(
                        and_(
                            InfluencerWallet.user_id == user.id,
                            InfluencerWallet.influencer_id == influencer_id,
                            InfluencerWallet.is_18.is_(False),
                        )
                    )
                )
                return {
                    "ok": True,
                    "credited": True,
                    "new_balance_cents": wallet.balance_cents if wallet else 0,
                }

            existing_tx = await db.scalar(
                select(InfluencerCreditTransaction).where(
                    and_(
                        InfluencerCreditTransaction.user_id == user.id,
                        InfluencerCreditTransaction.influencer_id == influencer_id,
                        InfluencerCreditTransaction.feature == "topup",
                        InfluencerCreditTransaction.meta["source"].as_string() == source,  # type: ignore[index]
                    )
                )
            )
            if existing_tx:
                locked.status = "COMPLETED"
                locked.credited = True
                db.add(locked)
                wallet = await db.scalar(
                    select(InfluencerWallet).where(
                        and_(
                            InfluencerWallet.user_id == user.id,
                            InfluencerWallet.influencer_id == influencer_id,
                            InfluencerWallet.is_18.is_(False),
                        )
                    )
                )
                return {
                    "ok": True,
                    "credited": True,
                    "new_balance_cents": wallet.balance_cents if wallet else 0,
                }

            cents = int(locked.cents)
            new_balance = await topup_wallet(
                db,
                user.id,
                influencer_id,
                cents,
                source=source,
                is_18=False,
            )
            locked.status = "COMPLETED"
            locked.credited = True
            db.add(locked)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        # Post-commit side effects (don't affect payment success)
        try:
            if req.influencer_id:
                influencer = await db.get(Influencer, req.influencer_id)
                if influencer and influencer.fp_ref_id:
                    await fp_track_sale_v2(
                        email=user.email,
                        uid=str(user.id),
                        amount_cents=cents,
                        event_id=req.order_id,
                        ref_id=influencer.fp_ref_id,
                        plan="wallet_topup",
                    )
        except Exception as e:
            print("FirstPromoter track sale failed:", e)

        return {
            "ok": True,
            "status": "COMPLETED",
            "credited": True,
            "new_balance_cents": new_balance,
        }
    except HTTPException:
        raise
    except Exception as e:
        # Keep `detail` a string so frontends that render it directly don't crash,
        # while still returning rich debug info for development.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "paypal_capture crashed",
                "debug": {
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "trace": traceback.format_exc().splitlines()[-20:],
                },
            },
        )