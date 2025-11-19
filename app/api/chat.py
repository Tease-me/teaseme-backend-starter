from __future__ import annotations

import asyncio
import logging
import io
import random
import re

from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, Depends, File, UploadFile, HTTPException, Form, Query
from app.agents.turn_handler import handle_turn
from app.db.session import get_db, SessionLocal
from app.db.models import Message
from jose import jwt
from app.api.utils import get_embedding
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, func, insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.chat_service import get_or_create_chat
from app.schemas.chat import ChatCreateRequest,PaginatedMessages
from app.core.config import settings
from app.utils.chat import transcribe_audio, synthesize_audio_with_elevenlabs_V3, synthesize_audio_with_bland_ai, get_ai_reply_via_websocket
from app.utils.s3 import save_audio_to_s3, save_ia_audio_to_s3, generate_presigned_url, message_to_schema_with_presigned
from app.services.billing import charge_feature, get_duration_seconds, can_afford

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

router = APIRouter(prefix="/chat", tags=["chat"])

log = logging.getLogger("chat")

@router.post("")
async def start_chat(
    data: ChatCreateRequest, 
    db: AsyncSession = Depends(get_db)
):
    chat_id = await get_or_create_chat(db, data.user_id, data.influencer_id)
    return {"chat_id": chat_id}

# ---------- Buffer state ----------
class _Buf:
    __slots__ = ("messages", "timer", "lock")
    def __init__(self) -> None:
        self.messages: List[str] = []
        self.timer: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

_buffers: Dict[str, _Buf] = {}  # chat_id -> _Buf
MAX_BUFFERS = 1000  # Maximum number of active buffers to prevent memory issues

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_DOUBLE_TEXT_MIN_SENTENCES = 3
_DOUBLE_TEXT_MIN_LENGTH = 220
_DOUBLE_TEXT_MIN_SEGMENT_LEN = 25
_DOUBLE_TEXT_DELAY_RANGE = (0.55, 1.1)


def _split_into_double_text_chunks(text: str) -> List[str]:
    """
    Break a single assistant reply into at most two conversational bubbles.
    Long or multi-sentence replies sound more natural when delivered as staggered texts.
    """
    if not text:
        return [text]
    stripped = text.strip()
    if not stripped:
        return [text]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(stripped) if s.strip()]
    if len(sentences) >= _DOUBLE_TEXT_MIN_SENTENCES:
        boundary = min(2, len(sentences) - 1)
        first = " ".join(sentences[:boundary]).strip()
        second = " ".join(sentences[boundary:]).strip()
        if len(first) >= _DOUBLE_TEXT_MIN_SEGMENT_LEN and len(second) >= _DOUBLE_TEXT_MIN_SEGMENT_LEN:
            return [first, second]

    if len(stripped) >= _DOUBLE_TEXT_MIN_LENGTH:
        midpoint = len(stripped) // 2
        candidates: List[int] = []
        right_space = stripped.find(" ", midpoint)
        if right_space != -1:
            candidates.append(right_space)
        left_space = stripped.rfind(" ", 0, midpoint)
        if left_space != -1:
            candidates.append(left_space)
        for pos in candidates:
            if _DOUBLE_TEXT_MIN_SEGMENT_LEN <= pos <= len(stripped) - _DOUBLE_TEXT_MIN_SEGMENT_LEN:
                first = stripped[:pos].strip()
                second = stripped[pos:].strip()
                if len(first) >= _DOUBLE_TEXT_MIN_SEGMENT_LEN and len(second) >= _DOUBLE_TEXT_MIN_SEGMENT_LEN:
                    return [first, second]

    return [stripped]


async def _save_ai_messages(db_ai: AsyncSession, chat_id: str, chunks: List[str]) -> None:
    payloads = [
        {"chat_id": chat_id, "sender": "ai", "content": chunk.strip()}
        for chunk in chunks
        if chunk and chunk.strip()
    ]
    if not payloads:
        return
    await db_ai.execute(insert(Message), payloads)
    await db_ai.commit()


