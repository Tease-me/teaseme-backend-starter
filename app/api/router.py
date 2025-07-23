import os
import io
import wave

from fastapi import APIRouter, WebSocket, Depends, File, UploadFile, HTTPException, Form
from app.agents.engine import handle_turn
from app.db.session import get_db
from app.db.models import Message, User
from jose import jwt
from app.api.utils import get_embedding
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from pydantic import BaseModel
from typing import List

from app.db.models import Chat
from datetime import datetime

import openai
import tempfile



#TODO: Bad code
import httpx
load_dotenv()


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
BLAND_API_KEY =os.getenv("BLAND_API_KEY")
BLAND_VOICE_ID = os.getenv("BLAND_VOICE_ID")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")


router = APIRouter()

async def create_chat(db, user_id, persona_id, chat_id=None):
    if not chat_id:
        # Use UUID para chats múltiplos, ou f"{user_id}_{persona_id}" se só 1 por persona
        import uuid
        chat_id = str(uuid.uuid4())
    new_chat = Chat(
        id=chat_id,
        user_id=user_id,
        persona_id=persona_id,
        started_at=datetime.utcnow(),
    )
    db.add(new_chat)
    await db.commit()
    return chat_id

@router.post("/chat/")
async def start_chat(user_id: int, persona_id: str, db: AsyncSession = Depends(get_db)):
    chat_id = await create_chat(db, user_id, persona_id)
    return {"chat_id": chat_id}

@router.websocket("/ws/chat/{persona_id}")
async def websocket_chat(ws: WebSocket, persona_id: str, db=Depends(get_db)):
    await ws.accept()
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected from chat/persona={persona_id}")
    except Exception as e:
        await ws.close(code=4002)
        print("JWT decode error:", e)
        return

    while True:
        try:
            raw = await ws.receive_json()
            chat_id = raw.get("chat_id")
            if not chat_id:
                chat_id = f"{user_id}_{persona_id}"
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
                persona_id=persona_id,
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
            print(f"[WS] Client {user_id} disconnected from {persona_id}")
            break
        except Exception as e:
            print(f"[WS] Unexpected error: {e}")
            await ws.close(code=4003)
            break

async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1].lower()
    # Fallback: try to infer from content_type if missing
    if not suffix and file.content_type in ("audio/webm", "audio/wav", "audio/mp3"):
        suffix = {
            "audio/webm": ".webm",
            "audio/wav": ".wav",
            "audio/mp3": ".mp3"
        }[file.content_type]
    if suffix not in [".webm", ".wav", ".mp3"]:  # Add more as needed
        raise HTTPException(status_code=415, detail="Formato não suportado.")
    content = await file.read()
    if len(content) < 512:  # Change threshold as needed
        raise HTTPException(status_code=422, detail="Arquivo de áudio vazio ou muito pequeno.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    with open(tmp_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(
            file=f,
            model="whisper-1"
        )
    os.remove(tmp_path)
    print("Transcription:", transcript.text)
    return {"text": transcript.text}

async def get_ai_reply_via_websocket(chat_id: str,message: str, persona_id: str, token: str, db: Depends(get_db) ): # type: ignore
    # Use websockets.client to connect to your /ws/chat/{persona_id} endpoint
    # Or, refactor your logic to call the same handle_turn() function directly!
    # For demo, let's assume you can just call handle_turn():
    reply = await handle_turn(message, chat_id=chat_id, persona_id=persona_id, user_id=1, db=db,is_audio=True)  # mock user/db
    return reply

async def synthesize_audio_with_elevenlabs(text: str):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",  # For MP3 output
        "Content-Type": "application/json",
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",  # or another model if you want
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=data)
        if resp.status_code != 200:
            print("ElevenLabs error:", resp.text)
            return None, None
        return resp.content, "audio/mpeg"
    
