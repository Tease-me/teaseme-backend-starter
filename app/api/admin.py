import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message, Memory
from app.db.session import get_db

from sqlalchemy import select
from app.db.models import RelationshipState, User

from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("admin")

@router.delete("/chats/history/{chat_id}")
async def clear_chat_history_admin(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
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
async def list_relationships(user_id: int, db: AsyncSession = Depends(get_db)):
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
            "sentiment_score": r.sentiment_score,
            "sentiment": sentiment_label(r.sentiment_score),
            "exclusive_agreed": r.exclusive_agreed,
            "girlfriend_confirmed": r.girlfriend_confirmed,
            "sentiment_score": r.sentiment_score,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

@router.get("/users")
async def list_users(q: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(User)

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
async def patch_relationship(payload: RelationshipPatch, db: AsyncSession = Depends(get_db)):
    q = select(RelationshipState).where(
        RelationshipState.user_id == payload.user_id,
        RelationshipState.influencer_id == payload.influencer_id,
    )
    res = await db.execute(q)
    rel = res.scalar_one_or_none()

    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")

    # apply updates if provided
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

    # optional: keep girlfriend sticky
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
async def update_relationship(payload: RelationshipPatch, db: AsyncSession = Depends(get_db)):
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