async def _send_reply_chunks(ws: WebSocket, chat_id: str, chunks: List[str]) -> None:
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        if not chunk:
            continue
        payload = {"reply": chunk}
        if total > 1:
            payload["part"] = idx
            payload["parts"] = total
        await ws.send_json(payload)
        log.info("[BUF %s] sent chunk %d/%d (len=%d)", chat_id, idx, total, len(chunk))
        if idx < total:
            await asyncio.sleep(random.uniform(*_DOUBLE_TEXT_DELAY_RANGE))

# ---------- Heuristic: did the message end a thought? ----------
def _ends_thought(msg: str) -> bool:
    if not msg:
        return False
    msg = msg.strip()
    strong = (".", "!", "?", "…")
    end_emojis = ("👍", "😉", "😂", "😅", "🤣", "😍", "😘")
    return msg.endswith(strong) or msg.endswith(end_emojis)

# ---------- Queue message and schedule flush ----------
async def _queue_message(
    chat_id: str,
    msg: str,
    ws: WebSocket,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
    timeout_sec: float = 2.5,
) -> None:
    # Prevent memory issues by limiting buffer count
    if len(_buffers) >= MAX_BUFFERS and chat_id not in _buffers:
        # Remove oldest buffer (simple FIFO)
        oldest_key = next(iter(_buffers))
        old_buf = _buffers[oldest_key]
        if old_buf.timer and not old_buf.timer.done():
            old_buf.timer.cancel()
        del _buffers[oldest_key]
        log.warning("[BUF] Removed oldest buffer %s (limit reached)", oldest_key)
    
    buf = _buffers.setdefault(chat_id, _Buf())

    # ---- mutate buffer under lock
    flush_now = False
    async with buf.lock:
        buf.messages.append(msg)
        log.info("[BUF %s] queued: %r (len=%d)", chat_id, msg, len(buf.messages))

        # cancel previous timer if any
        if buf.timer and not buf.timer.done():
            log.info("[BUF %s] cancel previous timer", chat_id)
            buf.timer.cancel()
            buf.timer = None

        # decide behavior
        if _ends_thought(msg):
            flush_now = True
        else:
            log.info("[BUF %s] schedule flush in %.2fs", chat_id, timeout_sec)

            async def _wait_and_flush():
                try:
                    await asyncio.sleep(timeout_sec)
                    await _flush_buffer(chat_id, ws, influencer_id, user_id, db)
                except asyncio.CancelledError:
                    return
                except Exception:
                    log.exception("[BUF %s] scheduled-flush failed", chat_id)

            buf.timer = asyncio.create_task(_wait_and_flush())

    # ---- outside the lock: perform the flush now if needed
    if flush_now:
        log.info("[BUF %s] ends_thought=True -> flush now", chat_id)
        try:
            await _flush_buffer(chat_id, ws, influencer_id, user_id, db)
        except Exception:
            log.exception("[BUF %s] flush-now failed", chat_id)

# ---------- Do the flush: concat, charge, call LLM, persist, reply ----------
async def _flush_buffer_without_ws(chat_id: str, influencer_id: str, user_id: int) -> None:
    """
    Flush buffer without WebSocket (for disconnect cleanup).
    Saves AI reply to DB even if client disconnected.
    """
    buf = _buffers.get(chat_id)
    if not buf:
        return

    async with buf.lock:
        if not buf.messages:
            return
        user_text = " ".join(m.strip() for m in buf.messages if m and m.strip())
        buf.messages.clear()
        buf.timer = None

    if not user_text:
        return

    log.info("[BUF %s] FLUSH (no-WS) start; user_text=%r", chat_id, user_text)

    # 1) Billing – fresh session
    async with SessionLocal() as db_bill:
        try:
            # charge_feature commits internally, no need to commit again
            await charge_feature(
                db_bill, user_id=user_id, feature="text", units=1,
                meta={"chat_id": chat_id, "burst": True},
            )
        except Exception as e:
            await db_bill.rollback()
            log.exception("[WS %s] Billing error (no-WS flush): %s", chat_id, e, exc_info=True)
            return  # Don't process if billing fails

    # 2) Get LLM reply
    reply = None
    try:
        log.info("[BUF %s] calling handle_turn() (no-WS)", chat_id)
        async with SessionLocal() as db_ht:
            reply = await handle_turn(
                message=user_text,
                chat_id=chat_id,
                influencer_id=influencer_id,
                user_id=user_id,
                db=db_ht,
                is_audio=False,
            )
        
        if not reply:
            log.warning("[BUF %s] handle_turn returned empty reply (no-WS)", chat_id)
            return
    except Exception:
        log.exception("[BUF %s] handle_turn error (no-WS)", chat_id)
        return

    chunks = _split_into_double_text_chunks(reply)

    # 3) Persist AI reply to DB (client will get it on reconnect via chat history)
    async with SessionLocal() as db_ai:
        try:
            await _save_ai_messages(db_ai, chat_id, chunks)
            log.info(
                "[BUF %s] Saved %d AI chunk(s) to DB (no-WS)",
                chat_id,
                len(chunks),
            )
        except Exception:
            await db_ai.rollback()
            log.exception("[WS %s] Failed to save AI message (no-WS)", chat_id)

