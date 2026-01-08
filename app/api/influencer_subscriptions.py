from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone

from app.db.session import get_db
from app.utils.deps import get_current_user
from app.db.models import (
    InfluencerSubscription,
    InfluencerSubscriptionPayment,
)

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

@router.get("/me")
async def my_subscriptions(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    res = await db.execute(
        select(InfluencerSubscription)
        .where(InfluencerSubscription.user_id == user.id)
        .order_by(InfluencerSubscription.created_at.desc())
    )
    subs = res.scalars().all()

    return [
        {
            "id": s.id,
            "influencer_id": s.influencer_id,
            "status": s.status,
            "price_cents": s.price_cents,
            "next_payment_at": s.next_payment_at,
        }
        for s in subs
    ]

@router.get("/me/{influencer_id}")
async def my_subscription_for_influencer(
    influencer_id: str,
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

    if not sub:
        raise HTTPException(404, "Not subscribed")

    return {
        "id": sub.id,
        "status": sub.status,
        "price_cents": sub.price_cents,
        "started_at": sub.started_at,
        "current_period_end": sub.current_period_end,
        "next_payment_at": sub.next_payment_at,
    }


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