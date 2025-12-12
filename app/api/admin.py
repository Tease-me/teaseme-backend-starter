import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn_handler import redis_history
from app.db.models import CallRecord, Message, Memory
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("admin")

@router.delete("/chats/{chat_id}/history")
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
