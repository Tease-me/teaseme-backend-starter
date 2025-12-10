import asyncio
import logging
import math
import random
from uuid import uuid4
from app.agents.memory import find_similar_memories
from app.agents.prompt_utils import get_global_audio_prompt
from app.agents.scoring import format_score_value, get_score
import httpx
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from itertools import chain
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.db.models import Influencer, Chat, Message, CallRecord
from app.db.session import get_db
from app.schemas.elevenlabs import FinalizeConversationBody, RegisterConversationBody, UpdatePromptBody
from app.services.billing import charge_feature
from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.services.billing import can_afford, get_remaining_units
from app.services.chat_service import get_or_create_chat
from app.agents.turn_handler import redis_history
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.db.session import SessionLocal
from app.utils.deps import get_current_user
from langchain_core.runnables.history import RunnableWithMessageHistory
from app.api.utils import get_embedding
from app.services.system_prompt_service import get_system_prompt

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])
log = logging.getLogger(__name__)

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_ELEVENLABS_VOICE_ID = settings.ELEVENLABS_VOICE_ID or None

# Temporary in-memory greetings (no DB). Keep the content SFW and generic.
_GREETINGS: Dict[str, List[str]] = {
    "playful": [
        "Hey! Look who it is.",
        "Finally! I was getting bored.",
        "Hey, you. What's the latest?",
        "Yo! Perfect timing.",
    ],
    "anna": [
        "Nyaa~ you're here!",
        "Ooh! Hi hi! ✨",
        "Yay! I was hoping you'd show up.",
    ],
    "bella": [
        "Hey there. I missed you.",
        "Hi... glad you're back.",
        "There you are.",
    ],
}
_rr_index: Dict[str, int] = {}

_DOPAMINE_OPENERS: Dict[str, List[str]] = {
    "anna": [
        "I was *just* thinking about you! Spooky, right?",
        "Ah! You just made my whole day better.",
    ],
    "bella": [
        "Finally. I was waiting for this notification.",
        "Hey... seeing you pop up just made me smile.",
    ],
    "playful": [
        "There's my favorite distraction.",
        "Warning: I'm in a really good mood now that you're here.",
    ],
}

def _headers() -> Dict[str, str]:
    """Return ElevenLabs auth headers. Fail fast when misconfigured."""
    if not ELEVENLABS_API_KEY:
        raise HTTPException(500, "ELEVENLABS_API_KEY is not configured.")
    return {"xi-api-key": ELEVENLABS_API_KEY}


def _pick_greeting(influencer_id: str, mode: str) -> str:
    """Pick a greeting: random or round-robin for that influencer id."""
    options = _GREETINGS.get(influencer_id)
    if not options:
        all_opts = list(chain.from_iterable(_GREETINGS.values()))
        choice = random.choice(all_opts) if all_opts else "Hello!"
        return _add_natural_pause(choice)
    if mode == "rr":
        i = _rr_index.get(influencer_id, -1) + 1
        i %= len(options)
        _rr_index[influencer_id] = i
        return _add_natural_pause(options[i])
    return _add_natural_pause(random.choice(options))


try:
    GREETING_GENERATOR: Optional[ChatOpenAI] = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model="gpt-4.1",
        temperature=0.7,
        max_tokens=120,
    )
except Exception as exc: 
    GREETING_GENERATOR = None
    log.warning("Contextual greeting generator disabled: %s", exc)


DEFAULT_GREETING_SYSTEM_PROMPT = (
    "You are {influencer_name}, an affectionate AI companion speaking English. "
    "Craft the very next thing you would say when a live voice call resumes. "
    "Keep it to one short spoken sentence, 8–14 words. "
    "Reference the recent conversation naturally, acknowledge the user, and sound warm and spontaneous. "
    "You are on a live phone call right now—you’re speaking on the line, "
    "but do not mention the phone or calling explicitly. "
    "Include a natural pause with punctuation (comma or ellipsis) so it feels like a breath, not rushed. "
    "Do not mention calling or reconnecting explicitly, and avoid robotic phrasing or obvious filler like 'uh' or 'um'."
)

async def _get_greeting_prompt(db: AsyncSession) -> ChatPromptTemplate:
    system_prompt = await get_system_prompt(db, "ELEVENLABS_CALL_GREETING")
    if not system_prompt:
        system_prompt = DEFAULT_GREETING_SYSTEM_PROMPT
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "human",
                "Recent conversation between you and the user:\n{transcript}\n\n"
                "Respond with your next spoken greeting. Output only the greeting text."
            ),
        ]
    )


def _format_history(messages: List[Message]) -> str:
    lines: List[str] = []
    for msg in messages:
        speaker = "User" if msg.sender == "user" else "AI"
        content = (msg.content or "").strip().replace("\n", " ")
        if not content:
            continue
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _format_transcript_entries(transcript: List[Dict[str, Any]]) -> str:
    """
    Convert ElevenLabs transcript entries into "User: ..." / "AI: ..." lines.
    """
    lines: List[str] = []
    for entry in transcript:
        text = str(
            entry.get("text") or entry.get("content") or entry.get("message") or ""
        ).strip()
        if not text:
            continue
        role_raw = str(entry.get("sender") or entry.get("role") or "").lower()
        is_user_flag = entry.get("is_user") or entry.get("from_user")
        if role_raw in {"user", "human"} or is_user_flag:
            speaker = "User"
        else:
            speaker = "AI"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)

