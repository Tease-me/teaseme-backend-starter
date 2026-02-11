import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_, not_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    User,
    Influencer,
    InfluencerWallet,
    RelationshipState,
    ReEngagementLog,
    Subscription,
    Message,
)
from app.utils.messaging.push import send_push_rich
from app.agents.turn_handler import handle_turn
from app.services.chat_service import get_or_create_chat
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys
# from app.utils.s3 import generate_presigned_url  # - text only for now

log = logging.getLogger("re_engagement")

DEFAULT_INACTIVE_DAYS = 3
DEFAULT_MIN_BALANCE_CENTS = 50_00  # $50


async def find_inactive_high_balance_users(
    db: AsyncSession,
    inactive_days: int = DEFAULT_INACTIVE_DAYS,
    min_balance_cents: int = DEFAULT_MIN_BALANCE_CENTS,
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)

    already_notified = (
        select(ReEngagementLog.id)
        .where(
            ReEngagementLog.user_id == RelationshipState.user_id,
            ReEngagementLog.influencer_id == RelationshipState.influencer_id,
            ReEngagementLog.triggered_at > RelationshipState.last_interaction_at,
        )
        .exists()
    )

    query = (
        select(
            RelationshipState.user_id,
            RelationshipState.influencer_id,
            InfluencerWallet.balance_cents,
            RelationshipState.last_interaction_at,
            Influencer.display_name.label("influencer_name"),
        )
        .join(
            InfluencerWallet,
            and_(
                InfluencerWallet.user_id == RelationshipState.user_id,
                InfluencerWallet.influencer_id == RelationshipState.influencer_id,
            ),
        )
        .join(
            Influencer,
            Influencer.id == RelationshipState.influencer_id,
        )
        .where(
            RelationshipState.last_interaction_at < cutoff,
            InfluencerWallet.balance_cents >= min_balance_cents,
            not_(already_notified),
        )
        .order_by(InfluencerWallet.balance_cents.desc())
    )

    result = await db.execute(query)
    rows = result.all()

    now = datetime.now(timezone.utc)
    return [
        {
            "user_id": row.user_id,
            "influencer_id": row.influencer_id,
            "balance_cents": row.balance_cents,
            "last_interaction_at": row.last_interaction_at,
            "days_inactive": (now - row.last_interaction_at).days,
            "influencer_name": row.influencer_name,
        }
        for row in rows
    ]


async def generate_reengagement_via_turn_handler(
    db: AsyncSession,
    user_id: int,
    influencer_id: str,
    influencer_name: str,
    days_inactive: int,
) -> tuple[str, str]:
    prompt_template = await get_system_prompt(db, prompt_keys.REENGAGEMENT_PROMPT)
    #backup can be removed later after testing
    if not prompt_template:
        prompt_template = (
            "[SYSTEM: The user hasn't messaged you in {days_inactive} days. "
            "Send them a flirty, personalized message to bring them back. "
            "Be sweet and miss them. Keep it short and enticing - 1-2 sentences max. "
            "Don't mention specific days or numbers - just express that you've missed them.]"
        )
    
    reengagement_prompt = prompt_template.format(days_inactive=days_inactive)
    
    chat_id = await get_or_create_chat(db, user_id, influencer_id)
    
    try:
        ai_response = await handle_turn(
            message=reengagement_prompt,
            chat_id=chat_id,
            influencer_id=influencer_id,
            user_id=str(user_id),
            db=db,
            is_audio=False,
        )
        
        ai_message = Message(
            chat_id=chat_id,
            sender="ai",
            content=ai_response,
            channel="text",
        )
        db.add(ai_message)
        await db.commit()
        
        log.info(f"[RE-ENGAGE] AI generated message for user {user_id}: {ai_response[:50]}...")
        
        title = f"{influencer_name} misses you 💕"
        
        return title, ai_response
        
    except Exception as e:
        log.error(f"[RE-ENGAGE] AI generation failed for user {user_id}: {e}", exc_info=True)
        log.info(f"[RE-ENGAGE] Falling back to static template for user {user_id}")

# TODO: Re-enable when ready to send images/videos
# async def get_influencer_media(
#     db: AsyncSession,
#     influencer_id: str,
# ) -> Optional[dict]:
#     """
#     Replace this with actual media fetching logic / video generation.
#     """
#     influencer = await db.get(Influencer, influencer_id)
#     if not influencer or not influencer.samples:
#         return None
#
#     media_samples = [
#         s for s in influencer.samples
#         if s.get("type") in ("image", "video") and s.get("key")
#     ]
#
#     if not media_samples:
#         if influencer.profile_photo_key:
#             return {
#                 "type": "image",
#                 "url": generate_presigned_url(influencer.profile_photo_key),
#             }
#         return None
#
#     sample = random.choice(media_samples)
#     return {
#         "type": sample.get("type", "image"),
#         "url": generate_presigned_url(sample["key"]),
#     }