async def synthesize_audio_with_bland_ai(text: str):
    url = "https://api.bland.ai/v1/speak"
    headers = {
        "Authorization": BLAND_API_KEY,
        "Content-Type": "application/json",
    }
    data = {
        "voice": BLAND_VOICE_ID,
        "text": text,
    }
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=data)
        content_type = resp.headers.get("content-type", "")
        print("Bland AI status:", resp.status_code)
        print("Content-Type:", content_type)
        if resp.status_code != 200:
            print("Bland AI error:", resp.text)
            return None, None
        if "application/json" in content_type:
            result = resp.json()
            print("Bland AI JSON response:", result)
            return None, None  # You can adjust this for your needs
        # If not JSON, it's audio
        return resp.content, content_type

def pcm_bytes_to_wav_bytes(pcm_bytes, sample_rate=44100):
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    wav_io.seek(0)
    return wav_io.read()

@router.post("/chat_audio/")
async def chat_audio(
    file: UploadFile = File(...),
    chat_id: str = Form(...),
    persona_id: str = Form("default"),
    token: str = Form(""),    
    db=Depends(get_db)
):
    # 1. Transcribe audio
    transcript = await transcribe_audio(file)
    if not transcript or "error" in transcript:
        raise HTTPException(status_code=422, detail=transcript.get("error", "Transcription error"))

    # 2. Get AI reply (via websocket or direct)
    ai_reply = await get_ai_reply_via_websocket(chat_id,transcript["text"], persona_id, token, db)

    # 3. Synthesize reply as audio (try ElevenLabs first, then Bland as fallback)
    audio_bytes, audio_mime = await synthesize_audio_with_elevenlabs(ai_reply)
    if not audio_bytes:
        audio_bytes, audio_mime = await synthesize_audio_with_bland_ai(ai_reply)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="No audio returned from any TTS provider.")

    return StreamingResponse(io.BytesIO(audio_bytes), media_type=audio_mime)



@router.post("/nudge")
async def send_nudge(
    user_id: int = Form(...),
    persona_id: str = Form("loli"),
    message: str = Form("Hey sumido! Senti sua falta... 😘"),
    db: AsyncSession = Depends(get_db),
):
    chat_id = f"nudge_{user_id}_{persona_id}"

    # 1. Garante que o chat existe
    chat = await db.get(Chat, chat_id)
    if not chat:
        db.add(Chat(id=chat_id, user_id=user_id, persona_id=persona_id, started_at=datetime.utcnow()))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()

    # 2. Gera a resposta da AI
    ai_reply = await handle_turn(
        message,
        chat_id=chat_id,
        persona_id=persona_id,
        user_id=user_id,
        db=db,
    )
    # 3. Salva a mensagem na tabela messages (agora só com chat_id)
    db.add(Message(
        chat_id=chat_id,
        sender="ai",
        content=ai_reply,
        created_at=datetime.utcnow()
    ))
    await db.commit()
    return {"user_id": user_id, "persona_id": persona_id, "reply": ai_reply}


class BroadcastRequest(BaseModel):
    user_ids: List[int]
    persona_id: str = "anna"
    message: str = "Olá, novidade da sua namorada virtual 💖"

@router.post("/nudge/broadcast")
async def broadcast_nudge(
    req: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
):
    results = []
    for user_id in req.user_ids:
        chat_id = f"broadcast_{user_id}_{req.persona_id}"

        # Garante que o chat existe
        chat = await db.get(Chat, chat_id)
        if not chat:
            db.add(Chat(id=chat_id, user_id=user_id, persona_id=req.persona_id, started_at=datetime.utcnow()))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()

        ai_reply = await handle_turn(
            req.message,
            chat_id=chat_id,
            persona_id=req.persona_id,
            user_id=user_id,
            db=db,
        )
        db.add(Message(
            chat_id=chat_id,
            sender="ai",
            content=ai_reply,
            created_at=datetime.utcnow()
        ))
        results.append({"user_id": user_id, "reply": ai_reply})
    await db.commit()
    return results