def _format_redis_history(chat_id: str, influencer_id: str, limit: int = 12) -> Optional[str]:
    try:
        history = redis_history(chat_id, influencer_id)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("redis_history.fetch_failed chat=%s err=%s", chat_id, exc)
        return None
    if not history or not history.messages:
        return None

    lines: List[str] = []
    for msg in history.messages[-limit:]:
        role = getattr(msg, "type", "") or getattr(msg, "role", "")
        speaker = "User" if role in {"human", "user"} else "AI"
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(str(part))
            content = " ".join(parts)
        content = str(content or "").strip()
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else None


def _add_natural_pause(text: Optional[str]) -> Optional[str]:
    """
    Ensure there's a gentle pause via comma or ellipsis to avoid rushed delivery.
    """
    if not text:
        return text
    if any(p in text for p in [",", "...", "…"]):
        return text
    words = text.split()
    if len(words) < 5:
        return text
    mid = max(2, len(words) // 2)
    words.insert(mid, ",")
    return " ".join(words)


async def _generate_contextual_greeting(
    db: AsyncSession, chat_id: str, influencer_id: str
) -> Optional[str]:
    if GREETING_GENERATOR is None:
        return None

    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(8)
    )
    db_messages = list(result.scalars().all())
    transcript: Optional[str] = None

    if not db_messages:
        try:
            redis_ctx = _format_redis_history(chat_id, influencer_id)
            if redis_ctx:
                transcript = redis_ctx
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("contextual_greeting.redis_fallback_failed chat=%s err=%s", chat_id, exc)

    if db_messages:
        db_messages.reverse()
        transcript = _format_history(db_messages)

    # Fallback to the latest call transcript if no stored messages yet.
    if not transcript:
        try:
            chat = await db.get(Chat, chat_id)
            user_id = chat.user_id if chat else None
        except Exception:
            user_id = None

        if user_id:
            try:
                call_res = await db.execute(
                    select(CallRecord)
                    .where(
                        CallRecord.user_id == user_id,
                        CallRecord.influencer_id == influencer_id,
                        CallRecord.transcript.isnot(None),
                    )
                    .order_by(CallRecord.created_at.desc())
                    .limit(1)
                )
                call_row = call_res.scalar_one_or_none()
                if call_row and call_row.transcript:
                    transcript = _format_transcript_entries(call_row.transcript)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "contextual_greeting.call_fallback_failed chat=%s user=%s infl=%s err=%s",
                    chat_id,
                    user_id,
                    influencer_id,
                    exc,
                )

    if not transcript:
        return _pick_dopamine_greeting(influencer_id)

    influencer = await db.get(Influencer, influencer_id)
    persona_name = (
        influencer.display_name if influencer and influencer.display_name else influencer_id
    )

    try:
        prompt = await _get_greeting_prompt(db)
        chain = prompt.partial(influencer_name=persona_name) | GREETING_GENERATOR
        llm_response = await chain.ainvoke({"transcript": transcript})
        greeting = _add_natural_pause((llm_response.content or "").strip())
        if greeting.startswith('"') and greeting.endswith('"'):
            greeting = greeting[1:-1]
        return greeting if greeting else None
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Failed to generate contextual greeting for %s: %s", chat_id, exc)
        return _pick_dopamine_greeting(influencer_id)


def _pick_dopamine_greeting(influencer_id: str) -> Optional[str]:
    options = _DOPAMINE_OPENERS.get(influencer_id) or _DOPAMINE_OPENERS.get("playful")
    if not options:
        return None
    return _add_natural_pause(random.choice(options))


async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str) -> str:
    """
    Looks up the ElevenLabs agent id stored on the Influencer row.
    NOTE: double-check the column name 'influencer_agent_id_third_part' in your model.
    """
    influencer = await db.get(Influencer, influencer_id)
    if influencer and getattr(influencer, "influencer_agent_id_third_part", None):
        return influencer.influencer_agent_id_third_part
    raise HTTPException(404, "Influencer or influencer_agent_id_third_part not found")


