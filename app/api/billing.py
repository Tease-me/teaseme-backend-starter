from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.billing import topup_wallet
from app.db.models import InfluencerWallet
from app.schemas.billing import TopUpRequest
from app.db.session import get_db
from app.utils.deps import get_current_user

import httpx
from decimal import Decimal
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from app.services.paypal import paypal_access_token
from app.services.firstpromoter import fp_track_sale_v2
from app.db.models import PayPalTopUp, Influencer
from app.core.config import settings

router = APIRouter(prefix="/billing", tags=["billing"])

@router.get("/balance")
async def get_balance(
    influencer_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # optional: validate influencer exists
    infl = await db.get(Influencer, influencer_id)
    if not infl:
        raise HTTPException(status_code=404, detail="Influencer not found")

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.user_id,
            InfluencerWallet.influencer_id == influencer_id,
        )
    )

    return {
        "influencer_id": influencer_id,
        "balance_cents": wallet.balance_cents if wallet else 0,
    }

@router.post("/topup")
async def topup(
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
async def paypal_create_order(req: PayPalCreateReq, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    token = await paypal_access_token()

    currency = req.currency or getattr(settings, "PAYPAL_CURRENCY", "AUD")
    value = f"{(Decimal(req.cents) / Decimal(100)):.2f}"

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{"amount": {"currency_code": currency, "value": value}}],
                "application_context": {
                    "user_action": "PAY_NOW",
                    "return_url": settings.PAYPAL_RETURN_URL,
                    "cancel_url": settings.PAYPAL_CANCEL_URL,
                },
            },
        )
        r.raise_for_status()
        data = r.json()

    order_id = data["id"]
    approve_url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
    if not approve_url:
        raise HTTPException(500, "PayPal approve url missing")

    db.add(PayPalTopUp(
        user_id=user.id,
        influencer_id=req.influencer_id,
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
async def paypal_capture(
    req: PayPalCaptureReq,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    row = await db.scalar(
        select(PayPalTopUp).where(PayPalTopUp.order_id == req.order_id)
    )
    if not row:
        raise HTTPException(404, "Unknown order_id")

    if row.user_id != user.id:
        raise HTTPException(403, "Order does not belong to this user")

    if row.credited:
        wallet = await db.scalar(select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == row.influencer_id,
        ))
        return {"ok": True, "credited": True, "new_balance_cents": wallet.balance_cents if wallet else 0}

    # Capture PayPal
    token = await paypal_access_token()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{req.order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()
        cap = r.json()

    if cap.get("status") != "COMPLETED":
        row.status = cap.get("status", "UNKNOWN")
        db.add(row)
        await db.commit()
        return {"ok": False, "status": row.status, "credited": False}

    # Credit wallet
    new_balance = await topup_wallet(
        db, user.id, row.cents, source=f"paypal:{req.order_id}"
    )

    row.status = "COMPLETED"
    row.credited = True

    try:
        if req.influencer_id:
            influencer = await db.get(Influencer, req.influencer_id)

            if influencer and influencer.fp_ref_id:
                await fp_track_sale_v2(
                    email=user.email,
                    uid=str(user.id),
                    amount_cents=row.cents,
                    event_id=req.order_id,
                    ref_id=influencer.fp_ref_id,
                    plan="wallet_topup",
                )
    except Exception as e:
        print("FirstPromoter track sale failed:", e)

    db.add(row)
    await db.commit()

    return {
        "ok": True,
        "status": "COMPLETED",
        "credited": True,
        "new_balance_cents": new_balance,
    }