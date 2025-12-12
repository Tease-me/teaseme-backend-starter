import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("admin")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        # Delete transcript messages tied to this conversation first to avoid FK issues.
        msg_delete_res = await db.execute(
            delete(Message)
            .where(Message.conversation_id == conversation_id)
            .returning(Message.id)
        )
        messages_deleted = len(msg_delete_res.scalars().all())

        call_delete_res = await db.execute(
            delete(CallRecord)
            .where(CallRecord.conversation_id == conversation_id)
            .returning(CallRecord.conversation_id)
        )
        call_deleted = bool(call_delete_res.scalar_one_or_none())

        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete conversation")

    if not call_deleted and messages_deleted == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "call_deleted": call_deleted,
        "messages_deleted": messages_deleted,
    }


@router.delete("/chats/{chat_id}/history")
async def clear_chat_history_admin(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            delete(Message).where(Message.chat_id == chat_id).returning(Message.id)
        )
        deleted_ids = result.scalars().all()

        try:
            redis_history(chat_id).clear()
        except Exception:
            log.warning("[REDIS] Failed to clear history for chat %s", chat_id)

        if not deleted_ids:
            await db.rollback()
            raise HTTPException(status_code=404, detail="Chat not found or empty")

        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to clear chat history")

    return {"ok": True, "chat_id": chat_id, "deleted_count": len(deleted_ids)}