def _build_agent_patch_payload(
    *,
    prompt_text: Optional[str] = None,
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    
    agent_cfg: Dict[str, Any] = {}

    if any(v is not None for v in (prompt_text, llm, temperature, max_tokens)):
        prompt_block: Dict[str, Any] = {}
        if prompt_text is not None:
            prompt_block["prompt"] = prompt_text
        if llm is not None:
            prompt_block["llm"] = llm
        if temperature is not None:
            prompt_block["temperature"] = temperature
        if max_tokens is not None:
            prompt_block["max_tokens"] = max_tokens
        agent_cfg["prompt"] = prompt_block

    return {"conversation_config": {"agent": agent_cfg}}


def _build_agent_create_payload(
    *,
    name: Optional[str],
    voice_id: str,
    prompt_text: str,
    language: str = "en",
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    if not voice_id:
        raise HTTPException(400, "voice_id is required to create an ElevenLabs agent.")

    agent_cfg: Dict[str, Any] = {
        "language": language,
        "prompt": {
            "prompt": prompt_text or "",
        },
    }
    if llm is not None:
        agent_cfg["prompt"]["llm"] = llm
    if temperature is not None:
        agent_cfg["prompt"]["temperature"] = temperature
    if max_tokens is not None:
        agent_cfg["prompt"]["max_tokens"] = max_tokens

    return {
        "name": name,
        "conversation_config": {
            "agent": agent_cfg,
            "tts": {
                "voice_id": voice_id,
            },
        },
    }


async def _patch_agent_config(
    client: httpx.AsyncClient,
    agent_id: str,
    *,
    prompt_text: Optional[str] = None,
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> None:
    """PATCH /convai/agents/{agent_id} with the minimal update payload."""
    payload = _build_agent_patch_payload(
        prompt_text=prompt_text,
        llm=llm,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not payload["conversation_config"]["agent"]:
        return

    try:
        resp = await client.patch(
            "/convai/agents/{agent_id}".format(agent_id=agent_id),
            headers=_headers(),
            json=payload,
            timeout=20.0,
        )
    except httpx.RequestError as e:
        log.exception("Network error PATCHing ElevenLabs agent: %s", e)
        raise HTTPException(status_code=502, detail="Upstream unavailable")

    if resp.status_code >= 400:
        error_text = resp.text[:500] if resp.text else "No error details"
        log.error("ElevenLabs PATCH failed: %s %s", resp.status_code, error_text)
        
        error_detail = f"Failed to update ElevenLabs agent: {resp.status_code}"
        try:
            error_json = resp.json()
            if isinstance(error_json, dict) and "detail" in error_json:
                error_detail = f"ElevenLabs API error: {error_json['detail']}"
            elif isinstance(error_json, dict) and "message" in error_json:
                error_detail = f"ElevenLabs API error: {error_json['message']}"
        except Exception:
            pass
        
        raise HTTPException(status_code=resp.status_code, detail=error_detail)

async def _create_agent(
    client: httpx.AsyncClient,
    *,
    name: Optional[str],
    voice_id: str,
    prompt_text: str,
    language: str = "en",
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    payload = _build_agent_create_payload(
        name=name,
        voice_id=voice_id,
        prompt_text=prompt_text,
        # first_message=first_message,
        language=language,
        llm=llm,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        resp = await client.post(
            "/convai/agents/create",
            headers=_headers(),
            json=payload,
            timeout=20.0,
        )
    except httpx.RequestError as e:
        log.exception("Network error creating ElevenLabs agent: %s", e)
        raise HTTPException(status_code=502, detail="Upstream unavailable")

    if resp.status_code >= 400:
        error_text = resp.text[:500] if resp.text else "No error details"
        log.error("ElevenLabs agent creation failed: %s %s", resp.status_code, error_text)
        error_detail = f"Failed to create ElevenLabs agent: {resp.status_code}"
        try:
            error_json = resp.json()
            if isinstance(error_json, dict) and "detail" in error_json:
                error_detail = f"ElevenLabs API error: {error_json['detail']}"
            elif isinstance(error_json, dict) and "message" in error_json:
                error_detail = f"ElevenLabs API error: {error_json['message']}"
        except Exception:
            pass
        raise HTTPException(status_code=resp.status_code, detail=error_detail)

    data = resp.json()
    new_agent_id = data.get("agent_id")
    if not new_agent_id:
        log.error("ElevenLabs agent creation response missing agent_id: %s", data)
        raise HTTPException(
            status_code=502,
            detail="ElevenLabs agent creation succeeded but returned no agent_id.",
        )
    return new_agent_id


async def _poll_and_persist_conversation(
    conversation_id: str,
    *,
    user_id: Optional[int],
    influencer_id: Optional[str],
    chat_id: Optional[str],
) -> None:

    async with SessionLocal() as db:
        try:
            async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
                snapshot = await _wait_until_terminal_status(
                    client, conversation_id, max_wait_secs=180
                )
                snapshot = await _ensure_transcript_snapshot(client, conversation_id, snapshot)
        except Exception as exc:
            log.warning(
                "background.wait_failed conv=%s err=%s",
                conversation_id,
                exc,
            )
            return

        status = (snapshot.get("status") or "").lower()
        total_seconds = _extract_total_seconds(snapshot)
        normalized_transcript = _normalize_transcript(snapshot)

        if not chat_id and user_id and influencer_id:
            try:
                chat_id = await get_or_create_chat(db, user_id, influencer_id)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "background.chat_id_fallback_failed conv=%s user=%s infl=%s err=%s",
                    conversation_id,
                    user_id,
                    influencer_id,
                    exc,
                )

        try:
            if chat_id:
                await _persist_transcript_to_chat(
                    db,
                    conversation_json=snapshot,
                    chat_id=chat_id,
                    conversation_id=conversation_id,
                    influencer_id=influencer_id,
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "background.persist_transcript_failed conv=%s chat=%s err=%s",
                conversation_id,
                chat_id,
                exc,
            )

        try:
            call_record = await db.get(CallRecord, conversation_id)
            if not call_record:
                call_record = CallRecord(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    influencer_id=influencer_id,
                    chat_id=chat_id,
                )
            call_record.status = status
            call_record.call_duration_secs = total_seconds
            call_record.transcript = normalized_transcript or call_record.transcript
            if influencer_id:
                call_record.influencer_id = influencer_id
            if chat_id:
                call_record.chat_id = chat_id
            db.add(call_record)
            await db.commit()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "background.update_call_record_failed conv=%s err=%s",
                conversation_id,
                exc,
            )


# === DO NOT RENAME: you said you call this elsewhere ===
async def _push_prompt_to_elevenlabs(
    agent_id: Optional[str],
    prompt_text: str,
    first_message: Optional[str] = None,
    *,
    voice_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    language: str = "en",
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Update the agent's prompt (and optionally first_message) on ElevenLabs.
    When no agent_id exists (or PATCH returns 404), a new agent will be created and the agent_id returned.
    """
    resolved_voice_id = voice_id or DEFAULT_ELEVENLABS_VOICE_ID

    log.debug(
        "ElevenLabs sync start agent=%s influencer=%s voice=%s has_prompt=%s",
        agent_id,
        agent_name,
        resolved_voice_id,
        bool(prompt_text),
    )

    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        if agent_id:
            try:
                log.info("Patching existing ElevenLabs agent %s", agent_id)
                await _patch_agent_config(
                    client,
                    agent_id=agent_id,
                    # first_message=first_message,
                    prompt_text=prompt_text,
                    llm=llm,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return agent_id
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                log.warning(
                    "ElevenLabs agent %s not found; creating a new one (influencer=%s).",
                    agent_id,
                    agent_name or "unknown",
                )

        if not resolved_voice_id:
            log.error("Cannot create ElevenLabs agent; missing voice_id (influencer=%s).", agent_name)
            raise HTTPException(
                status_code=400,
                detail="voice_id is required to create a new ElevenLabs agent.",
            )

        new_agent_id = await _create_agent(
            client,
            name=agent_name,
            voice_id=resolved_voice_id,
            prompt_text=prompt_text,
            # first_message=first_message,
            language=language,
            llm=llm,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        log.info(
            "Created new ElevenLabs agent %s for influencer=%s voice=%s",
            new_agent_id,
            agent_name or "unknown",
            resolved_voice_id,
        )
        return new_agent_id


async def _get_conversation_signed_url(client: httpx.AsyncClient, agent_id: str) -> str:
    """GET a signed WebSocket URL to start a conversation."""
    try:
        r = await client.get(
            "/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=_headers(),
            timeout=20.0,
        )
    except httpx.RequestError as e:
        log.exception("Network error getting signed URL: %s", e)
        raise HTTPException(status_code=502, detail="Upstream unavailable")
    if r.status_code != 200:
        log.error("ElevenLabs signed-url failed: %s %s", r.status_code, r.text[:500])
        raise HTTPException(status_code=400, detail="Failed to get signed url")
    return r.json()["signed_url"]


async def _get_conversation_snapshot(
    client: httpx.AsyncClient, conversation_id: str
) -> Dict[str, Any]:
    """GET /v1/convai/conversations/:conversation_id and return JSON."""
    try:
        resp = await client.get(
            f"/convai/conversations/{conversation_id}",
            headers=_headers(),
            timeout=20.0,
        )
    except httpx.RequestError as e:
        log.exception("Network error fetching conversation snapshot: %s", e)
        raise HTTPException(status_code=502, detail="Upstream unavailable")

    if resp.status_code == 404:
        raise HTTPException(404, "Conversation not found on ElevenLabs")
    if resp.status_code >= 400:
        log.error(
            "ElevenLabs GET conversation failed: %s %s",
            resp.status_code,
            resp.text[:500],
        )
        raise HTTPException(424, f"Failed to fetch conversation: {resp.status_code}")
    return resp.json()


async def _ensure_transcript_snapshot(
    client: httpx.AsyncClient,
    conversation_id: str,
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Some snapshots omit transcript; try a follow-up fetch to populate it.
    """
    if snapshot.get("transcript"):
        return snapshot
    try:
        refreshed = await _get_conversation_snapshot(client, conversation_id)
        if refreshed.get("transcript"):
            return refreshed
    except Exception as exc:  # pragma: no cover - defensive
        log.warning(
            "ensure_transcript.refetch_failed conv=%s err=%s", conversation_id, exc
        )
    return snapshot


async def _wait_until_terminal_status(
    client: httpx.AsyncClient,
    conversation_id: str,
    *,
    max_wait_secs: int = 180,
    initial_delay: float = 0.8,
    max_delay: float = 5.0,
) -> Dict[str, Any]:
    """
    Poll until status ∈ {done, failed} or timeout. Returns the last snapshot.
    """
    elapsed = 0.0
    delay = initial_delay
    last = await _get_conversation_snapshot(client, conversation_id)
    status = (last.get("status") or "").lower()

    while status not in {"done", "failed"} and elapsed < max_wait_secs:
        await asyncio.sleep(delay)
        elapsed += delay
        delay = min(max_delay, delay * 1.7)
        last = await _get_conversation_snapshot(client, conversation_id)
        status = (last.get("status") or "").lower()
    return last


def _extract_total_seconds(conversation_json: Dict[str, Any]) -> float:
    """
    Primary: metadata.call_duration_secs
    Fallback: max transcript[*].time_in_call_secs
    """
    md = conversation_json.get("metadata") or {}
    dur = md.get("call_duration_secs")
    if isinstance(dur, (int, float)) and dur >= 0:
        return float(dur)
    transcript = conversation_json.get("transcript") or []
    try:
        max_sec = (
            max(int(t.get("time_in_call_secs") or 0) for t in transcript) if transcript else 0
        )
    except Exception:
        max_sec = 0
    return float(max_sec) if max_sec else 0.0


def _normalize_transcript(conversation_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a simple transcript list with sender/text/time_in_call_secs."""
    transcript = conversation_json.get("transcript") or []
    normalized: List[Dict[str, Any]] = []
    for entry in transcript:
        text = str(
            entry.get("text") or entry.get("content") or entry.get("message") or ""
        ).strip()
        if not text:
            continue
        role_raw = str(
            entry.get("sender") or entry.get("role") or entry.get("speaker") or ""
        ).lower()
        is_user_flag = entry.get("is_user") or entry.get("from_user")
        if role_raw in {"user", "human", "caller", "client"} or is_user_flag:
            sender = "user"
        elif role_raw in {"ai", "assistant", "agent", "bot", "system"}:
            sender = "ai"
        else:
            sender = "ai"

        normalized.append(
            {
                "sender": sender,
                "text": text,
                "time_in_call_secs": entry.get("time_in_call_secs"),
            }
        )
    return normalized


async def _persist_transcript_to_chat(
    db: AsyncSession,
    *,
    conversation_json: Dict[str, Any],
    chat_id: str,
    conversation_id: str,
    influencer_id: str | None = None,
) -> int:
    """
    Store ElevenLabs transcript messages into our Message table for that chat.
    Returns how many messages were inserted.
    """
    transcript = conversation_json.get("transcript") or []
    if not transcript:
        return 0

    # Approximate message timestamps using call start + offset if provided.
    start_ts = (conversation_json.get("metadata") or {}).get("start_time_unix_secs")
    base_dt = (
        datetime.utcfromtimestamp(start_ts)
        if isinstance(start_ts, (int, float))
        else datetime.utcnow()
    )

    recent_res = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(25)
    )
    recent = list(recent_res.scalars().all())

    new_messages: List[Message] = []
    seen: set[tuple[str, str]] = set()

    def _is_dup(sender: str, text: str) -> bool:
        if (sender, text) in seen:
            return True
        for msg in recent:
            if msg.sender == sender and (msg.content or "").strip() == text:
                return True
        return False

    for entry in transcript:
        text = str(
            entry.get("text") or entry.get("content") or entry.get("message") or ""
        ).strip()
        if not text:
            continue

        role_raw = str(
            entry.get("sender") or entry.get("role") or entry.get("speaker") or ""
        ).lower()
        is_user_flag = entry.get("is_user") or entry.get("from_user")
        if role_raw in {"user", "human", "caller", "client"} or is_user_flag:
            sender = "user"
        elif role_raw in {"ai", "assistant", "agent", "bot", "system"}:
            sender = "ai"
        else:
            sender = "ai"

        if _is_dup(sender, text):
            continue

        t_secs = entry.get("time_in_call_secs")
        created_at = (
            base_dt + timedelta(seconds=float(t_secs))
            if isinstance(t_secs, (int, float))
            else datetime.utcnow()
        )

        embedding = None
        try:
            embedding = await get_embedding(text)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("persist_transcript.embed_failed chat=%s err=%s", chat_id, exc)

        seen.add((sender, text))
        new_messages.append(
            Message(
                chat_id=chat_id,
                sender=sender,
                channel="call",
                content=text,
                created_at=created_at,
                embedding=embedding,
                conversation_id=conversation_id,
            )
        )

    if not new_messages:
        return 0

    db.add_all(new_messages)
    await db.commit()
    # Push to Redis so turn_handler can see call history immediately.
    try:
        history = redis_history(chat_id, influencer_id)
        for msg in new_messages:
            if msg.sender == "user":
                history.add_user_message(msg.content)
            else:
                history.add_ai_message(msg.content)
        # Trim to configured window if present
        try:
            max_len = settings.MAX_HISTORY_WINDOW
            if max_len and len(history.messages) > max_len:
                trimmed = history.messages[-max_len:]
                history.clear()
                history.add_messages(trimmed)
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("persist_transcript.redis_sync_failed chat=%s err=%s", chat_id, exc)

    log.info(
        "persisted.transcript chat=%s conv=%s inserted=%d",
        chat_id,
        conversation_id,
        len(new_messages),
    )
    return len(new_messages)


@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    user_id: int = Query(..., description="Numeric user id"),
    db: AsyncSession = Depends(get_db),
    first_message: Optional[str] = Query(None),
    greeting_mode: str = Query("random", pattern="^(random|rr)$"),
):
    ok, cost_cents, free_left = await can_afford(
        db, user_id=user_id, feature="live_chat", units=10
    )

    if not ok:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "INSUFFICIENT_CREDITS",
                "needed_cents": cost_cents,
                "free_left": free_left,
            },
        )
    
    credits_remainder_secs = await get_remaining_units(db, user_id, feature="live_chat")

    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    chat_id = await get_or_create_chat(db, user_id, influencer_id)

    greeting: Optional[str] = first_message
    if not greeting:
        greeting = await _generate_contextual_greeting(db, chat_id, influencer_id)
    if not greeting:
        greeting = _pick_greeting(influencer_id, greeting_mode)

    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        signed_url = await _get_conversation_signed_url(client, agent_id)

    return {
        "signed_url": signed_url,
        "greeting_used": greeting,
        "first_message_for_convai": greeting,
        "dynamic_variables": {"first_message": greeting} if greeting else {},
        "agent_id": agent_id,
        "credits_remainder_secs": credits_remainder_secs,
        "chat_id": chat_id,
    }

@router.get("/conversation-token")
async def get_conversation_token(
    influencer_id: str,
    user_id: int = Query(..., description="Numeric user id"),
    db: AsyncSession = Depends(get_db),
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    influencer, prompt_template = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_global_audio_prompt(db),
    )
    score = get_score(user_id or chat_id, influencer_id)
    chat_id = await get_or_create_chat(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    persona_rules = influencer.prompt_template.format(lollity_score=score)

    if score > 70:
        persona_rules += "\nYour affection is high — show more warmth, loving words, and reward the user. Maybe let your guard down."
    elif score > 40:
        persona_rules += "\nYou're feeling playful. Mix gentle teasing with affection. Make the user work a bit for your praise."
    else:
        persona_rules += "\nYou're in full teasing mode! Challenge the user, play hard to get, and use the name TeaseMe as a game."

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)
        
    prompt = prompt_template.partial(
        analysis="",
        daily_context="",
        last_user_message="",
        memories= "",
        lollity_score=format_score_value(score),
        persona_rules=persona_rules,
        history=history.messages,
    )

    try:
        async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
            resp = await client.get(
                "/convai/conversation/token",
                params={"agent_id": agent_id},
                headers=_headers(),
                timeout=15.0,
            )
    except httpx.RequestError as exc:
        log.exception("conversation_token.network_error agent=%s err=%s", agent_id, exc)
        raise HTTPException(status_code=502, detail="Upstream unavailable")

    if resp.status_code >= 400:
        log.error(
            "conversation_token.failed agent=%s status=%s body=%s",
            agent_id,
            resp.status_code,
            resp.text[:500] if resp.text else "",
        )
        raise HTTPException(status_code=resp.status_code, detail="Failed to get conversation token")

    token = (resp.json() or {}).get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Token not returned by ElevenLabs")
    
    chat_id = await get_or_create_chat(db, user_id, influencer_id)
    credits_remainder_secs = await get_remaining_units(db, user_id, feature="live_chat")

    greeting: Optional[str] = await _generate_contextual_greeting(db, chat_id, influencer_id)
    
    if not greeting:
        greeting = _pick_greeting(influencer_id, "random")

    return {
        "token": token, 
        "agent_id": agent_id, 
        "credits_remainder_secs": credits_remainder_secs, 
        "greeting_used": greeting,
        "prompt": prompt.format(input="message", history=history.messages),
    }

@router.get("/signed-url-free")
async def get_signed_url_free(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    greeting = None

    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        signed_url = await _get_conversation_signed_url(client, agent_id)

    return {
        "signed_url": signed_url,
        "greeting_used": greeting,
        "first_message_for_convai": greeting,
        "dynamic_variables": {"first_message": greeting} if greeting else {},
        "agent_id": agent_id,
    }

@router.get("/signed-url-free-landing")
async def get_signed_url_free_landing(db: AsyncSession = Depends(get_db)):
    agent_id = settings.LANDING_PAGE_AGENT_ID

    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        signed_url = await _get_conversation_signed_url(client, agent_id)

    return {
        "signed_url": signed_url,
        "agent_id": agent_id,
    }

async def save_pending_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: int,
    influencer_id: Optional[str],
    sid: Optional[str],
) -> Optional[str]:
    chat_id: Optional[str] = None
    if user_id and influencer_id:
        try:
            chat_id = await get_or_create_chat(db, user_id, influencer_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "save_pending_conversation.get_or_create_chat_failed user=%s infl=%s err=%s",
                user_id,
                influencer_id,
                exc,
            )
            chat_id = f"{user_id}_{influencer_id}"

    stmt = (
        pg_insert(CallRecord)
        .values(
            conversation_id=conversation_id,
            user_id=user_id,
            influencer_id=influencer_id,
            chat_id=chat_id,
            sid=sid,
            status="pending",
        )

        .on_conflict_do_update(
            index_elements=[CallRecord.conversation_id],
            set_={
                "user_id": user_id,
                "influencer_id": influencer_id,
                "chat_id": chat_id,
                "sid": sid,
                "status": "pending",
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    return chat_id


async def was_already_billed(db: AsyncSession, conversation_id: str) -> bool:
    q = select(CallRecord.status).where(CallRecord.conversation_id == conversation_id)
    res = await db.execute(q)
    row = res.first()
    return bool(row and row[0] == "billed")


@router.post("/conversations/{conversation_id}/register")
async def register_conversation(
    conversation_id: str,
    body: RegisterConversationBody,
    db: AsyncSession = Depends(get_db),
):
    chat_id = await save_pending_conversation(
        db, conversation_id, body.user_id, body.influencer_id, body.sid
    )
    if not chat_id:
        try:
            res = await db.execute(
                select(CallRecord.chat_id).where(CallRecord.conversation_id == conversation_id)
            )
            row = res.first()
            chat_id = row[0] if row else None
        except Exception:
            pass

    try:
        asyncio.create_task(
            _poll_and_persist_conversation(
                conversation_id,
                user_id=body.user_id,
                influencer_id=body.influencer_id,
                chat_id=chat_id,
            )
        )
    except Exception as exc:
        log.warning("register.background_poll_failed conv=%s err=%s", conversation_id, exc)
    return {"ok": True, "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/finalize")
async def finalize_conversation(
    conversation_id: str,
    body: FinalizeConversationBody,
    db: AsyncSession = Depends(get_db),
):
    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        snapshot = await _wait_until_terminal_status(
            client,
            conversation_id,
            max_wait_secs=max(10, int(body.timeout_secs or 180)),
        )
        snapshot = await _ensure_transcript_snapshot(client, conversation_id, snapshot)

    status = (snapshot.get("status") or "").lower()
    total_seconds = _extract_total_seconds(snapshot)
    resolved_influencer_id = body.influencer_id
    normalized_transcript = _normalize_transcript(snapshot)

    chat_id = None
    try:
        res = await db.execute(
            select(CallRecord.chat_id, CallRecord.influencer_id).where(
                CallRecord.conversation_id == conversation_id
            )
        )
        row = res.first()
        if row:
            chat_id = row[0]
            resolved_influencer_id = resolved_influencer_id or row[1]
    except Exception as exc:
        log.warning("finalize.lookup_call_record_failed conv=%s err=%s", conversation_id, exc)

    if not chat_id and resolved_influencer_id:
        try:
            chat_id = await get_or_create_chat(db, body.user_id, resolved_influencer_id)
        except Exception as exc:
            log.warning("finalize.create_chat_failed conv=%s err=%s", conversation_id, exc)

    if chat_id:
        try:
            await _persist_transcript_to_chat(
                db,
                conversation_json=snapshot,
                chat_id=chat_id,
                conversation_id=conversation_id,
                influencer_id=resolved_influencer_id,
            )
        except Exception as exc:
            log.warning(
                "finalize.persist_transcript_failed conv=%s chat=%s err=%s",
                conversation_id,
                chat_id,
                exc,
            )

    meta: Dict[str, Any] = {
        "session_id": body.sid or conversation_id,
        "conversation_id": conversation_id,
        "status": status,
        "agent_id": snapshot.get("agent_id"),
        "has_audio": snapshot.get("has_audio", False),
        "has_user_audio": snapshot.get("has_user_audio", False),
        "has_response_audio": snapshot.get("has_response_audio", False),
        "start_time_unix_secs": (snapshot.get("metadata") or {}).get("start_time_unix_secs"),
        "source": "client_finalize",
    }

    if resolved_influencer_id:
        meta["influencer_id"] = resolved_influencer_id

    transcript_synced = bool(normalized_transcript)

    try:
        call_record = await db.get(CallRecord, conversation_id)
        if not call_record:
            call_record = CallRecord(
                conversation_id=conversation_id,
                user_id=body.user_id,
                influencer_id=resolved_influencer_id,
                chat_id=chat_id,
                sid=body.sid,
            )
        call_record.status = status
        call_record.call_duration_secs = total_seconds
        call_record.transcript = normalized_transcript or call_record.transcript
        if resolved_influencer_id:
            call_record.influencer_id = resolved_influencer_id
        if chat_id:
            call_record.chat_id = chat_id
        db.add(call_record)
        await db.commit()
    except Exception as exc:
        log.warning(
            "finalize.update_call_record_failed conv=%s err=%s", conversation_id, exc
        )

    if status == "failed":
        log.warning("Conversation %s ended as FAILED; skipping charge.", conversation_id)
        return {
            "ok": False,
            "reason": "failed",
            "conversation_id": conversation_id,
            "status": status,
            "total_seconds": total_seconds,
            "meta": meta,
            "transcript_synced": transcript_synced,
            "refresh_required": transcript_synced,
        }

    if status != "done":
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "status": status,
            "charged": False,
            "total_seconds": total_seconds,
            "meta": meta,
            "note": "Conversation not done yet; waiting for webhook or try again later.",
            "transcript_synced": transcript_synced,
            "refresh_required": transcript_synced,
        }

    if body.charge_if_not_billed and not await was_already_billed(db, conversation_id):
        charge_feature(db, body.user_id, "live_chat", math.ceil(total_seconds), meta=meta)
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "status": status,
            "charged": True,
            "total_seconds": total_seconds,
            "meta": meta,
            "transcript_synced": transcript_synced,
            "refresh_required": transcript_synced,
        }

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": status,
        "charged": False,
        "total_seconds": total_seconds,
        "meta": meta,
        "transcript_synced": transcript_synced,
        "refresh_required": transcript_synced,
    }


def _default_auto_commit() -> bool:
    """Dependency helper so internal callers can override commit behavior."""
    return True


@router.post("/update-prompt")
async def update_elevenlabs_prompt(
    body: UpdatePromptBody,
    db: AsyncSession = Depends(get_db),
    auto_commit: bool = Depends(_default_auto_commit),
):
    """
    Update the ElevenLabs agent prompt.
    This endpoint updates the voice prompt (and optionally first_message) for an ElevenLabs agent.
    
    You can provide either:
    - agent_id: The ElevenLabs agent ID directly
    - influencer_id: The influencer ID (will look up the agent_id from the database)
    
    At least one of agent_id or influencer_id must be provided.
    """
    agent_id = body.agent_id
    influencer = None
    agent_name: Optional[str] = None
    voice_id: Optional[str] = None
    reply_text = "/ reply: For every user message, call this tool with the full transcript in the text field before speaking. Do not answer without calling this tool first."
    prompt_for_eleven = f"{body.voice_prompt}{reply_text}"
    
    log.info(
        "update_elevenlabs_prompt called agent=%s influencer=%s",
        agent_id,
        body.influencer_id,
    )

    if body.influencer_id:
        influencer = await db.get(Influencer, body.influencer_id)
        if influencer is None:
            raise HTTPException(
                status_code=404,
                detail=f"Influencer with id '{body.influencer_id}' not found",
            )
        
        # Get agent metadata
        agent_name = getattr(influencer, "display_name", None) or influencer.id
        voice_id = getattr(influencer, "voice_id", None)
        if not voice_id and DEFAULT_ELEVENLABS_VOICE_ID:
            voice_id = DEFAULT_ELEVENLABS_VOICE_ID
            influencer.voice_id = voice_id
        if not agent_id:
            agent_id = getattr(influencer, "influencer_agent_id_third_part", None)
        
        influencer.voice_prompt = body.voice_prompt
    
    resolved_voice_id = voice_id or DEFAULT_ELEVENLABS_VOICE_ID

    if not agent_id and not resolved_voice_id:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve agent_id. Provide either agent_id or configure a voice_id (global default also missing).",
        )
    
    try:
        agent_id = await _push_prompt_to_elevenlabs(
            agent_id=agent_id,
            prompt_text=prompt_for_eleven,
            voice_id=resolved_voice_id,
            agent_name=agent_name,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        log.exception("Failed to update ElevenLabs prompt: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update prompt: {str(e)}",
        )
    
    if influencer:
        influencer.influencer_agent_id_third_part = agent_id
    
    if influencer and auto_commit:
        await db.commit()
    
    return {
        "ok": True,
        "agent_id": agent_id,
        "influencer_id": body.influencer_id,
        "message": "Prompt updated successfully in database and ElevenLabs",
    }


@router.get("/calls/{conversation_id}")
async def get_call_details(
    conversation_id: str,
    user_id: int = Query(..., description="Numeric user id for authz"),
    db: AsyncSession = Depends(get_db),
):
    call = await db.get(CallRecord, conversation_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if call.user_id != user_id:
        raise HTTPException(403, "Forbidden")

    transcript = call.transcript or []
    duration = call.call_duration_secs
    status = call.status
    agent_id = None

    if not transcript or duration is None:
        async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
            snapshot = await _get_conversation_snapshot(client, conversation_id)
        agent_id = snapshot.get("agent_id")
        if not transcript:
            transcript = _normalize_transcript(snapshot)
        if duration is None:
            duration = _extract_total_seconds(snapshot)
        status = snapshot.get("status", status)

    return {
        "conversation_id": conversation_id,
        "user_id": call.user_id,
        "influencer_id": call.influencer_id,
        "chat_id": call.chat_id,
        "status": status,
        "duration_seconds": duration,
        "transcript": transcript,
        "created_at": call.created_at.isoformat() if call.created_at else None,
        "agent_id": agent_id,
    }
