import os
import io
import wave
import openai
import tempfile
import httpx
import logging

from fastapi import HTTPException
from app.agents.turn_handler import handle_turn
from app.core.config import settings
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BLAND_API_KEY = settings.BLAND_API_KEY
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
    logger.info(f"Transcription successful: {transcript.text[:50]}...")
    return {"text": transcript.text}

async def get_ai_reply_via_websocket(
    chat_id: str,
    message: str,
    influencer_id: str,
    user_id: int,
    db: AsyncSession,
) -> str:
    """
    Get AI reply using handle_turn function.
    This function should be called with a validated user_id from the token.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID is required")
    
    reply = await handle_turn(
        message,
        chat_id=chat_id,
        influencer_id=influencer_id,
        user_id=user_id,
        db=db,
        is_audio=True
    )
    return reply

async def synthesize_audio_with_elevenlabs(text: str, db, influencer_id: str = None):
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    if not influencer.voice_id:
        raise HTTPException(500, f"Voice ID not set for influencer '{influencer_id}'")

    voice_id = influencer.voice_id
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    data = {
        "text": text,  # aqui envie o output do LLM (já com audio tags / SSML)
        "model_id": "eleven_multilingual_v2",  # ou "eleven_v3"
        "voice_settings": {
            "stability": 0.35,
            "similarity_boost": 0.8,
            "style": 0.5,
            "use_speaker_boost": True
        },
        "output_format": "mp3_44100_128"
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, json=data)
        if resp.status_code != 200:
            logger.error(f"ElevenLabs error: {resp.status_code} - {resp.text}")
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
        
        if resp.status_code != 200:
            logger.error(f"Bland AI error: {resp.status_code} - {resp.text}")
            return None, None
        
        if "application/json" in content_type:
            result = resp.json()
            logger.error(f"Bland AI returned JSON instead of audio: {result}")
            return None, None 
        
        logger.info(f"Bland AI synthesis successful: {resp.status_code}, content-type: {content_type}")
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