import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message, Memory
from app.db.session import get_db

from sqlalchemy import select
from app.db.models import RelationshipState, User


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
            "exclusive_agreed": r.exclusive_agreed,
            "girlfriend_confirmed": r.girlfriend_confirmed,
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