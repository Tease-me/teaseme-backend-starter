import os
import io
import wave

from fastapi import  Depends, File, UploadFile, HTTPException

from app.agents.turn_handler import handle_turn
from app.db.session import get_db
from app.core.config import settings

import openai
import tempfile

import httpx

BLAND_API_KEY =settings.BLAND_API_KEY
BLAND_VOICE_ID = settings.BLAND_VOICE_ID
ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID = settings.ELEVENLABS_VOICE_ID

async def transcribe_audio(file_or_bytesio, filename=None, content_type=None):
    if hasattr(file_or_bytesio, "read") and hasattr(file_or_bytesio, "filename"):
        content = await file_or_bytesio.read()
        filename = file_or_bytesio.filename
        content_type = file_or_bytesio.content_type
    else:
        file_or_bytesio.seek(0)
        content = file_or_bytesio.read()
        if filename is None:
            filename = "audio.webm"
    
    suffix = os.path.splitext(filename)[1].lower()
    if not suffix and content_type in ("audio/webm", "audio/wav", "audio/mp3"):
        suffix = {
            "audio/webm": ".webm",
            "audio/wav": ".wav",
            "audio/mp3": ".mp3"
        }[content_type]
    if suffix not in [".webm", ".wav", ".mp3"]:
        raise HTTPException(status_code=415, detail="Format not supported. Use .webm, .wav or .mp3")
    if len(content) < 512:
        raise HTTPException(status_code=422, detail="Audio File empty.")
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
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
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
            return None, None 
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