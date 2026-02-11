"""
Shared chat buffering and websocket logic for both regular and 18+ chats.

This service handles:
- Message buffering and batching
- Smart flush timing (detects sentence endings)
- WebSocket message handling
- Billing and charging
- AI turn handling
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Message18, Chat, Chat18
from app.services.embeddings import get_embedding
from app.services.billing import charge_feature
from app.relationship import get_relationship_payload
from app.services.user import _get_usage_snapshot_simple

log = logging.getLogger(__name__)


@dataclass
class ChatConfig:
    """Configuration for different chat types (regular vs 18+)."""
    is_18plus: bool
    message_model: type  # Message or Message18
    chat_model: type  # Chat or Chat18
    text_feature: str  # "text" or "text_18"
    voice_feature: str  # "voice" or "voice_18"
    turn_handler: Callable  # handle_turn or handle_turn_18
    include_relationship: bool = True  # Whether to include relationship payload
    
    @classmethod
    def regular(cls, turn_handler):
        """Configuration for regular (non-18+) chats."""
        return cls(
            is_18plus=False,
            message_model=Message,
            chat_model=Chat,
            text_feature="text",
            voice_feature="voice",
            turn_handler=turn_handler,
            include_relationship=True,
        )
    
    @classmethod
    def adult(cls, turn_handler):
        """Configuration for 18+ chats."""
        return cls(
            is_18plus=True,
            message_model=Message18,
            chat_model=Chat18,
            text_feature="text_18",
            voice_feature="voice_18",
            turn_handler=turn_handler,
            include_relationship=False,
        )


class _Buf:
    """Buffer for accumulating messages before processing."""
    __slots__ = ("messages", "timer", "lock", "timezone")
    
    def __init__(self) -> None:
        self.messages: List[str] = []
        self.timer: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        self.timezone: Optional[str] = None


# Global buffer storage per chat_id
_buffers: Dict[str, _Buf] = {}


def _ends_thought(msg: str) -> bool:
    """
    Check if a message represents a complete thought.
    
    Returns True if the message ends with strong punctuation or emojis
    that typically indicate the end of a sentence or thought.
    """
    if not msg:
        return False
    msg = msg.strip()
    strong = (".", "!", "?", "…")
    end_emojis = ("👍", "😉", "😂", "😅", "🤣", "😍", "😘")
    return msg.endswith(strong) or msg.endswith(end_emojis)


async def get_message_context(
    db: AsyncSession,
    chat_id: str,
    message_model: type,
    limit: int = 6
) -> str:
    """
    Get recent message context for a chat.
    
    Args:
        db: Database session
        chat_id: Chat identifier
        message_model: Message or Message18 class
        limit: Number of recent messages to include
        
    Returns:
        Formatted context string with "User:" and "AI:" prefixes
    """
    recent_res = await db.execute(
        select(message_model)
        .where(message_model.chat_id == chat_id)
        .order_by(message_model.created_at.desc())
        .limit(limit)
    )
    recent = list(recent_res.scalars().all())
    recent.reverse()
    context_lines = []
    for msg in recent:
        speaker = "User" if msg.sender == "user" else "AI"
        context_lines.append(f"{speaker}: {msg.content or ''}")
    return "\n".join(context_lines)


async def queue_message(
    chat_id: str,
    msg: str,
    ws: WebSocket,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
    config: ChatConfig,
    user_timezone: Optional[str] = None,
    timeout_sec: float = 2.5,
) -> None:
    """
    Queue a message for processing with smart batching.
    
    Messages are buffered and either:
    1. Flushed immediately if they end a complete thought
    2. Flushed after a timeout if more messages arrive
    
    Args:
        chat_id: Chat identifier
        msg: Message text
        ws: WebSocket connection
        influencer_id: Influencer identifier
        user_id: User identifier
        db: Database session
        config: Chat configuration (regular or 18+)
        user_timezone: Optional user timezone
        timeout_sec: Seconds to wait before auto-flush
    """
    buf = _buffers.setdefault(chat_id, _Buf())

    flush_now = False
    async with buf.lock:
        buf.messages.append(msg)
        if user_timezone is not None:
            buf.timezone = user_timezone
        log.info("[BUF %s] queued: %r (len=%d)", chat_id, msg, len(buf.messages))

        # Cancel previous timer if exists
        if buf.timer and not buf.timer.done():
            log.info("[BUF %s] cancel previous timer", chat_id)
            buf.timer.cancel()
            buf.timer = None

        # Check if we should flush immediately
        if _ends_thought(msg):
            flush_now = True
        else:
            log.info("[BUF %s] schedule flush in %.2fs", chat_id, timeout_sec)

            async def _wait_and_flush():
                try:
                    await asyncio.sleep(timeout_sec)
                    await flush_buffer(chat_id, ws, influencer_id, user_id, db, config)
                except asyncio.CancelledError:
                    raise  # Re-raise as required by asyncio best practices
                except Exception:
                    log.exception("[BUF %s] scheduled-flush failed", chat_id)

            buf.timer = asyncio.create_task(_wait_and_flush())

    if flush_now:
        log.info("[BUF %s] ends_thought=True -> flush now", chat_id)
        try:
            await flush_buffer(chat_id, ws, influencer_id, user_id, db, config)
        except Exception:
            log.exception("[BUF %s] flush-now failed", chat_id)


async def flush_buffer(
    chat_id: str,
    ws: WebSocket,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
    config: ChatConfig,
) -> None:
    """
    Flush buffered messages and process them through the AI.
    
    This function:
    1. Combines all buffered messages
    2. Charges the user
    3. Calls the AI turn handler
    4. Saves the AI response
    5. Sends the response via WebSocket
    
    Args:
        chat_id: Chat identifier
        ws: WebSocket connection
        influencer_id: Influencer identifier
        user_id: User identifier
        db: Database session
        config: Chat configuration (regular or 18+)
    """
    buf = _buffers.get(chat_id)
    if not buf:
        return

    # Extract messages from buffer
    async with buf.lock:
        if not buf.messages:
            return
        user_text = " ".join(m.strip() for m in buf.messages if m and m.strip())
        user_timezone = buf.timezone
        buf.messages.clear()
        buf.timer = None

    if not user_text:
        return

    log.info("[BUF %s] FLUSH start; user_text=%r", chat_id, user_text)

    # Charge for the message
    try:
        await charge_feature(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            feature=config.text_feature,
            units=1,
            is_18=config.is_18plus,
            meta={"chat_id": chat_id},
        )
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        log.exception("[BUF %s] Billing error", chat_id)
        await ws.send_json({"error": "⚠️ Billing error. Please try again."})
        return

    # Call AI turn handler
    try:
        log.info("[BUF %s] calling turn handler", chat_id)
        
        # Build kwargs for turn handler
        handler_kwargs: Dict[str, Any] = {
            "message": user_text,
            "chat_id": chat_id,
            "influencer_id": influencer_id,
            "user_id": user_id,
            "db": db,
            "is_audio": False,
        }
        
        # Add timezone for 18+ chats
        if config.is_18plus and user_timezone:
            handler_kwargs["user_timezone"] = user_timezone
        
        reply = await config.turn_handler(**handler_kwargs)
        log.info("[BUF %s] turn handler ok (reply_len=%d)", chat_id, len(reply or ""))
    except Exception:
        log.exception("[BUF %s] turn handler error", chat_id)
        try:
            await ws.send_json({"error": "Sorry, something went wrong. 😔"})
        except Exception:
            pass
        return

    # Save AI message
    try:
        db.add(config.message_model(chat_id=chat_id, sender="ai", content=reply))
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        log.exception("[BUF %s] Failed to save AI message", chat_id)

    # Build response payload
    response_payload = {"reply": reply}

    # Add relationship data for regular chats
    if config.include_relationship:
        try:
            rel_payload = await get_relationship_payload(db, user_id, influencer_id)
            response_payload["relationship"] = rel_payload
        except Exception:
            log.exception("[BUF %s] Failed to load relationship snapshot", chat_id)

    # Add usage data
    try:
        usage_payload = await _get_usage_snapshot_simple(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            is_18=config.is_18plus,
        )
        response_payload["usage"] = usage_payload
    except Exception:
        log.exception("[BUF %s] Failed to load usage snapshot", chat_id)

    # Send response via WebSocket
    try:
        await ws.send_json(response_payload)
        log.info("[BUF %s] ws.send_json done", chat_id)
    except Exception:
        log.exception("[BUF %s] Failed to send reply", chat_id)


async def save_user_message(
    db: AsyncSession,
    chat_id: str,
    text: str,
    message_model: type,
) -> None:
    """
    Save user message to database with embedding.
    
    Args:
        db: Database session
        chat_id: Chat identifier
        text: Message text
        message_model: Message or Message18 class
    """
    try:
        emb = await get_embedding(text)
        db.add(message_model(chat_id=chat_id, sender="user", content=text, embedding=emb))
        await db.commit()
    except Exception:
        await db.rollback()
        log.exception("[WS %s] Failed to save user message", chat_id)
        raise