async def _flush_buffer(chat_id: str, ws: WebSocket, influencer_id: str, user_id: int, db: AsyncSession) -> None:
    buf = _buffers.get(chat_id)
    if not buf:
        return

    async with buf.lock:
        if not buf.messages:
            return
        user_text = " ".join(m.strip() for m in buf.messages if m and m.strip())
        buf.messages.clear()
        buf.timer = None

    if not user_text:
        return

    log.info("[BUF %s] FLUSH start; user_text=%r", chat_id, user_text)

    # 1) Billing – fresh session
    async with SessionLocal() as db_bill:
        try:
            # charge_feature commits internally, no need to commit again
            await charge_feature(
                db_bill, user_id=user_id, feature="text", units=1,
                meta={"chat_id": chat_id, "burst": True},
            )
        except HTTPException as e:
            await db_bill.rollback()
            # Handle specific billing errors
            if e.status_code == 402:
                # Insufficient credits - should have been caught earlier, but handle gracefully
                log.warning("[WS %s] Insufficient credits during flush (race condition?)", chat_id)
                try:
                    await ws.send_json({
                        "ok": False,
                        "type": "billing_error",
                        "error": "INSUFFICIENT_CREDITS",
                        "message": "You don't have enough credits. Please top up to continue.",
                        "needed_cents": None,  # Can't determine without re-checking
                        "free_left": None,
                    })
                except Exception:
                    pass
            elif e.status_code == 500:
                # Pricing not configured - system error
                log.error("[WS %s] Pricing not configured: %s", chat_id, e.detail)
                try:
                    await ws.send_json({
                        "ok": False,
                        "type": "billing_error",
                        "error": "SYSTEM_ERROR",
                        "message": "Payment system error. Please contact support.",
                    })
                except Exception:
                    pass
            else:
                # Other HTTP exceptions
                log.error("[WS %s] Billing HTTP error (%d): %s", chat_id, e.status_code, e.detail)
                try:
                    await ws.send_json({
                        "ok": False,
                        "type": "billing_error",
                        "error": "CHARGE_FAILED",
                        "message": "Failed to process payment. Please try again.",
                    })
                except Exception:
                    pass
            return  # ⚠️ Exit early if billing fails
        except Exception as e:
            # Unexpected errors (database issues, etc.)
            await db_bill.rollback()
            # Log full exception details for debugging
            log.exception(
                "[WS %s] Unexpected billing error (type=%s, msg=%s): %s",
                chat_id, type(e).__name__, str(e), e,
                exc_info=True
            )
            
            # Check for specific database errors
            error_msg = "Payment system temporarily unavailable. Please try again."
            error_type = "CHARGE_FAILED"
            
            # Check if it's a database connection/transaction error
            error_str = str(e).lower()
            if "connection" in error_str or "timeout" in error_str:
                error_msg = "Database connection error. Please try again."
                error_type = "DATABASE_ERROR"
            elif "deadlock" in error_str or "lock" in error_str:
                error_msg = "Transaction conflict. Please try again in a moment."
                error_type = "TRANSACTION_ERROR"
            
            try:
                await ws.send_json({
                    "ok": False,
                    "type": "billing_error",
                    "error": error_type,
                    "message": error_msg,
                })
            except Exception:
                pass
            return  # ⚠️ Exit early if billing fails

    # 2) Get LLM reply – fresh session for handle_turn
    reply = None
    try:
        log.info("[BUF %s] calling handle_turn()", chat_id)
        async with SessionLocal() as db_ht:
            reply = await handle_turn(
                message=user_text,
                chat_id=chat_id,
                influencer_id=influencer_id,
                user_id=user_id,
                db=db_ht,
                is_audio=False,
            )
        
        if not reply:
            log.warning("[BUF %s] handle_turn returned empty reply", chat_id)
            reply = "Sorry, something went wrong. 😔"
        
        log.info("[BUF %s] handle_turn ok (reply_len=%d)", chat_id, len(reply or ""))
    except Exception:
        log.exception("[BUF %s] handle_turn error", chat_id)
        try:
            await ws.send_json({"reply": "Sorry, something went wrong. 😔"})
        except Exception:
            pass
        return

    chunks = _split_into_double_text_chunks(reply)

    # 3) Persist AI reply – fresh session
    async with SessionLocal() as db_ai:
        try:
            await _save_ai_messages(db_ai, chat_id, chunks)
        except Exception:
            await db_ai.rollback()
            log.exception("[WS %s] Failed to save AI message", chat_id)

    # 4) Send to client
    try:
        await _send_reply_chunks(ws, chat_id, chunks)
    except Exception:
        log.exception("[WS %s] Failed to send reply", chat_id)


