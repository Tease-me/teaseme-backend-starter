import os
import io
import wave
import openai
import tempfile
import httpx
import logging
import re

from fastapi import HTTPException
from app.agents.turn_handler import handle_turn
from app.core.config import settings
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID = settings.ELEVENLABS_VOICE_ID or None

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
        "text": text, 
        "model_id": "eleven_multilingual_v2", 
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

# ElevenLabs V3 style tags mapping
# Based on: https://elevenlabs.io/docs/best-practices/prompting/eleven-v3
STYLE_TAGS = {
    "neutral": "",
    "warm": "[warm]",
    "playful": "[playful]",
    "flirty": "[flirty][soft]",
    "angry": "[angry]",
    "softly": "[softly]",
    "happily": "[happy]",
    "sad": "[sad]",
    "whispers": "[whispers]",
    "excited": "[excited]",
    "sarcastic": "[sarcastic]",
    "curious": "[curious]",
    "thoughtful": "[thoughtful]",
    "surprised": "[surprised]",
    "annoyed": "[annoyed]",
    "professional": "[professional]",
    "sympathetic": "[sympathetic]",
    "reassuring": "[reassuring]",
}


def format_for_eleven_v3(message: str, style: str = "neutral") -> str:
    if not message:
        return ""
    
    text = message.strip()
    text = re.sub(r'[*_`>#]', '', text)
    text = re.sub(r'\s+', ' ', text)
    
    if not re.search(r'[.!?…]$', text):
        text += "."
    
    tags = STYLE_TAGS.get(style, "")
    if tags:
        text = f"{tags} {text}"
    
    MAX_LENGTH = 2990  # a bit of buffer
    if len(text) > MAX_LENGTH:
        text = text[:MAX_LENGTH - 3] + "..."
    
    return text


def _enhance_text_with_v3_tags(text: str) -> str:
    """
    Enhance plain text with ElevenLabs V3 expression tags for more natural speech.
    Adds tags based on text patterns and emotional cues.
    Based on: https://elevenlabs.io/docs/best-practices/prompting/eleven-v3
    """
    v3_tag_pattern = r'\[(slowly|quickly|whispers|shouts|softly|sad|angry|happy|happily|excited|sorrowful|laughs|laughing|chuckles|sighs|exhales|coughs|gulps|giggles|gasp|sarcastic|curious|crying|snorts|mischievously|thoughtful|surprised|annoyed|professional|sympathetic|reassuring|warm|playful|flirty)\]'
    has_tags = bool(re.search(v3_tag_pattern, text, re.IGNORECASE))
    
    if has_tags:
        logger.debug("Text already contains V3 expression tags, skipping enhancement")
        return text
    
    if len(text.strip()) < 10:
        return text
    
    enhanced = text
    
    gentle_patterns = [
        (r'\b(miss you|missed you|thinking of you|love you|right here|here for you)\b', '[softly]'),
        (r'\b(secret|whisper|quiet|hush)\b', '[whispers]'),
    ]
    
    happy_patterns = [
        (r'\b(great|awesome|wonderful|amazing|excited|happy|glad|yes|yeah|sure)\b', '[happy]'),
        (r'\b(ha|heh|haha|hehe|lol)\b', '[chuckles]'),
        (r'[!]{2,}', '[excited]'),  # Multiple exclamation marks
        (r'^\s*(yes|yeah|sure|of course|absolutely)\b', '[happy]'),  # Positive responses at start
    ]
    
    contemplative_patterns = [
        (r'\b(well|hmm|um|ah|oh)\b', '[sighs]'),
        (r'\.\.\.', '[thoughtful]'),  # Ellipses suggest thoughtful pause
    ]
    
    slow_patterns = [
        (r'\b(remember|back then|once|used to|long ago|think|wonder|consider)\b', '[thoughtful]'),
    ]
    
    surprised_patterns = [
        (r'\b(what|wow|really|seriously|no way|unbelievable)\b', '[surprised]'),
    ]
    
    for pattern, tag in gentle_patterns:
        if re.search(pattern, enhanced, re.IGNORECASE):
            if not enhanced.strip().startswith('['):
                enhanced = f"{tag} {enhanced}"
                break
    
    for pattern, tag in happy_patterns:
        if re.search(pattern, enhanced, re.IGNORECASE):
            if tag not in enhanced:
                match = re.search(pattern, enhanced, re.IGNORECASE)
                if match:
                    pos = match.start()
                    if not enhanced[:pos].strip().startswith('['):
                        enhanced = enhanced[:pos] + f"{tag} " + enhanced[pos:]
                        break
    
    for pattern, tag in slow_patterns:
        if re.search(pattern, enhanced, re.IGNORECASE) and tag not in enhanced:
            match = re.search(pattern, enhanced, re.IGNORECASE)
            if match:
                pos = match.start()
                if not enhanced[:pos].strip().startswith('['):
                    enhanced = enhanced[:pos] + f"{tag} " + enhanced[pos:]
                    break
    
    if enhanced != text:
        logger.debug(f"Enhanced text with V3 tags: '{text}' -> '{enhanced}'")
    
    return enhanced


