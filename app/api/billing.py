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
from app.db.models import PayPalTopUp, Influencer, Pricing, DailyUsage
from app.core.config import settings
from datetime import date

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/usage")
async def get_usage(
    influencer_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    infl = await db.get(Influencer, influencer_id)
    if not infl:
        raise HTTPException(status_code=404, detail="Influencer not found")

    today = date.today()

    normal_wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(False),
        )
    )
    adult_wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(True),
        )
    )

    normal_usage = await db.get(DailyUsage, (user.id, today, False))
    adult_usage = await db.get(DailyUsage, (user.id, today, True))

    pricing_result = await db.execute(
        select(Pricing).where(Pricing.is_active.is_(True))
    )
    pricing_list = pricing_result.scalars().all()
    pricing_map = {p.feature: p for p in pricing_list}

    def calc_remaining(wallet, usage, feature: str, usage_field: str) -> dict:
        """Calculate remaining units for a feature."""
        price = pricing_map.get(feature)
        if not price:
            return {
                "feature": feature,
                "unit": "unknown",
                "price_cents": 0,
                "free_allowance": 0,
                "used_today": 0,
                "free_left": 0,
                "balance_cents": 0,
                "paid_units_available": 0,
                "total_remaining": 0,
            }

        used = getattr(usage, usage_field, 0) or 0 if usage else 0
        free_allowance = price.free_allowance or 0
        free_left = max(free_allowance - used, 0)
        
        balance_cents = wallet.balance_cents if wallet and wallet.balance_cents else 0
        unit_price = price.price_cents or 0
        paid_units = (balance_cents // unit_price) if unit_price > 0 else 0

        return {
            "feature": feature,
            "unit": price.unit,
            "price_cents": unit_price,
            "free_allowance": free_allowance,
            "used_today": used,
            "free_left": free_left,
            "balance_cents": balance_cents,
            "paid_units_available": paid_units,
            "total_remaining": free_left + paid_units,
        }

    normal_text = calc_remaining(normal_wallet, normal_usage, "text", "text_count")
    normal_voice = calc_remaining(normal_wallet, normal_usage, "voice", "voice_secs")
    normal_live = calc_remaining(normal_wallet, normal_usage, "live_chat", "live_secs")

    adult_text = calc_remaining(adult_wallet, adult_usage, "text_18", "text_count")
    adult_voice = calc_remaining(adult_wallet, adult_usage, "voice_18", "voice_secs")

    return {
        "influencer_id": influencer_id,
        "normal": {
            "balance_cents": normal_wallet.balance_cents if normal_wallet else 0,
            "text": {
                "messages_remaining": normal_text["total_remaining"],
                "free_left": normal_text["free_left"],
                "paid_available": normal_text["paid_units_available"],
                "used_today": normal_text["used_today"],
                "price_per_message_cents": normal_text["price_cents"],
            },
            "voice": {
                "seconds_remaining": normal_voice["total_remaining"],
                "minutes_remaining": round(normal_voice["total_remaining"] / 60, 2),
                "free_left": normal_voice["free_left"],
                "paid_available": normal_voice["paid_units_available"],
                "used_today": normal_voice["used_today"],
                "price_per_second_cents": normal_voice["price_cents"],
            },
            "live_chat": {
                "seconds_remaining": normal_live["total_remaining"],
                "minutes_remaining": round(normal_live["total_remaining"] / 60, 2),
                "free_left": normal_live["free_left"],
                "paid_available": normal_live["paid_units_available"],
                "used_today": normal_live["used_today"],
                "price_per_second_cents": normal_live["price_cents"],
            },
        },
        "adult": {
            "balance_cents": adult_wallet.balance_cents if adult_wallet else 0,
            "text": {
                "messages_remaining": adult_text["total_remaining"],
                "free_left": adult_text["free_left"],
                "paid_available": adult_text["paid_units_available"],
                "used_today": adult_text["used_today"],
                "price_per_message_cents": adult_text["price_cents"],
            },
            "voice": {
                "seconds_remaining": adult_voice["total_remaining"],
                "minutes_remaining": round(adult_voice["total_remaining"] / 60, 2),
                "free_left": adult_voice["free_left"],
                "paid_available": adult_voice["paid_units_available"],
                "used_today": adult_voice["used_today"],
                "price_per_second_cents": adult_voice["price_cents"],
            },
        },
    }

@router.get("/balance")
async def get_balance(
    influencer_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    is_18: bool = True,
):
    # optional: validate influencer exists
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
            InfluencerWallet.is_18 == False,
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