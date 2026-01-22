import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.models import RelationshipState

log = logging.getLogger("inactivity")

REENGAGEMENT_INACTIVE_DAYS = 3
REENGAGEMENT_MIN_BALANCE_CENTS = 10_000  # $100


def apply_inactivity_decay(rel, now: datetime) -> float:
    last = rel.last_interaction_at or rel.updated_at
    if not last:
        return 0.0

    days_idle = (now - last).total_seconds() / 86400.0
    if days_idle < 2:
        return days_idle

    rel.closeness = max(0.0, rel.closeness - min(8.0, days_idle * 1.5))

    if days_idle >= 3:
        rel.attraction = max(0.0, rel.attraction - min(10.0, days_idle * 1.8))

    if days_idle >= 7:
        rel.trust = max(0.0, rel.trust - min(5.0, (days_idle - 6) * 0.8))

    return days_idle


async def check_and_trigger_reengagement(
    db: "AsyncSession",
    user_id: int,
    influencer_id: str,
    days_idle: float,
) -> bool:
    if days_idle < REENGAGEMENT_INACTIVE_DAYS:
        return False

    from sqlalchemy import select, and_
    from app.db.models import InfluencerWallet, ReEngagementLog, Influencer, Subscription

    wallet_result = await db.execute(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user_id,
            InfluencerWallet.influencer_id == influencer_id,
        )
    )
    wallets = wallet_result.scalars().all()
    
    total_balance = sum(w.balance_cents or 0 for w in wallets)
    
    if total_balance < REENGAGEMENT_MIN_BALANCE_CENTS:
        return False

    from app.db.models import RelationshipState
    rel_result = await db.execute(
        select(RelationshipState.last_interaction_at).where(
            RelationshipState.user_id == user_id,
            RelationshipState.influencer_id == influencer_id,
        )
    )
    last_interaction = rel_result.scalar()

    if last_interaction:
        log_result = await db.execute(
            select(ReEngagementLog.id).where(
                ReEngagementLog.user_id == user_id,
                ReEngagementLog.influencer_id == influencer_id,
                ReEngagementLog.triggered_at > last_interaction,
            ).limit(1)
        )
        if log_result.scalar():
            return False

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        return False

    sub_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id).limit(1)
    )
    if not sub_result.scalar():
        log.info(f"[RE-ENGAGE] User {user_id} has no push subscriptions, skipping")
        return False

    from app.services.re_engagement import send_reengagement_notification

    log.info(
        f"[RE-ENGAGE] Triggering for user={user_id} influencer={influencer_id} "
        f"balance=${total_balance/100:.2f} days_idle={days_idle:.1f}"
    )

    asyncio.create_task(
        send_reengagement_notification(
            db=db,
            user_id=user_id,
            influencer_id=influencer_id,
            influencer_name=influencer.display_name,
            balance_cents=total_balance,
            days_inactive=int(days_idle),
        )
    )

    return True