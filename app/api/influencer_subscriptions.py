import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

from app.db.session import get_db
from app.utils.deps import get_current_user
from app.db.models import (
    InfluencerSubscription,
    InfluencerSubscriptionPayment,
    InfluencerWallet,
    User
)
from app.services.influencer_subscriptions import require_active_subscription

log = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/start")
async def start_subscription(
    influencer_id: str,
    price_cents: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        res = await db.execute(
            select(InfluencerSubscription).where(
                InfluencerSubscription.user_id == user.id,
                InfluencerSubscription.influencer_id == influencer_id,
            )
        )
        sub = res.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        next_month = now + timedelta(days=30)

        if sub:
            sub.status = "active"
            sub.price_cents = price_cents
            sub.started_at = now
            sub.current_period_start = now
            sub.current_period_end = next_month
            sub.next_payment_at = next_month
            await db.commit()
            return {"status": "reactivated", "subscription_id": sub.id}

        sub = InfluencerSubscription(
            user_id=user.id,
            influencer_id=influencer_id,
            price_cents=price_cents,
            started_at=now,
            current_period_start=now,
            current_period_end=next_month,
            next_payment_at=next_month,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)

        return {"status": "created", "subscription_id": sub.id}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to start subscription for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to start subscription")

@router.post("/paypal/capture")
async def paypal_capture_subscription(
    subscription_id: int,
    order_id: str,
    amount_cents: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        sub = await db.get(InfluencerSubscription, subscription_id)
        if not sub or sub.user_id != user.id:
            raise HTTPException(404, "Subscription not found")

        existing_payment = await db.scalar(
            select(InfluencerSubscriptionPayment).where(
                InfluencerSubscriptionPayment.provider == "paypal",
                InfluencerSubscriptionPayment.provider_event_id == order_id,
            )
        )
        if existing_payment:
            return {"status": "already recorded"}

        now = datetime.now(timezone.utc)

        base = sub.current_period_end or now
        next_period = base + timedelta(days=30)

        sub.last_payment_at = now
        sub.current_period_start = sub.current_period_end or now
        sub.current_period_end = next_period
        sub.next_payment_at = next_period
        sub.status = "active"

        payment = InfluencerSubscriptionPayment(
            subscription_id=sub.id,
            user_id=user.id,
            influencer_id=sub.influencer_id,
            amount_cents=amount_cents,
            status="succeeded",
            provider="paypal",
            provider_event_id=order_id,
            provider_payload=payload,
            occurred_at=now,
        )
        db.add(payment)

        wallet = await db.scalar(
            select(InfluencerWallet).where(
                InfluencerWallet.user_id == user.id,
                InfluencerWallet.influencer_id == sub.influencer_id,
                InfluencerWallet.is_18 == True,
            )
        )

        if not wallet:
            wallet = InfluencerWallet(
                user_id=user.id,
                influencer_id=sub.influencer_id,
                balance_cents=0,
                is_18=True,
            )
            db.add(wallet)
            await db.flush()

        wallet.balance_cents = (wallet.balance_cents or 0) + int(amount_cents)
        db.add(wallet)

        db.add(sub)
        await db.commit()

        return {
            "status": "payment recorded",
            "subscription_id": sub.id,
            "influencer_id": sub.influencer_id,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "wallet_balance_cents": wallet.balance_cents,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to capture subscription payment: %s", e)
        raise HTTPException(status_code=500, detail="Failed to capture payment")

def _now():
    return datetime.now(timezone.utc)

@router.post("/expire")
async def expire_subscriptions(db: AsyncSession = Depends(get_db)):
    try:
        now = _now()

        await db.execute(
            update(InfluencerSubscription)
            .where(
                InfluencerSubscription.status == "active",
                InfluencerSubscription.current_period_end.isnot(None),
                InfluencerSubscription.current_period_end < now,
            )
            .values(status="expired")
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        log.exception("Failed to expire subscriptions: %s", e)
        raise HTTPException(status_code=500, detail="Failed to expire subscriptions")


class CancelSubscriptionBody(BaseModel):
    influencer_id: str
    reason: str | None = None

@router.post("/cancel")
async def cancel_subscription(
    body: CancelSubscriptionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        now = datetime.now(timezone.utc)

        sub = await db.scalar(
            select(InfluencerSubscription).where(
                InfluencerSubscription.user_id == user.id,
                InfluencerSubscription.influencer_id == body.influencer_id,
            )
        )

        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        if sub.status in ("cancelled", "expired"):
            return {
                "ok": True,
                "status": sub.status,
                "message": "Subscription already cancelled",
            }

        sub.status = "cancelled"
        sub.canceled_at = now
        sub.cancel_reason = body.reason

        db.add(sub)
        await db.commit()
        await db.refresh(sub)

        return {
            "ok": True,
            "user_id": user.id,
            "influencer_id": sub.influencer_id,
            "status": sub.status,
            "canceled_at": sub.canceled_at.isoformat(),
            "current_period_end": sub.current_period_end.isoformat()
            if sub.current_period_end
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to cancel subscription for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")

class Set18Req(BaseModel):
    is_18_selected: bool
    
@router.post("/{influencer_id}/18")
async def set_18_mode(
    influencer_id: str,
    req: Set18Req,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        sub = await require_active_subscription(
            db,
            user_id=user.id,
            influencer_id=influencer_id,
        )

        sub.is_18_selected = bool(req.is_18_selected)
        db.add(sub)
        await db.commit()
        await db.refresh(sub)

        return {
            "ok": True,
            "influencer_id": influencer_id,
            "is_18_selected": sub.is_18_selected,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to set 18 mode for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to update 18+ mode")

@router.get("/{influencer_id}")
async def get_subscription_for_influencer(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        sub = await db.scalar(
            select(InfluencerSubscription).where(
                InfluencerSubscription.user_id == user.id,
                InfluencerSubscription.influencer_id == influencer_id,
            )
        )

        if not sub:
            return {
                "has_subscription": False,
                "is_18_selected": False,
            }

        return {
            "has_subscription": True,
            "status": sub.status,
            "current_period_end": sub.current_period_end,
            "is_18_selected": sub.is_18_selected,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to get subscription for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to get subscription")