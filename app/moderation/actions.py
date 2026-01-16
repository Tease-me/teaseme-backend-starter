import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, ContentViolation
from app.moderation.detector import ModerationResult

log = logging.getLogger("moderation.actions")


async def flag_user(
    db: AsyncSession,
    user_id: int,
    category: str
) -> None:
    user = await db.get(User, user_id)
    if not user:
        log.error(f"User {user_id} not found for flagging")
        return
    
    now = datetime.now(timezone.utc)
    
    # Update violation count
    user.violation_count = (user.violation_count or 0) + 1
    user.last_violation_at = now
    
    if not user.first_violation_at:
        user.first_violation_at = now
    
    # Update status based on count
    if user.moderation_status == "BANNED":
        pass  # Don't change if already banned
    elif user.violation_count >= 3:
        user.moderation_status = "UNDER_REVIEW"
    else:
        user.moderation_status = "FLAGGED"
    
    log.info(
        f"User {user_id} flagged: count={user.violation_count} "
        f"status={user.moderation_status} category={category}"
    )


async def handle_violation(
    db: AsyncSession,
    user_id: int,
    chat_id: str,
    influencer_id: str,
    message: str,
    context: str,
    result: ModerationResult
) -> ContentViolation:
 
    violation = ContentViolation(
        user_id=user_id,
        chat_id=chat_id,
        influencer_id=influencer_id,
        message_content=message,
        message_context=context[:2000] if context else None,  # Limit context size
        category=result.category or "UNKNOWN",
        severity=result.severity or "MEDIUM",
        keyword_matched=result.keyword,
        ai_confidence=result.confidence,
        ai_reasoning=result.reason,
        detection_tier=result.tier,
        created_at=datetime.now(timezone.utc)
    )
    db.add(violation)
    
    await flag_user(db, user_id, result.category or "UNKNOWN")
    
    await db.commit()
    await db.refresh(violation)
    
    log.warning(
        f"Violation logged: id={violation.id} user={user_id} "
        f"category={result.category} tier={result.tier}"
    )
    
    return violation


async def clear_user_flag(
    db: AsyncSession,
    user_id: int,
    admin_email: str,
    notes: str = ""
) -> None:
 
    user = await db.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    user.moderation_status = "CLEAN"
    # Keep violation_count and dates for audit trail
    
    await db.commit()
    
    log.info(f"User {user_id} cleared by {admin_email}: {notes}")


async def ban_user(
    db: AsyncSession,
    user_id: int,
    admin_email: str,
    notes: str = ""
) -> None:
  
    user = await db.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    user.moderation_status = "BANNED"
    
    await db.commit()
    
    log.warning(f"User {user_id} BANNED by {admin_email}: {notes}")
