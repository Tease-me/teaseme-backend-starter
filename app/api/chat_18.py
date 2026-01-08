from __future__ import annotations

import asyncio
import logging
import io
import asyncio

from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, Depends, File, UploadFile, HTTPException, Form, Query
from app.agents.turn_handler_18 import handle_turn_18
from app.db.session import get_db
from app.db.models import Message18, Chat18
from jose import jwt
from app.api.utils import get_embedding
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.chat_service import get_or_create_chat18
from app.schemas.chat import ChatCreateRequest,PaginatedMessages

from app.core.config import settings
from app.utils.chat import transcribe_audio, synthesize_audio_with_elevenlabs_V3, synthesize_audio_with_bland_ai, get_ai_reply_via_websocket
from app.utils.s3 import save_audio_to_s3, save_ia_audio_to_s3, generate_presigned_url, message18_to_schema_with_presigned
from app.services.billing import charge_feature, get_duration_seconds, can_afford
from app.services.influencer_subscriptions import require_active_subscription

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

router = APIRouter(prefix="/chat18", tags=["chat18"])

log = logging.getLogger("chat18")

@router.post("/")
async def start_chat(
    data: ChatCreateRequest, 
    db: AsyncSession = Depends(get_db)
):
    chat_id = await get_or_create_chat18(db, data.user_id, data.influencer_id)
    return {"chat_id": chat_id}

# ---------- Buffer state ----------
class _Buf:
    __slots__ = ("messages", "timer", "lock")
    def __init__(self) -> None:
        self.messages: List[str] = []
        self.timer: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

_buffers: Dict[str, _Buf] = {}  # chat_id -> _Buf

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

async def _wait_and_flush(
    chat_id: str,
    ws: WebSocket,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
    delay: float,
) -> None:
    try:
        await asyncio.sleep(delay)
        await _flush_buffer(chat_id, ws, influencer_id, user_id, db)
    except asyncio.CancelledError:
        # timer canceled due to a newer incoming message
        return