def _ensure_v3_compatibility(text: str, style: str = "neutral") -> str:
    formatted_text = format_for_eleven_v3(text, style=style)
    
    if style == "neutral" or not STYLE_TAGS.get(style):
        enhanced_text = _enhance_text_with_v3_tags(formatted_text)
    else:
        enhanced_text = formatted_text
    
    v3_tag_pattern = r'\[(slowly|quickly|whispers|shouts|softly|sad|angry|happy|happily|excited|sorrowful|laughs|laughing|chuckles|sighs|exhales|coughs|gulps|giggles|gasp|sarcastic|curious|crying|snorts|mischievously|thoughtful|surprised|annoyed|professional|sympathetic|reassuring|warm|playful|flirty)\]'
    has_tags = bool(re.search(v3_tag_pattern, enhanced_text, re.IGNORECASE))
    
    if has_tags:
        logger.debug("Text contains V3 expression tags")
    else:
        logger.debug("Text is plain (V3 compatible but no expression tags added)")
    
    return enhanced_text


async def synthesize_audio_with_elevenlabs_V3(text: str, db, influencer_id: str = None, style: str = "neutral"):
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    if not influencer.voice_id:
        raise HTTPException(500, f"Voice ID not set for influencer '{influencer_id}'")

    # Ensure V3 compatibility - format with style tags and cleanup
    text = _ensure_v3_compatibility(text, style=style)

    voice_id = influencer.voice_id
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    
    # V3-compatible voice settings
    # stability: Must be 0.0, 0.5, or 1.0 (0.0=Creative, 0.5=Natural, 1.0=Robust)
    # similarity_boost: 0.0 to 1.0 (how similar to original voice)
    # style: 0.0 to 1.0 (how much style variation)
    # use_speaker_boost: Boolean (enhances similarity to original voice)
    data = {
        "text": text,  # Expression tags like [slowly], [chuckles], [whispers] are supported natively by V3
        "model_id": "eleven_v3",  # Using ElevenLabs V3 model
        "voice_settings": {
            "stability": 0.5,  # V3 requires: 0.0 (Creative), 0.5 (Natural), or 1.0 (Robust)
            "similarity_boost": 0.8,  # 0.0-1.0: How similar to original voice
            "style": 0.5,  # 0.0-1.0: Style variation amount
            "use_speaker_boost": True  # Enhances similarity to original voice
        },
        "output_format": "mp3_44100_128"
    }
    
    logger.info(f"[ELEVENLABS V3] Synthesizing audio with V3 model")
    logger.info(f"[ELEVENLABS V3] Text (length: {len(text)}): {text}")
    logger.info(f"[ELEVENLABS V3] Voice ID: {voice_id}, Influencer ID: {influencer_id}")
    logger.debug(f"[ELEVENLABS V3] Voice settings: stability={data['voice_settings']['stability']}, similarity_boost={data['voice_settings']['similarity_boost']}, style={data['voice_settings']['style']}")
    
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, json=data)
        if resp.status_code != 200:
            logger.error(f"ElevenLabs error: {resp.status_code} - {resp.text}")
            return None, None
        return resp.content, "audio/mpeg"

def pcm_bytes_to_wav_bytes(pcm_bytes, sample_rate=44100):
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    wav_io.seek(0)
    return wav_io.read()