# ---------- WebSocket entrypoint ----------
@router.websocket("/ws/{influencer_id}")
async def websocket_chat(
    ws: WebSocket,
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
):
    await ws.accept()

    # simple token auth: ?token=...
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except WebSocketDisconnect:
        log.info("[WS] Client disconnected before auth (persona=%s)", influencer_id)
        return
    except Exception as e:
        await ws.close(code=4002)
        log.error("[WS] JWT decode error: %s", e)
        return

    try:
        while True:
            raw = await ws.receive_json()
            text = (raw.get("message") or "").strip()
            if not text:
                continue

            chat_id = raw.get("chat_id") or f"{user_id}_{influencer_id}"

            # 🔒 PRE-CHECK: deny if user cannot afford a burst (1 unit)
            ok, cost, free_left = await can_afford(db, user_id=user_id, feature="text", units=1)
            if not ok:
                # send a structured error and DO NOT save/enqueue
                await ws.send_json({
                    "ok": False,
                    "type": "billing_error",
                    "error": "INSUFFICIENT_CREDITS",
                    "message": "You’re out of free texts and credits. Please top up to continue.",
                    "needed_cents": cost,
                    "free_left": free_left,
                })
                # optionally close socket with specific code:
                # await ws.close(code=4402)
                continue

            # save user message (with embedding)
            try:
                emb = await get_embedding(text)
                db.add(Message(chat_id=chat_id, sender="user", content=text, embedding=emb))
                await db.commit()
            except Exception:
                await db.rollback()
                log.exception("[WS %s] Failed to save user message", chat_id)

            # enqueue; buffer decides when to respond
            await _queue_message(chat_id, text, ws, influencer_id, user_id, db)

            # optional: client can force immediate flush by sending {"final": true}
            if raw.get("final") is True:
                log.info("[BUF %s] client requested final flush", chat_id)
                await _flush_buffer(chat_id, ws, influencer_id, user_id, db)

    except WebSocketDisconnect:
        log.info("[WS] Client %s disconnected from %s", user_id, influencer_id)
        # Cleanup buffer on disconnect to prevent memory leaks
        chat_id = f"{user_id}_{influencer_id}"
        if chat_id in _buffers:
            buf = _buffers[chat_id]
            # Cancel any pending timer
            if buf.timer and not buf.timer.done():
                buf.timer.cancel()
            
            # Try a last flush so we don't leave unsent content
            # Note: This will fail to send via WebSocket (already disconnected),
            # but it will still save the AI reply to DB if it succeeds
            if buf.messages:
                try:
                    log.info("[WS] Attempting final flush for disconnected client %s (messages=%d)", chat_id, len(buf.messages))
                    # Create a dummy WebSocket object to avoid errors, but flush will handle send failures gracefully
                    await _flush_buffer_without_ws(chat_id, influencer_id, user_id)
                except Exception as e:
                    log.warning("[WS] Final flush failed for %s: %s", chat_id, e)
            
            # Remove buffer to prevent memory leak
            del _buffers[chat_id]
            log.info("[WS] Cleaned up buffer for %s", chat_id)
    except Exception:
        log.exception("[WS] Unexpected error")
        try:
            await ws.close(code=4003)
        except Exception:
            pass

