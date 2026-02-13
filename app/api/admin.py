import logging
import io
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message, Memory, Message18, ContentViolation
from app.db.session import get_db
from app.utils.auth.dependencies import get_current_user

from sqlalchemy import select, func, desc
from app.db.models import RelationshipState, Influencer,User
from app.utils.storage.s3 import save_sample_audio_to_s3, generate_presigned_url, delete_file_from_s3

from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("admin")

@router.delete("/chats/history/{chat_id}")
async def clear_chat_history_admin(
    chat_id: str,
    is_18: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        deleted_msg_ids = []
        deleted_mem_ids = []
        deleted_call_ids = []

        if is_18:
            msg_result = await db.execute(
                delete(Message18).where(Message18.chat_id == chat_id).returning(Message18.id)
            )
            deleted_msg_ids = msg_result.scalars().all()
        else:
            msg_result = await db.execute(
                delete(Message).where(Message.chat_id == chat_id).returning(Message.id)
            )
            deleted_msg_ids = msg_result.scalars().all()

            mem_result = await db.execute(
                delete(Memory).where(Memory.chat_id == chat_id).returning(Memory.id)
            )
            deleted_mem_ids = mem_result.scalars().all()

            call_result = await db.execute(
                delete(CallRecord).where(CallRecord.chat_id == chat_id).returning(CallRecord.conversation_id)
            )
            deleted_call_ids = call_result.scalars().all()

        try:
            redis_history(chat_id).clear()
        except Exception:
            log.warning("[REDIS] Failed to clear history for chat %s", chat_id)

        if not deleted_msg_ids and not deleted_call_ids and not deleted_mem_ids:
            await db.rollback()
            raise HTTPException(status_code=404, detail="Chat not found or empty")

        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to clear chat history")

    return {
        "ok": True,
        "chat_id": chat_id,
        "is_18": is_18,
        "messages_deleted": len(deleted_msg_ids),
        "memories_deleted": len(deleted_mem_ids),
        "call_records_deleted": len(deleted_call_ids),
    }

@router.delete("/chats/history/{influencer_id}/{user_id}")
async def clear_chat_history_by_user_influencer(
    influencer_id: str,
    user_id: int,
    is_18: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Not authorized")

    chat_id = f"{influencer_id}_{user_id}"

    try:
        deleted_msg_ids = []
        deleted_mem_ids = []
        deleted_call_ids = []

        if is_18:
            msg_result = await db.execute(
                delete(Message18).where(Message18.chat_id == chat_id).returning(Message18.id)
            )
            deleted_msg_ids = msg_result.scalars().all()
        else:
            msg_result = await db.execute(
                delete(Message).where(Message.chat_id == chat_id).returning(Message.id)
            )
            deleted_msg_ids = msg_result.scalars().all()

            mem_result = await db.execute(
                delete(Memory).where(Memory.chat_id == chat_id).returning(Memory.id)
            )
            deleted_mem_ids = mem_result.scalars().all()

            call_result = await db.execute(
                delete(CallRecord).where(CallRecord.chat_id == chat_id).returning(CallRecord.conversation_id)
            )
            deleted_call_ids = call_result.scalars().all()

        try:
            redis_history(chat_id).clear()
        except Exception:
            log.warning("[REDIS] Failed to clear history for chat %s", chat_id)

        if not deleted_msg_ids and not deleted_call_ids and not deleted_mem_ids:
            await db.rollback()
            raise HTTPException(status_code=404, detail="Chat not found or empty")

        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to clear chat history")

    return {
        "ok": True,
        "chat_id": chat_id,
        "influencer_id": influencer_id,
        "user_id": user_id,
        "is_18": is_18,
        "messages_deleted": len(deleted_msg_ids),
        "memories_deleted": len(deleted_mem_ids),
        "call_records_deleted": len(deleted_call_ids),
    }

def sentiment_label(score: float) -> str:
    if score <= -60:
        return "HATE"
    elif score <= -20:
        return "DISLIKE"
    elif score < 20:
        return "NEUTRAL"
    elif score < 50:
        return "FRIENDLY"
    elif score < 75:
        return "FLIRTY"
    else:
        return "IN_LOVE"
    
@router.get("/relationships")
async def list_relationships(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(RelationshipState).where(RelationshipState.user_id == user_id)
    res = await db.execute(q)
    rows = res.scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "influencer_id": r.influencer_id,
            "trust": r.trust,
            "closeness": r.closeness,
            "attraction": r.attraction,
            "safety": r.safety,
            "state": r.state,
            "stage_points": r.stage_points,
            "sentiment": sentiment_label(r.sentiment_score),
            "exclusive_agreed": r.exclusive_agreed,
            "girlfriend_confirmed": r.girlfriend_confirmed,
            "sentiment_score": r.sentiment_score,
            "sentiment_delta": r.sentiment_delta,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

@router.get("/users")
async def list_users(
    q: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    if current_user.id != 1:
        

        raise HTTPException(status_code=403, detail="Admin only")

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (User.email.ilike(like)) |
            (User.username.ilike(like)) |
            (User.full_name.ilike(like))
        )

    res = await db.execute(stmt)
    users = res.scalars().all()

    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
        }
        for u in users
    ]

class RelationshipPatch(BaseModel):
    user_id: int
    influencer_id: str

    trust: Optional[float] = Field(default=None, ge=0, le=100)
    closeness: Optional[float] = Field(default=None, ge=0, le=100)
    attraction: Optional[float] = Field(default=None, ge=0, le=100)
    safety: Optional[float] = Field(default=None, ge=0, le=100)

    state: Optional[str] = None

    stage_points: Optional[float] = Field(default=None, ge=0, le=100)
    sentiment_score: Optional[float] = Field(default=None, ge=-100, le=100)
    sentiment_delta: Optional[float] = Field(default=None, ge=-10, le=5)

    exclusive_agreed: Optional[bool] = None
    girlfriend_confirmed: Optional[bool] = None

    dtr_stage: Optional[int] = Field(default=None, ge=0)
    dtr_cooldown_until: Optional[datetime] = None
    last_interaction_at: Optional[datetime] = None


@router.patch("/relationships")
async def patch_relationship(
    payload: RelationshipPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):    
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(RelationshipState).where(
        RelationshipState.user_id == payload.user_id,
        RelationshipState.influencer_id == payload.influencer_id,
    )
    res = await db.execute(q)
    rel = res.scalar_one_or_none()

    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")

    if payload.trust is not None:
        rel.trust = payload.trust
    if payload.closeness is not None:
        rel.closeness = payload.closeness
    if payload.attraction is not None:
        rel.attraction = payload.attraction
    if payload.safety is not None:
        rel.safety = payload.safety

    if payload.state is not None:
        rel.state = payload.state

    if payload.stage_points is not None:
        rel.stage_points = payload.stage_points

    if payload.sentiment_score is not None:
        rel.sentiment_score = payload.sentiment_score
    
    if payload.sentiment_delta is not None:
        rel.sentiment_delta = payload.sentiment_delta

    if payload.exclusive_agreed is not None:
        rel.exclusive_agreed = payload.exclusive_agreed
    if payload.girlfriend_confirmed is not None:
        rel.girlfriend_confirmed = payload.girlfriend_confirmed

    if payload.dtr_stage is not None:
        rel.dtr_stage = payload.dtr_stage
    if payload.dtr_cooldown_until is not None:
        rel.dtr_cooldown_until = payload.dtr_cooldown_until

    if payload.last_interaction_at is not None:
        rel.last_interaction_at = payload.last_interaction_at

    if rel.girlfriend_confirmed:
        rel.state = "GIRLFRIEND"
        rel.exclusive_agreed = True

    rel.updated_at = datetime.now(timezone.utc)

    db.add(rel)
    await db.commit()
    await db.refresh(rel)

    return {
        "ok": True,
        "relationship": {
            "id": rel.id,
            "user_id": rel.user_id,
            "influencer_id": rel.influencer_id,
            "trust": rel.trust,
            "closeness": rel.closeness,
            "attraction": rel.attraction,
            "safety": rel.safety,
            "state": rel.state,
            "stage_points": rel.stage_points,
            "sentiment_score": rel.sentiment_score,
            "sentiment_delta": rel.sentiment_delta,
            "exclusive_agreed": rel.exclusive_agreed,
            "girlfriend_confirmed": rel.girlfriend_confirmed,
            "updated_at": rel.updated_at.isoformat() if rel.updated_at else None,
        }
    }

@router.post("/relationships/update")
async def update_relationship(
    payload: RelationshipPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):  
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(RelationshipState).where(
        RelationshipState.user_id == payload.user_id,
        RelationshipState.influencer_id == payload.influencer_id,
    )
    res = await db.execute(q)
    rel = res.scalar_one_or_none()

    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")

    if payload.trust is not None:
        rel.trust = payload.trust
    if payload.closeness is not None:
        rel.closeness = payload.closeness
    if payload.attraction is not None:
        rel.attraction = payload.attraction
    if payload.safety is not None:
        rel.safety = payload.safety

    if payload.state is not None:
        rel.state = payload.state
    if payload.stage_points is not None:
        rel.stage_points = payload.stage_points
    if payload.sentiment_score is not None:
        rel.sentiment_score = payload.sentiment_score
    if payload.sentiment_delta is not None:
        rel.sentiment_delta = payload.sentiment_delta

    if payload.exclusive_agreed is not None:
        rel.exclusive_agreed = payload.exclusive_agreed
    if payload.girlfriend_confirmed is not None:
        rel.girlfriend_confirmed = payload.girlfriend_confirmed

    if rel.girlfriend_confirmed:
        rel.state = "GIRLFRIEND"
        rel.exclusive_agreed = True

    rel.updated_at = datetime.now(timezone.utc)

    db.add(rel)
    await db.commit()
    await db.refresh(rel)

    return {"ok": True}


@router.post("/influencer/{influencer_id}/samples")
async def upload_influencer_sample(
    influencer_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    s3_key = await save_sample_audio_to_s3(
        io.BytesIO(file_bytes),
        file.filename or "sample.mp3",
        file.content_type or "audio/mpeg",
        influencer_id,
    )

    sample_entry = {
        "s3_key": s3_key,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if influencer.samples is None:
        influencer.samples = [sample_entry]
    else:
        influencer.samples = influencer.samples + [sample_entry]

    await db.commit()
    await db.refresh(influencer)

    return {
        "id": s3_key,
        "s3_key": s3_key,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "url": generate_presigned_url(s3_key),
        "created_at": sample_entry["created_at"],
    }


@router.delete("/influencer/{influencer_id}/samples/{sample_id}")
async def delete_influencer_sample(
    influencer_id: str,
    sample_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    if not influencer.samples:
        raise HTTPException(status_code=404, detail="Sample not found")

    sample = next((s for s in influencer.samples if s.get("s3_key") == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    influencer.samples = [s for s in influencer.samples if s.get("s3_key") != sample_id]

    try:
        await delete_file_from_s3(sample_id)
    except Exception:
        log.warning("Failed to delete S3 sample file %s", sample_id, exc_info=True)

    await db.commit()

    return {"ok": True, "deleted_id": sample_id}

@router.get("/moderation")
async def get_moderation_dashboard(
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    current_user: User = Depends(get_current_user),

    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    users_stmt = select(User).where(User.moderation_status != "CLEAN")
    users_stmt = users_stmt.order_by(desc(User.last_violation_at))
    users_result = await db.execute(users_stmt)
    flagged_users = users_result.scalars().all()
    
    violations_stmt = select(ContentViolation)
    if category:
        violations_stmt = violations_stmt.where(ContentViolation.category == category)
    if user_id:
        violations_stmt = violations_stmt.where(ContentViolation.user_id == user_id)
    
    count_stmt = select(func.count()).select_from(violations_stmt.subquery())
    total_violations = (await db.execute(count_stmt)).scalar() or 0
    
    violations_stmt = violations_stmt.order_by(desc(ContentViolation.created_at))
    violations_stmt = violations_stmt.offset((page - 1) * page_size).limit(page_size)
    violations_result = await db.execute(violations_stmt)
    violations = violations_result.scalars().all()
    
    return {
        "flagged_users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "moderation_status": u.moderation_status,
                "violation_count": u.violation_count,
                "first_violation_at": u.first_violation_at.isoformat() if u.first_violation_at else None,
                "last_violation_at": u.last_violation_at.isoformat() if u.last_violation_at else None,
            }
            for u in flagged_users
        ],
        "violations": {
            "total": total_violations,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": v.id,
                    "user_id": v.user_id,
                    "chat_id": v.chat_id,
                    "influencer_id": v.influencer_id,
                    "message_content": v.message_content,
                    "category": v.category,
                    "severity": v.severity,
                    "keyword_matched": v.keyword_matched,
                    "ai_confidence": v.ai_confidence,
                    "detection_tier": v.detection_tier,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in violations
            ]
        }
    }


# ── API Usage Analytics ──────────────────────────────────────────
from app.db.models.api_usage import ApiUsageLog
from datetime import timedelta


@router.get("/api-usage/summary")
async def get_api_usage_summary(
    period: str = "24h",
    group_by: str = "category",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregated API usage analytics.

    Query params:
        period: "1h" | "24h" | "7d" | "30d" | "90d"
        group_by: "category" | "model" | "provider" | "purpose" | "user" | "influencer"
    """
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    period_map = {
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    delta = period_map.get(period)
    if not delta:
        raise HTTPException(400, f"Invalid period. Use: {', '.join(period_map.keys())}")

    cutoff = datetime.now(timezone.utc) - delta

    group_col_map = {
        "category": ApiUsageLog.category,
        "model": ApiUsageLog.model,
        "provider": ApiUsageLog.provider,
        "purpose": ApiUsageLog.purpose,
        "user": ApiUsageLog.user_id,
        "influencer": ApiUsageLog.influencer_id,
    }
    group_col = group_col_map.get(group_by)
    if not group_col:
        raise HTTPException(400, f"Invalid group_by. Use: {', '.join(group_col_map.keys())}")

    stmt = (
        select(
            group_col.label("group_key"),
            func.count().label("total_calls"),
            func.sum(ApiUsageLog.input_tokens).label("total_input_tokens"),
            func.sum(ApiUsageLog.output_tokens).label("total_output_tokens"),
            func.sum(ApiUsageLog.total_tokens).label("total_tokens"),
            func.sum(ApiUsageLog.estimated_cost_micros).label("total_cost_micros"),
            func.avg(ApiUsageLog.latency_ms).label("avg_latency_ms"),
            func.max(ApiUsageLog.latency_ms).label("max_latency_ms"),
            func.sum(ApiUsageLog.duration_secs).label("total_duration_secs"),
            func.count().filter(ApiUsageLog.success == False).label("error_count"),
        )
        .where(ApiUsageLog.created_at >= cutoff)
        .group_by(group_col)
        .order_by(func.count().desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return {
        "period": period,
        "group_by": group_by,
        "cutoff": cutoff.isoformat(),
        "groups": [
            {
                "key": str(r.group_key) if r.group_key is not None else "unknown",
                "total_calls": r.total_calls,
                "total_input_tokens": r.total_input_tokens or 0,
                "total_output_tokens": r.total_output_tokens or 0,
                "total_tokens": r.total_tokens or 0,
                # estimated_cost_micros stores raw units (1M units = 1 microdollar)
                "total_cost_micros": round((r.total_cost_micros or 0) / 1_000_000, 2) if r.total_cost_micros else 0,
                "estimated_cost_usd": round((r.total_cost_micros or 0) / 1_000_000_000_000, 9),
                "avg_latency_ms": round(r.avg_latency_ms, 1) if r.avg_latency_ms else None,
                "max_latency_ms": r.max_latency_ms,
                "total_duration_secs": round(r.total_duration_secs, 1) if r.total_duration_secs else None,
                "error_count": r.error_count or 0,
                "error_rate": round((r.error_count or 0) / r.total_calls * 100, 2) if r.total_calls > 0 else 0,
            }
            for r in rows
        ],
    }


@router.get("/api-usage/top-users")
async def get_top_api_users(
    period: str = "24h",
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top users by API consumption."""
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    period_map = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "90d": 2160}
    hours = period_map.get(period, 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(
            ApiUsageLog.user_id,
            func.count().label("total_calls"),
            func.sum(ApiUsageLog.total_tokens).label("total_tokens"),
            func.sum(ApiUsageLog.estimated_cost_micros).label("total_cost_micros"),
        )
        .where(ApiUsageLog.created_at >= cutoff, ApiUsageLog.user_id.isnot(None))
        .group_by(ApiUsageLog.user_id)
        .order_by(func.sum(ApiUsageLog.estimated_cost_micros).desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return {
        "period": period,
        "users": [
            {
                "user_id": r.user_id,
                "total_calls": r.total_calls,
                "total_tokens": r.total_tokens or 0,
                # estimated_cost_micros stores raw units (1M units = 1 microdollar)
                "total_cost_micros": round((r.total_cost_micros or 0) / 1_000_000, 2) if r.total_cost_micros else 0,
                "estimated_cost_usd": round((r.total_cost_micros or 0) / 1_000_000_000_000, 9),
            }
            for r in rows
        ],
    }


@router.get("/api-usage/top-influencers")
async def get_top_api_influencers(
    period: str = "24h",
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top influencers by API usage they drive."""
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    period_map = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "90d": 2160}
    hours = period_map.get(period, 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(
            ApiUsageLog.influencer_id,
            func.count().label("total_calls"),
            func.sum(ApiUsageLog.total_tokens).label("total_tokens"),
            func.sum(ApiUsageLog.estimated_cost_micros).label("total_cost_micros"),
            func.sum(ApiUsageLog.duration_secs).label("total_call_secs"),
        )
        .where(ApiUsageLog.created_at >= cutoff, ApiUsageLog.influencer_id.isnot(None))
        .group_by(ApiUsageLog.influencer_id)
        .order_by(func.sum(ApiUsageLog.estimated_cost_micros).desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return {
        "period": period,
        "influencers": [
            {
                "influencer_id": r.influencer_id,
                "total_calls": r.total_calls,
                "total_tokens": r.total_tokens or 0,
                # estimated_cost_micros stores raw units (1M units = 1 microdollar)
                "total_cost_micros": round((r.total_cost_micros or 0) / 1_000_000, 2) if r.total_cost_micros else 0,
                "estimated_cost_usd": round((r.total_cost_micros or 0) / 1_000_000_000_000, 9),
                "total_call_secs": round(r.total_call_secs, 1) if r.total_call_secs else 0,
            }
            for r in rows
        ],
    }


@router.get("/api-usage/errors")
async def get_api_errors(
    period: str = "24h",
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent API errors for debugging."""
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")

    period_map = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "90d": 2160}
    hours = period_map.get(period, 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(ApiUsageLog)
        .where(ApiUsageLog.created_at >= cutoff, ApiUsageLog.success == False)
        .order_by(ApiUsageLog.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    errors = result.scalars().all()

    return {
        "period": period,
        "total_errors": len(errors),
        "errors": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat(),
                "category": e.category,
                "provider": e.provider,
                "model": e.model,
                "purpose": e.purpose,
                "user_id": e.user_id,
                "influencer_id": e.influencer_id,
                "error_message": e.error_message,
            }
            for e in errors
        ],
    }



