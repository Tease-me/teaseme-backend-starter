import logging
import io
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message, Memory, Message18, ContentViolation
from app.db.session import get_db
from app.utils.deps import get_current_user

from sqlalchemy import select, func, desc
from app.db.models import RelationshipState, Influencer,User
from app.utils.s3 import save_sample_audio_to_s3, generate_presigned_url, delete_file_from_s3

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