# ---------- Do the flush: concat, charge, call LLM, persist, reply ----------
async def _flush_buffer(
    chat_id: str,
    ws: WebSocket,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
) -> None:
    buf = _buffers.get(chat_id)
    if not buf:
        return

    # Drain messages atomically
    async with buf.lock:
        if not buf.messages:
            return
        user_text = " ".join(m.strip() for m in buf.messages if m and m.strip())
        buf.messages.clear()
        buf.timer = None

    if not user_text:
        return

    log.info("[BUF %s] FLUSH start; user_text=%r", chat_id, user_text)

    # 1) Billing per flush (burst)
    try:
        await charge_feature(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            feature="text_18",
            units=1,
            meta={"chat_id": chat_id},
        )
        # ⚠ If charge_feature() commits internally, don't commit here.
        # If it does NOT commit, you may commit here with a guarded commit.
        # await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        log.exception("[BUF %s] Billing error", chat_id)
        await ws.send_json({"error": "⚠️ Billing error. Please try again."})
        return

    # 2) Get LLM reply
    try:
        log.info("[BUF %s] calling handle_turn()", chat_id)
        reply = await handle_turn_18(
            message=user_text,
            chat_id=chat_id,
            influencer_id=influencer_id,
            user_id=user_id,
            db=db,
            is_audio=False,
        )
        log.info("[BUF %s] handle_turn_18 ok (reply_len=%d)", chat_id, len(reply or ""))
    except Exception:
        log.exception("[BUF %s] handle_turn_18 error", chat_id)
        # try to tell the client but don't crash if socket closed
        try:
            await ws.send_json({"error": "Sorry, something went wrong. 😔"})
        except Exception:
            pass
        return

    # 3) Persist AI reply
    try:
        db.add(Message18(chat_id=chat_id, sender="ai", content=reply))
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        log.exception("[BUF %s] Failed to save AI message", chat_id)

    # 4) Send to client
    try:
        await ws.send_json({"reply": reply})
        log.info("[BUF %s] ws.send_json done", chat_id)
    except Exception:
        log.exception("[BUF %s] Failed to send reply", chat_id)


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
        await require_active_subscription(db, user_id=user_id, influencer_id=influencer_id)
    except Exception as e:
        # You can be more specific here if your function raises custom errors
        await ws.send_json({
            "ok": False,
            "type": "subscription_error",
            "error": "SUBSCRIPTION_REQUIRED",
            "message": "You need an active subscription for this influencer.",
        })
        SUBSCRIPTION_REQUIRED_CLOSE_CODE = 4403
        await ws.close(code=SUBSCRIPTION_REQUIRED_CLOSE_CODE)
        return

    try:
        while True:
            raw = await ws.receive_json()
            text = (raw.get("message") or "").strip()
            if not text:
                continue

            chat_id = await get_or_create_chat18(db, user_id, influencer_id, raw.get("chat_id"))

            # 🔒 PRE-CHECK: deny if user cannot afford a burst (1 unit)
            ok, cost, free_left = await can_afford(db, user_id=user_id,influencer_id=influencer_id, feature="text", units=1)
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
                db.add(Message18(chat_id=chat_id, sender="user", content=text, embedding=emb))
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
        # try a last flush so we don't leave unsent content
        try:
            chat_id = f"{user_id}_{influencer_id}"
            await _flush_buffer(chat_id, ws, influencer_id, user_id, db)
        except Exception:
            pass
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
        select(func.count()).where(Message18.chat_id == chat_id)
    )
    total = total_result.scalar()

    messages_result = await db.execute(
        select(Message18)
        .where(Message18.chat_id == chat_id)
        .order_by(Message18.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = messages_result.scalars().all()
    messages_schema = [
        message18_to_schema_with_presigned(msg)
        for msg in messages
    ]

    return PaginatedMessages(
        total=total,
        page=page,
        page_size=page_size,
        messages=messages_schema
    )

@router.post("/chat_audio")
async def chat_audio(
    file: UploadFile = File(...),
    chat_id: str = Form(...),
    influencer_id: str = Form(""),
    token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    try:
        if not token:
            raise HTTPException(status_code=400, detail="Token missing")

        # ✅ resolve influencer_id from chat if missing
        if not influencer_id:
            chat = await db.get(Chat18, chat_id)
            if not chat or not chat.influencer_id:
                raise HTTPException(status_code=400, detail="Missing influencer context")
            influencer_id = chat.influencer_id

        # ✅ decode token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub"))
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

        # ✅ read audio
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Audio file empty")

        seconds = int(get_duration_seconds(file_bytes, file.content_type))

        # ✅ PRE-CHECK (influencer-based now)
        ok, cost, free_left = await can_afford(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            feature="voice",
            units=seconds,
        )
        if not ok:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "INSUFFICIENT_CREDITS",
                    "message": "You’re out of free voice and credits. Please top up to continue.",
                    "needed_cents": cost,
                    "free_left": free_left,
                },
            )

        # ✅ CHARGE before expensive calls
        await charge_feature(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            feature="voice_18",
            units=seconds,
            meta={"chat_id": chat_id, "seconds": seconds},
        )

        # ✅ upload user audio (expect S3 KEY back)
        user_audio_key = await save_audio_to_s3(
            io.BytesIO(file_bytes),
            file.filename,
            file.content_type,
            user_id,
        )

        transcript = await transcribe_audio(
            io.BytesIO(file_bytes),
            file.filename,
            file.content_type,
        )
        if not transcript or "error" in transcript:
            raise HTTPException(status_code=422, detail=(transcript or {}).get("error", "Transcription error"))

        transcript_text = transcript.get("text") or ""
        if not transcript_text.strip():
            raise HTTPException(status_code=422, detail="Empty transcript")

        # ✅ save user msg
        embedding = await get_embedding(transcript_text)
        msg_user = Message18(
            chat_id=chat_id,
            sender="user",
            content=transcript_text,
            audio_url=user_audio_key,
            embedding=embedding,
        )
        db.add(msg_user)
        await db.commit()

        # ✅ get AI reply
        ai_reply = await get_ai_reply_via_websocket(
            chat_id,
            transcript_text,
            influencer_id,
            user_id,
            db,
        )
        if not ai_reply:
            raise HTTPException(status_code=500, detail="No AI reply")

        # ✅ TTS
        audio_bytes, audio_mime = await synthesize_audio_with_elevenlabs_V3(ai_reply, db, influencer_id)
        if not audio_bytes:
            audio_bytes, audio_mime = await synthesize_audio_with_bland_ai(ai_reply)
            if not audio_bytes:
                raise HTTPException(status_code=500, detail="No audio returned from any TTS provider")

        # ✅ upload AI audio (expect S3 KEY back)
        ai_audio_key = await save_ia_audio_to_s3(audio_bytes, user_id)

        # ✅ save AI msg
        msg_ai = Message18(
            chat_id=chat_id,
            sender="ai",
            content=ai_reply,
            audio_url=ai_audio_key,  # store KEY
        )
        db.add(msg_ai)
        await db.commit()

        # ✅ return presigned URLs (ONLY if keys)
        return {
            "ai_text": ai_reply,
            "ai_audio_url": generate_presigned_url(ai_audio_key),
            "user_audio_url": generate_presigned_url(user_audio_key),
            "transcript": transcript_text,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log.error("chat_audio 500: %r\n%s", e, err)
        raise HTTPException(
            status_code=500,
            detail={
                "error": repr(e),
                "trace": err.splitlines()[-30:],
            },
        )