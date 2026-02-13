from __future__ import annotations

import io
import logging

from fastapi import APIRouter, WebSocket, Depends, File, UploadFile, HTTPException, Form, Query
from app.agents.turn_handler import handle_turn
from app.db.session import get_db
from app.db.models import Message, Chat, User
from jose import jwt

from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.chat_service import get_or_create_chat
from app.schemas.chat import ChatCreateRequest, PaginatedMessages
from app.utils.auth.dependencies import get_current_user

from app.core.config import settings
from app.utils.messaging.chat import transcribe_audio, synthesize_audio_with_elevenlabs_V3, get_ai_reply_via_websocket
from app.utils.storage.s3 import save_audio_to_s3, save_ia_audio_to_s3, generate_presigned_url, message_to_schema_with_presigned
from app.services.billing import charge_feature, get_duration_seconds, can_afford
from app.moderation import moderate_message, handle_violation

# Import shared buffer service
from app.services.chat_buffer_service import (
    ChatConfig,
    queue_message,
    flush_buffer,
    get_message_context,
    save_user_message,
)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

router = APIRouter(prefix="/chat", tags=["chat"])

log = logging.getLogger("chat")

# Configure for regular (non-18+) chats
CHAT_CONFIG = ChatConfig.regular(turn_handler=handle_turn)


@router.post("/")
async def start_chat(
    data: ChatCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    chat_id = await get_or_create_chat(db, current_user.id, data.influencer_id)
    return {"chat_id": chat_id}


@router.websocket("/ws/{influencer_id}")
async def websocket_chat(
    ws: WebSocket,
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
):
    await ws.accept()

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
            
            user_timezone = raw.get("timezone")
            chat_id = raw.get("chat_id") or f"{user_id}_{influencer_id}"

            # Check if user can afford the message
            ok, cost, free_left = await can_afford(
                db,
                user_id=user_id,
                influencer_id=influencer_id,
                feature="text",
                units=1
            )
            if not ok:
                await ws.send_json({
                    "ok": False,
                    "type": "billing_error",
                    "error": "INSUFFICIENT_CREDITS",
                    "message": "You're out of free texts and credits. Please top up to continue.",
                    "needed_cents": cost,
                    "free_left": free_left,
                })
                continue

            # Save user message
            try:
                await save_user_message(db, chat_id, text, Message)
            except Exception:
                log.exception("[WS %s] Failed to save user message", chat_id)

            # Moderation check
            try:
                context = await get_message_context(db, chat_id, Message)
                mod_result = await moderate_message(text, context, db)
                if mod_result.action == "FLAG":
                    await handle_violation(
                        db=db,
                        user_id=user_id,
                        chat_id=chat_id,
                        influencer_id=influencer_id,
                        message=text,
                        context=context,
                        result=mod_result
                    )
                    log.warning("Flagged user=%s category=%s", user_id, mod_result.category)
            except Exception:
                log.exception("Error during moderation check")

            # Queue message for processing
            await queue_message(
                chat_id=chat_id,
                msg=text,
                ws=ws,
                influencer_id=influencer_id,
                user_id=user_id,
                db=db,
                config=CHAT_CONFIG,
                user_timezone=user_timezone,
            )

            # Handle final flush request
            if raw.get("final") is True:
                log.info("[BUF %s] client requested final flush", chat_id)
                await flush_buffer(chat_id, ws, influencer_id, user_id, db, CHAT_CONFIG)

    except WebSocketDisconnect:
        log.info("[WS] Client %s disconnected from %s", user_id, influencer_id)
        try:
            chat_id = f"{user_id}_{influencer_id}"
            await flush_buffer(chat_id, ws, influencer_id, user_id, db, CHAT_CONFIG)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    chat = await db.get(Chat, chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this chat")
    
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

        if not influencer_id:
            chat = await db.get(Chat, chat_id)
            if not chat or not chat.influencer_id:
                raise HTTPException(status_code=400, detail="Missing influencer context")
            influencer_id = chat.influencer_id

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub"))
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Audio file empty")

        seconds = int(get_duration_seconds(file_bytes, file.content_type))

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
                    "message": "You're out of free voice and credits. Please top up to continue.",
                    "needed_cents": cost,
                    "free_left": free_left,
                },
            )

        await charge_feature(
            db,
            user_id=user_id,
            influencer_id=influencer_id,
            feature="voice",
            units=seconds,
            meta={"chat_id": chat_id, "seconds": seconds},
        )

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

        from app.services.embeddings import get_embedding
        embedding = await get_embedding(transcript_text, source="call")
        msg_user = Message(
            chat_id=chat_id,
            sender="user",
            content=transcript_text,
            audio_url=user_audio_key,
            embedding=embedding,
        )
        db.add(msg_user)
        await db.commit()

        ai_reply = await get_ai_reply_via_websocket(
            chat_id,
            transcript_text,
            influencer_id,
            user_id,
            db,
        )
        if not ai_reply:
            raise HTTPException(status_code=500, detail="No AI reply")

        audio_bytes, _ = await synthesize_audio_with_elevenlabs_V3(ai_reply, db, influencer_id)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="No audio returned from any TTS provider")

        ai_audio_key = await save_ia_audio_to_s3(audio_bytes, user_id)

        msg_ai = Message(
            chat_id=chat_id,
            sender="ai",
            content=ai_reply,
            audio_url=ai_audio_key,
        )
        db.add(msg_ai)
        await db.commit()

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