@router.get("/history/{chat_id}", response_model=PaginatedMessages)
async def get_chat_history(
    chat_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(
        select(func.count()).where(Message.chat_id == chat_id)
    )
    total = total_result.scalar()

    messages_result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = messages_result.scalars().all()
    messages_schema = [
        message_to_schema_with_presigned(msg)
        for msg in messages
    ]

    return PaginatedMessages(
        total=total,
        page=page,
        page_size=page_size,
        messages=messages_schema
    )

@router.post("/chat_audio/")
async def chat_audio(
    file: UploadFile = File(...),
    chat_id: str = Form(...),
    influencer_id: str = Form("default"),
    token: str = Form(""),    
    db=Depends(get_db)
):
    if not token:
        raise HTTPException(status_code=400, detail="Token missing")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Audio File empty.")
    
    seconds = get_duration_seconds(file_bytes, file.content_type)

     # 🔒 PRE-CHECK: deny if cannot afford 'seconds' of voice
    ok, cost, free_left = await can_afford(db, user_id=user_id, feature="voice", units=int(seconds))
    if not ok:
        # 402 Payment Required with structured detail
        raise HTTPException(
            status_code=402,
            detail={
                "error": "INSUFFICIENT_CREDITS",
                "message": "You’re out of free voice and credits. Please top up to continue.",
                "needed_cents": cost,
                "free_left": free_left,
            },
        )
    
    # ◆ charge before heavy calls
    await charge_feature(
        db, user_id=user_id, feature="voice",
        units=int(seconds), meta={"chat_id": chat_id}
    )

    user_audio_url = await save_audio_to_s3(io.BytesIO(file_bytes), file.filename, file.content_type, user_id)

    transcript = await transcribe_audio(io.BytesIO(file_bytes), file.filename, file.content_type)
    if not transcript or "error" in transcript:
        raise HTTPException(status_code=422, detail=transcript.get("error", "Transcription error"))

    transcript_text = transcript["text"]

    # 3. Save user message with embedding
    embedding = await get_embedding(transcript_text)
    msg_user = Message(
        chat_id=chat_id,
            sender="user",
            content=transcript_text,
            audio_url=user_audio_url,
            embedding=embedding
        )
    db.add(msg_user)
    await db.commit()

    # 4. Get AI reply (via websocket or direct)
    ai_reply = await get_ai_reply_via_websocket(chat_id, transcript["text"], influencer_id, user_id, db)

    # 5. Synthesize reply as audio (try ElevenLabs first, then Bland as fallback)
    audio_bytes, audio_mime = await synthesize_audio_with_elevenlabs_V3(ai_reply,db,influencer_id)
    if not audio_bytes:
        # audio_bytes, audio_mime = await synthesize_audio_with_bland_ai(ai_reply)
        # if not audio_bytes:
        raise HTTPException(status_code=500, detail="No audio returned from any TTS provider.")
        
    # 6. Save AI audio to S3
    ai_audio_url = await save_ia_audio_to_s3(audio_bytes, user_id)

    # 7. Save AI message with audio URL
    # Use try/except to handle transaction errors (e.g., from failed memory operations)
    try:
        msg_ai = Message(
            chat_id=chat_id,
            sender="ai",
            content=ai_reply,
            audio_url=ai_audio_url
        )
        db.add(msg_ai)
        await db.commit()
    except Exception as e:
        # Rollback and retry with a fresh transaction
        await db.rollback()
        try:
            msg_ai = Message(
                chat_id=chat_id,
                sender="ai",
                content=ai_reply,
                audio_url=ai_audio_url
            )
            db.add(msg_ai)
            await db.commit()
        except Exception as retry_error:
            await db.rollback()
            log.error(f"Failed to save AI message after retry: {retry_error}", exc_info=True)
            # Continue anyway - the audio was generated and saved to S3
    
    return {
        "ai_text": ai_reply,
        "ai_audio_url": generate_presigned_url(ai_audio_url),
        "user_audio_url": generate_presigned_url(user_audio_url),
        "transcript": transcript_text
    }
