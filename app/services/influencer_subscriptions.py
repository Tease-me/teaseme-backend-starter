from datetime import datetime, timezone
from re import sub
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.db.models import InfluencerSubscription

def _now():
    return datetime.now(timezone.utc)

async def require_active_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    influencer_id: str,
) -> InfluencerSubscription:
    res = await db.execute(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user_id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )

    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "SUBSCRIPTION_REQUIRED",
                "message": "You need subscription to chat with this influencer.",
                "influencer_id": influencer_id,
            },
        )
    
    if sub.current_period_end and sub.current_period_end < _now():
        raise HTTPException(
            status_code=402,
            detail={
                "error": "SUBSCRIPTION_EXPIRED",
                "message": "Your subscription expired. Please renew.",
                "influencer_id": influencer_id,
            },
        )

    return sub


async def get_valid_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    influencer_id: str,
) -> InfluencerSubscription:
    res = await db.execute(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user_id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )

    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "SUBSCRIPTION_REQUIRED",
                "message": "You need subscription to chat with this influencer.",
                "influencer_id": influencer_id,
            },
        )
    
    if sub.current_period_end and sub.current_period_end < _now():
        raise HTTPException(
            status_code=402,
            detail={
                "error": "SUBSCRIPTION_EXPIRED",
                "message": "Your subscription expired. Please renew.",
                "influencer_id": influencer_id,
            },
        )

    return sub

async def can_toggle_18_plus(
    db: AsyncSession,
    user_id: int,
    influencer_id: str,
) -> bool:
    res = await db.execute(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user_id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )
    sub = res.scalar_one_or_none()
    if not sub:
        return False

    now = _now()
    if sub.current_period_end and sub.current_period_end < now:
        return False

    return True