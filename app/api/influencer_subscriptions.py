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
)
from app.services.influencer_subscriptions import require_active_subscription


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/start")
async def start_subscription(
    influencer_id: str,
    price_cents: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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

@router.post("/paypal/capture")
async def paypal_capture_subscription(
    subscription_id: int,
    order_id: str,
    amount_cents: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    sub = await db.get(InfluencerSubscription, subscription_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "Subscription not found")

    now = datetime.now(timezone.utc)
    next_period = (sub.current_period_end or now) + timedelta(days=30)

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

    sub.last_payment_at = now
    sub.current_period_start = sub.current_period_end or now
    sub.current_period_end = next_period
    sub.next_payment_at = next_period
    sub.status = "active"

    db.add(payment)
    db.add(sub)
    await db.commit()

    return {"status": "payment recorded"}


def _now():
    return datetime.now(timezone.utc)

@router.post("/expire")
async def expire_subscriptions(db: AsyncSession = Depends(get_db)):
    """
    Marks subscriptions as expired if current_period_end is in the past.
    Call this from cron (or manually).
    """
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

class Set18Req(BaseModel):
    is_18_selected: bool
@router.post("/{influencer_id}/18")
async def set_18_mode(
    influencer_id: str,
    req: Set18Req,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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

@router.get("/{influencer_id}")
async def get_subscription_for_influencer(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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