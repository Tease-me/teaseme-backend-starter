
import io

from fastapi import APIRouter, WebSocket, Depends, File, UploadFile, HTTPException, Form, Query
from app.agents.turn_handler import handle_turn
from app.db.session import get_db
from app.db.models import Message
from jose import jwt
from app.api.utils import get_embedding
from starlette.websockets import WebSocketDisconnect

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_service import get_or_create_chat
from app.schemas.chat import ChatCreateRequest,PaginatedMessages
from app.core.config import settings
from app.utils.router import transcribe_audio, synthesize_audio_with_elevenlabs, synthesize_audio_with_bland_ai, get_ai_reply_via_websocket
from app.utils.s3 import save_audio_to_s3, save_ia_audio_to_s3, generate_presigned_url, message_to_schema_with_presigned
from app.services.billing import charge_feature, get_duration_seconds

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

router = APIRouter()

@router.post("/chat/")
async def start_chat(
    data: ChatCreateRequest, 
    db: AsyncSession = Depends(get_db)
):
    chat_id = await get_or_create_chat(db, data.user_id, data.influencer_id)
    return {"chat_id": chat_id}

@router.websocket("/ws/chat/{influencer_id}")
async def websocket_chat(ws: WebSocket, influencer_id: str, db=Depends(get_db)):
    await ws.accept()
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected from chat/persona={influencer_id}")
    except Exception as e:
        await ws.close(code=4002)
        print("JWT decode error:", e)
        return

    while True:
        try:
            raw = await ws.receive_json()
            chat_id = raw.get("chat_id")
            if not chat_id:
                chat_id = f"{user_id}_{influencer_id}"

            await charge_feature(
                db, user_id=user_id, feature="text", units=1,
                meta={"chat_id": chat_id}
            )

            embedding = await get_embedding(raw["message"])
            db.add(Message(
                chat_id=chat_id,
                sender='user',
                content=raw["message"],
                embedding=embedding
            ))
            await db.commit()
            reply = await handle_turn(
                raw["message"],
                chat_id=chat_id,
                influencer_id=influencer_id,
                user_id=user_id,
                db=db
            )
            db.add(Message(
                chat_id=chat_id,
                sender='ai',
                content=reply
            ))
            await db.commit()
            await ws.send_json({"reply": reply})
        
        except WebSocketDisconnect:
            print(f"[WS] Client {user_id} disconnected from {influencer_id}")
            break
        except Exception as e:
            print(f"[WS] Unexpected error: {e}")
            await ws.close(code=4003)
            break

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
    ai_reply = await get_ai_reply_via_websocket(chat_id,transcript["text"], influencer_id, token, db)

    # 5. Synthesize reply as audio (try ElevenLabs first, then Bland as fallback)
    audio_bytes, audio_mime = await synthesize_audio_with_elevenlabs(ai_reply,db,influencer_id)
    if not audio_bytes:
        audio_bytes, audio_mime = await synthesize_audio_with_bland_ai(ai_reply)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="No audio returned from any TTS provider.")
        
    # 6. Salve o áudio da IA
    ai_audio_url = await save_ia_audio_to_s3(audio_bytes, user_id)

    # 7. Salve a mensagem da IA no banco
    msg_ai = Message(
        chat_id=chat_id,
        sender="ai",
        content=ai_reply,
        audio_url=ai_audio_url
    )
    db.add(msg_ai)
    await db.commit()
    
    return {
        "ai_text": ai_reply,
        "ai_audio_url": generate_presigned_url(ai_audio_url),
        "user_audio_url": generate_presigned_url(user_audio_url),
        "transcript": transcript_text
    }