async def send_reengagement_notification(
    db: AsyncSession,
    user_id: int,
    influencer_id: str,
    influencer_name: str,
    balance_cents: int,
    days_inactive: int,
) -> dict:
    title, body = await generate_reengagement_via_turn_handler(
        db=db,
        user_id=user_id,
        influencer_id=influencer_id,
        influencer_name=influencer_name,
        days_inactive=days_inactive,
    )

    media_url = None
    notification_type = "text"

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    subscriptions = result.scalars().all()

    if not subscriptions:
        log.warning(f"[RE-ENGAGE] No push subscriptions for user {user_id}")
        log_entry = ReEngagementLog(
            user_id=user_id,
            influencer_id=influencer_id,
            notification_type=notification_type,
            title=title,
            body=body,
            media_url=media_url,
            delivered=False,
            delivery_error="No push subscriptions",
            subscriptions_targeted=0,
            subscriptions_succeeded=0,
            wallet_balance_cents=balance_cents,
            days_inactive=days_inactive,
        )
        db.add(log_entry)
        await db.commit()
        return {"success": False, "error": "No subscriptions", "user_id": user_id}

    succeeded = 0
    errors = []

    for sub in subscriptions:
        try:
            await send_push_rich(
                subscription=sub,
                title=title,
                body=body,
                image_url=media_url if notification_type == "image" else None,
                influencer_id=influencer_id,
            )
            succeeded += 1
        except Exception as e:
            errors.append(str(e))
            log.error(f"[RE-ENGAGE] Push failed for user {user_id}: {e}")

    log_entry = ReEngagementLog(
        user_id=user_id,
        influencer_id=influencer_id,
        notification_type=notification_type,
        title=title,
        body=body,
        media_url=media_url,
        delivered=succeeded > 0,
        delivery_error="; ".join(errors) if errors else None,
        subscriptions_targeted=len(subscriptions),
        subscriptions_succeeded=succeeded,
        wallet_balance_cents=balance_cents,
        days_inactive=days_inactive,
    )
    db.add(log_entry)
    await db.commit()

    log.info(
        f"[RE-ENGAGE] Sent to user {user_id} for {influencer_id}: "
        f"{succeeded}/{len(subscriptions)} succeeded"
    )

    return {
        "success": succeeded > 0,
        "user_id": user_id,
        "influencer_id": influencer_id,
        "subscriptions_targeted": len(subscriptions),
        "subscriptions_succeeded": succeeded,
    }


async def run_reengagement_job(
    db: AsyncSession,
    inactive_days: int = DEFAULT_INACTIVE_DAYS,
    min_balance_cents: int = DEFAULT_MIN_BALANCE_CENTS,
    dry_run: bool = False,
) -> dict:
    log.info(
        f"[RE-ENGAGE] Starting job: inactive_days={inactive_days}, "
        f"min_balance=${min_balance_cents/100:.2f}, dry_run={dry_run}"
    )

    eligible = await find_inactive_high_balance_users(
        db,
        inactive_days=inactive_days,
        min_balance_cents=min_balance_cents,
    )

    log.info(f"[RE-ENGAGE] Found {len(eligible)} eligible user-influencer pairs")

    if dry_run:
        return {
            "dry_run": True,
            "eligible_count": len(eligible),
            "eligible": eligible,
        }

    results = []
    for entry in eligible:
        try:
            result = await send_reengagement_notification(
                db=db,
                user_id=entry["user_id"],
                influencer_id=entry["influencer_id"],
                influencer_name=entry["influencer_name"],
                balance_cents=entry["balance_cents"],
                days_inactive=entry["days_inactive"],
            )
            results.append(result)
        except Exception as e:
            log.exception(f"[RE-ENGAGE] Error sending to user {entry['user_id']}: {e}")
            results.append({
                "success": False,
                "user_id": entry["user_id"],
                "influencer_id": entry["influencer_id"],
                "error": str(e),
            })

    succeeded = sum(1 for r in results if r.get("success"))
    failed = len(results) - succeeded

    log.info(f"[RE-ENGAGE] Job complete: {succeeded} succeeded, {failed} failed")

    return {
        "dry_run": False,
        "eligible_count": len(eligible),
        "sent_count": succeeded,
        "failed_count": failed,
        "results": results,
    }


async def get_reengagement_stats(
    db: AsyncSession,
    days: int = 7,
) -> dict:
 
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_result = await db.execute(
        select(func.count(ReEngagementLog.id)).where(
            ReEngagementLog.triggered_at >= since
        )
    )
    total_sent = total_result.scalar() or 0

    delivered_result = await db.execute(
        select(func.count(ReEngagementLog.id)).where(
            ReEngagementLog.triggered_at >= since,
            ReEngagementLog.delivered.is_(True),
        )
    )
    delivered = delivered_result.scalar() or 0

    type_result = await db.execute(
        select(
            ReEngagementLog.notification_type,
            func.count(ReEngagementLog.id),
        )
        .where(ReEngagementLog.triggered_at >= since)
        .group_by(ReEngagementLog.notification_type)
    )
    by_type = {row[0]: row[1] for row in type_result.all()}

    recent_result = await db.execute(
        select(ReEngagementLog)
        .where(ReEngagementLog.triggered_at >= since)
        .order_by(ReEngagementLog.triggered_at.desc())
        .limit(20)
    )
    recent = recent_result.scalars().all()

    return {
        "period_days": days,
        "total_sent": total_sent,
        "delivered": delivered,
        "delivery_rate": (delivered / total_sent * 100) if total_sent > 0 else 0,
        "by_type": by_type,
        "recent": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "influencer_id": log.influencer_id,
                "type": log.notification_type,
                "delivered": log.delivered,
                "days_inactive": log.days_inactive,
                "balance_cents": log.wallet_balance_cents,
                "triggered_at": log.triggered_at.isoformat(),
            }
            for log in recent
        ],
    }
