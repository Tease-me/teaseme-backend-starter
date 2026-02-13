import asyncio
import logging
import math
import random
import json
from uuid import uuid4
from app.agents.prompt_utils import build_relationship_prompt, get_global_prompt, get_mbti_rules_for_archetype, get_relationship_stage_prompts, get_time_context
from app.relationship.dtr import plan_dtr_goal
from app.relationship.inactivity import apply_inactivity_decay
from app.relationship.repo import get_or_create_relationship
import httpx
from datetime import datetime, timedelta, timezone
from app.moderation import moderate_message, handle_violation
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.ext.asyncio import AsyncSession
from itertools import chain
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.db.models import Influencer, Chat, Message, CallRecord, User, PreInfluencer
from app.db.session import get_db
from app.utils.auth.dependencies import get_current_user
from app.schemas.elevenlabs import FinalizeConversationBody, RegisterConversationBody, UpdatePromptBody
from app.services.billing import charge_feature,_get_influencer_id_from_chat
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.services.billing import can_afford, get_remaining_units
from app.services.chat_service import get_or_create_chat
from app.agents.turn_handler import _norm, _build_user_name_block, redis_history
from langchain_core.prompts import ChatPromptTemplate
from app.db.session import SessionLocal
from app.services.embeddings import get_embedding
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys
from app.agents.prompts import GREETING_GENERATOR
from app.utils.logging.prompt_logging import log_prompt

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])
log = logging.getLogger(__name__)

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVEN_BASE_URL = settings.ELEVEN_BASE_URL
DEFAULT_ELEVENLABS_VOICE_ID = settings.ELEVENLABS_VOICE_ID or None

# Shared HTTP client for connection pooling
_elevenlabs_client: Optional[httpx.AsyncClient] = None

async def get_elevenlabs_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling for ElevenLabs API."""
    global _elevenlabs_client
    if _elevenlabs_client is None:
        _elevenlabs_client = httpx.AsyncClient(
            http2=True,
            base_url=ELEVEN_BASE_URL,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0
            ),
        )
        log.info("Created shared ElevenLabs HTTP client with connection pooling")
    return _elevenlabs_client


async def close_elevenlabs_client() -> None:
    """Close the shared ElevenLabs HTTP client gracefully."""
    global _elevenlabs_client
    if _elevenlabs_client is not None:
        await _elevenlabs_client.aclose()
        _elevenlabs_client = None
        log.info("Closed ElevenLabs HTTP client")

def _get_env_suffix() -> str:
    device = settings.DEVICE.upper() if settings.DEVICE else ""
    if device == "SERVER":
        return "-PROD"
    elif device == "LIVE":
        return "-LIVE"
    else:
        return "-DEV"

def _apply_env_suffix(name: str) -> str:
    suffix = _get_env_suffix()
    return f"{name}{suffix}"

_GREETINGS: Dict[str, List[str]] = {
    "playful": [
        "Well, look who finally decided to show up.",
        "Oh hey! You actually have perfect timing.",
        "There you are. I was about to start talking to myself.",
        "Hey! Save me from boredom, will you?",
    ],
    "anna": [
        "Hiii! ✨ I was literally just checking my phone!",
        "Omg hi!! How is your day going??",
        "Yay! You're actually here! 👋",
    ],
    "bella": [
        "Hey... it's really nice to see you.",
        "Hi. I was hoping to catch you today.",
        "There you are. How have you been?",
    ],
}

_rr_index: Dict[str, int] = {}

_DOPAMINE_OPENERS: Dict[str, List[str]] = {
    "anna": [
        "Okay, you won't believe what just happened to me!",
        "I was just about to message you! telepathy?? ✨",
    ],
    "bella": [
        "My phone buzzed and I actually hoped it was you.",
        "I saw something today that totally reminded me of you.",
    ],
    "playful": [
        "I have a question, and I feel like only you would know the answer.",
        "Warning: I'm in a mood to distract you from whatever you're doing.",
    ],
}

_RANDOM_FIRST_GREETINGS: List[str] = [
    "Hello?",
    "Hello, this is {persona_name}. Who’s calling?",
    "Hi, who am I speaking with?",
]

def _headers() -> Dict[str, str]:
    """Return ElevenLabs auth headers. Fail fast when misconfigured."""
    if not ELEVENLABS_API_KEY:
        raise HTTPException(500, "ELEVENLABS_API_KEY is not configured.")
    return {"xi-api-key": ELEVENLABS_API_KEY}


_POST_CALL_WEBHOOK_ID: Optional[str] = None
_WEBHOOK_NAME = "teaseme-post-call"


async def _get_or_create_post_call_webhook(client: httpx.AsyncClient) -> Optional[str]:
    global _POST_CALL_WEBHOOK_ID
    if _POST_CALL_WEBHOOK_ID:
        return _POST_CALL_WEBHOOK_ID

    webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/elevenlabs"
    
    try:
        list_resp = await client.get(
            "/workspace/webhooks",
            headers=_headers(),
            timeout=15.0,
        )
        if list_resp.status_code == 200:
            webhooks = list_resp.json()
            webhook_list = webhooks if isinstance(webhooks, list) else webhooks.get("webhooks", [])
            for wh in webhook_list:
                if wh.get("name") == _WEBHOOK_NAME or wh.get("webhook_url") == webhook_url:
                    _POST_CALL_WEBHOOK_ID = wh.get("webhook_id") or wh.get("id")
                    log.info("Found existing post-call webhook: %s", _POST_CALL_WEBHOOK_ID)
                    return _POST_CALL_WEBHOOK_ID
    except Exception as e:
        log.warning("Failed to list webhooks: %s", e)

    try:
        create_resp = await client.post(
            "/workspace/webhooks",
            headers=_headers(),
            json={
                "name": _WEBHOOK_NAME,
                "webhook_url": webhook_url,
                "auth_type": "hmac",
                "events": ["post_call_transcription"],
            },
            timeout=15.0,
        )
        if create_resp.status_code in (200, 201):
            data = create_resp.json()
            _POST_CALL_WEBHOOK_ID = data.get("webhook_id") or data.get("id")
            log.info("Created post-call webhook: %s", _POST_CALL_WEBHOOK_ID)
            return _POST_CALL_WEBHOOK_ID
        else:
            log.warning("Failed to create webhook: %s %s", create_resp.status_code, create_resp.text[:300])
    except Exception as e:
        log.warning("Exception creating webhook: %s", e)

    return None


async def _validate_voice_exists(voice_id: str) -> bool:
    """
    Check if a voice_id still exists in ElevenLabs.
    Returns True if voice exists, False if deleted/not found.
    """
    if not voice_id:
        return False
    
    log.info("Validating voice_id: %s", voice_id)
    client = await get_elevenlabs_client()
    try:
        resp = await client.get(
            f"/voices/{voice_id}",
            headers=_headers(),
            timeout=15.0,
        )
        log.info("Voice validation response: %s", resp.status_code)
        if resp.status_code == 200:
            return True
        elif resp.status_code == 404:
            log.warning("Voice %s not found in ElevenLabs", voice_id)
            return False
        else:
            log.warning("Voice validation returned %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        log.warning("Voice validation error for %s: %s", voice_id, e)
        return False


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
        history = redis_history(chat_id)
    except Exception as exc:
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


def _classify_gap(minutes: float) -> str:
    if minutes < 2:
        return "immediate"
    elif minutes < 15:
        return "short"
    elif minutes < 120: 
        return "medium"
    elif minutes < 1440: 
        return "long"
    else:
        return "extended"


def _classify_call_ending(call: Optional[CallRecord]) -> str:
    if not call:
        return "normal"
    duration = call.call_duration_secs or 0
    if duration < 30:
        return "abrupt"
    elif duration > 300:
        return "lengthy"
    else:
        return "normal"


def _extract_last_message(db_messages: List[Message], transcript: Optional[str]) -> str:
    if db_messages:
        for msg in db_messages:
            content = (msg.content or "").strip()
            if content and len(content) > 5:
                return content[:100]  
    
    if transcript:
        lines = transcript.strip().split("\n")
        for line in reversed(lines):
            if ":" in line:
                text = line.split(":", 1)[-1].strip()
                if text and len(text) > 5:
                    return text[:100]
    
    return ""


async def _get_contextual_first_message_prompt(db: AsyncSession) -> ChatPromptTemplate:
    system_prompt = await get_system_prompt(db, prompt_keys.CONTEXTUAL_FIRST_MESSAGE)
    if not system_prompt:
        system_prompt = (
            "You are {influencer_name}, an affectionate companion. "
            "Generate a warm, natural greeting for a call. Gap category: {gap_category}. "
            "Last message: {last_message}. Keep it to 8-14 words with a natural pause."
        )
    
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Generate the greeting now. Output only the greeting text."),
    ])


async def _generate_contextual_greeting(
    db: AsyncSession, chat_id: str, influencer_id: str
) -> Optional[str]:
    """
    Generate a contextual greeting using parallel DB lookups for speed.
    Uses dedicated sessions to avoid AsyncSession concurrency issues.
    Performance: ~100-200ms faster than sequential approach.
    """
    if GREETING_GENERATOR is None:
        return None

    # ============================================================
    # PHASE 1: Parallel fetches with dedicated sessions
    # Each helper uses its own SessionLocal() to avoid concurrent access
    # ============================================================
    
    async def _fetch_messages_standalone() -> List[Message]:
        """Fetch last 8 messages using dedicated session."""
        async with SessionLocal() as session:
            result = await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.desc())
                .limit(8)
            )
            return list(result.scalars().all())
    
    async def _fetch_chat_standalone() -> Optional[Chat]:
        """Fetch chat using dedicated session."""
        async with SessionLocal() as session:
            return await session.get(Chat, chat_id)
    
    async def _fetch_influencer_standalone() -> Optional[Influencer]:
        """Fetch influencer using dedicated session."""
        async with SessionLocal() as session:
            return await session.get(Influencer, influencer_id)
    
    async def _fetch_last_call_standalone(user_id: int) -> Optional[CallRecord]:
        """Fetch last call record using dedicated session."""
        async with SessionLocal() as session:
            result = await session.execute(
                select(CallRecord)
                .where(
                    CallRecord.user_id == user_id,
                    CallRecord.influencer_id == influencer_id,
                )
                .order_by(CallRecord.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
    
    # First wave: messages, chat, influencer (no dependencies)
    try:
        db_messages, chat, influencer = await asyncio.gather(
            _fetch_messages_standalone(),
            _fetch_chat_standalone(),
            _fetch_influencer_standalone(),
        )
    except Exception as exc:
        log.warning("contextual_greeting.parallel_fetch_failed chat=%s err=%s", chat_id, exc)
        db_messages, chat, influencer = [], None, None

    # Second wave: last call + user (depends on user_id from chat)
    user_id = chat.user_id if chat else None
    last_call: Optional[CallRecord] = None
    user_obj = None
    
    if user_id:
        async def _fetch_user_standalone() -> Optional[User]:
            async with SessionLocal() as session:
                return await session.get(User, user_id)
        
        try:
            last_call, user_obj = await asyncio.gather(
                _fetch_last_call_standalone(user_id),
                _fetch_user_standalone(),
            )
        except Exception as exc:
            log.warning(
                "contextual_greeting.call_user_fetch_failed chat=%s user=%s infl=%s err=%s",
                chat_id, user_id, influencer_id, exc,
            )

    # ============================================================
    # PHASE 2: Process fetched data (same logic as before)
    # ============================================================
    
    last_interaction: Optional[datetime] = None
    transcript: Optional[str] = None

    if not db_messages:
        try:
            redis_ctx = _format_redis_history(chat_id, influencer_id)
            if redis_ctx:
                transcript = redis_ctx
        except Exception as exc:
            log.warning("contextual_greeting.redis_fallback_failed chat=%s err=%s", chat_id, exc)

    if db_messages:
        last_interaction = getattr(db_messages[0], "created_at", None) or last_interaction
        db_messages.reverse()
        transcript = _format_history(db_messages)

    if last_call and last_call.created_at:
        call_time = last_call.created_at
        
        if call_time.tzinfo is None:
            call_time = call_time.replace(tzinfo=timezone.utc)
        
        if last_interaction:
            if last_interaction.tzinfo is None:
                last_interaction = last_interaction.replace(tzinfo=timezone.utc)
        
        if last_interaction is None:
            last_interaction = call_time
        elif call_time > last_interaction:
            last_interaction = call_time
            
        if not transcript and last_call.transcript:
            transcript = _format_transcript_entries(last_call.transcript)

    gap_minutes: float = 0
    if last_interaction:
        if last_interaction.tzinfo is not None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.utcnow()
        gap_minutes = (now - last_interaction).total_seconds() / 60

    gap_category = _classify_gap(gap_minutes)
    call_ending_type = _classify_call_ending(last_call)
    last_call_duration = last_call.call_duration_secs if last_call else 0
    last_message = _extract_last_message(db_messages, transcript)

    persona_name = (
        influencer.display_name if influencer and influencer.display_name else influencer_id
    )

    if not transcript and not last_message:
        return _pick_random_first_greeting(persona_name)

    try:
        async with SessionLocal() as session:
            users_name = await _build_user_name_block(session, user_id)
        prompt = await _get_contextual_first_message_prompt(db)
        chain = prompt.partial(
            influencer_name=persona_name,
            users_name=users_name,
            gap_category=gap_category,
            gap_minutes=str(round(gap_minutes, 1)),
            call_ending_type=call_ending_type,
            last_call_duration_secs=str(int(last_call_duration or 0)),
            last_message=last_message or "(no recent message)",
            history=transcript or "(no recent history)",
        ) | GREETING_GENERATOR

        llm_response = await chain.ainvoke({})
        greeting = _add_natural_pause((llm_response.content or "").strip())
        
        if greeting.startswith('"') and greeting.endswith('"'):
            greeting = greeting[1:-1]
        if greeting.startswith("'") and greeting.endswith("'"):
            greeting = greeting[1:-1]
            
        log.info(
            "contextual_greeting.generated chat=%s gap=%s ending=%s greeting=%r",
            chat_id, gap_category, call_ending_type, greeting[:50] if greeting else None
        )
        return greeting if greeting else None
        
    except Exception as exc:
        log.warning("Failed to generate contextual greeting for %s: %s", chat_id, exc)
        return _pick_dopamine_greeting(influencer_id)


def _pick_dopamine_greeting(influencer_id: str) -> Optional[str]:
    options = _DOPAMINE_OPENERS.get(influencer_id) or _DOPAMINE_OPENERS.get("playful")
    if not options:
        return None
    return _add_natural_pause(random.choice(options))

def _pick_random_first_greeting(persona_name: str) -> str:
    choice = random.choice(_RANDOM_FIRST_GREETINGS) if _RANDOM_FIRST_GREETINGS else None
    return choice.format(persona_name=persona_name)

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

    agent_cfg["tools"] = [
        {
            "name": "updateRelationship",
            "type": "webhook",
            "description": "Production: Updates and Retrieves the relationship states",
            "webhook": {
                "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/update_relationship",
                "method": "POST",
                "request_headers": {
                     "X-Webhook-Token": settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET or ""
                }
            }
        },
        {
            "name": "getMemories",
            "type": "webhook",
            "description": "Production: Retrieves long-term user-persona memories from the memory bank",
            "webhook": {
               "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/memories",
               "method": "POST",
               "request_headers": {
                    "X-Webhook-Token": settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET or ""
               }
            }
        }
    ]

    return {
        "conversation_config": {
            "agent": agent_cfg,
            "client": {
                "overrides": {
                    "agent": {
                         "first_message": True,
                         "language": True,
                         "prompt": {
                             "prompt": True,
                         },
                    },
                    "tts": {
                        "voice_id": True,
                    }
                }
            }
        }
    }


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
        "tools": [
            {
                "name": "updateRelationship",
                "type": "webhook",
                "description": "Production: Updates and Retrieves the relationship states",
                "webhook": {
                    "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/update_relationship",
                    "method": "POST",
                    "request_headers": {
                         "X-Webhook-Token": settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET or ""
                    }
                }
            },
            {
                "name": "getMemories",
                "type": "webhook",
                "description": "Production: Retrieves long-term user-persona memories from the memory bank",
                "webhook": {
                   "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/memories",
                   "method": "POST",
                   "request_headers": {
                        "X-Webhook-Token": settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET or ""
                   }
                }
            }
        ],
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
            "client": {
                "overrides": {
                    "agent": {
                        "first_message": True,
                        "language": True, 
                        "prompt": {
                            "prompt": True,
                        },
                    },
                    "tts": {
                        "voice_id": True,
                    }
                }
            }
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
    webhook_id = await _get_or_create_post_call_webhook(client)
    
    payload = _build_agent_create_payload(
        name=_apply_env_suffix(name) if name else None,
        voice_id=voice_id,
        prompt_text=prompt_text,
        language=language,
        llm=llm,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    
    if webhook_id:
        payload["platform_settings"] = {
            "post_call_webhook_ids": [webhook_id],
        }

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
            client = await get_elevenlabs_client()
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
            except Exception as exc:  
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
        except Exception as exc: 
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
        except Exception as exc:  
            log.warning(
                "background.update_call_record_failed conv=%s err=%s",
                conversation_id,
                exc,
            )

        if chat_id and normalized_transcript:
            try:
                from app.agents.turn_handler import extract_and_store_facts_for_turn
                user_messages = [t.get("message") or t.get("text") or "" for t in normalized_transcript 
                                 if (t.get("role") or "").lower() in ("user", "human")]
                last_user_msg = user_messages[-1] if user_messages else ""
                ctx_lines = [f"{t.get('role', 'unknown')}: {t.get('message') or t.get('text') or ''}" 
                             for t in normalized_transcript]
                recent_ctx = "\n".join(ctx_lines)
                
                if last_user_msg:
                    asyncio.create_task(
                        extract_and_store_facts_for_turn(
                            message=last_user_msg,
                            recent_ctx=recent_ctx,
                            chat_id=chat_id,
                            cid=conversation_id,
                        )
                    )
                    log.info(
                        "background.fact_extraction_scheduled conv=%s chat=%s",
                        conversation_id,
                        chat_id,
                    )
            except Exception as exc:
                log.warning(
                    "background.fact_extraction_schedule_failed conv=%s err=%s",
                    conversation_id,
                    exc,
                )


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
    # No fallback - voice must be explicitly provided or created
    resolved_voice_id = voice_id

    log.debug(
        "ElevenLabs sync start agent=%s influencer=%s voice=%s has_prompt=%s",
        agent_id,
        agent_name,
        resolved_voice_id,
        bool(prompt_text),
    )

    client = await get_elevenlabs_client()
    if agent_id:
        try:
            log.info("Patching existing ElevenLabs agent %s", agent_id)
            await _patch_agent_config(
                client,
                agent_id=agent_id,
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
    except Exception as exc: 
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
    chat = await db.get(Chat, chat_id)
    user_id = chat.user_id if chat else None
    resolved_influencer_id = influencer_id or (chat.influencer_id if chat else None)
    if not chat: 
        log.warning(
            log.warning(
                "_persist_transcript.chat_not_found conv=%s chat=%s",
                conversation_id,
                chat_id,
            )
        )
    moderation_enabled =  bool(user_id and resolved_influencer_id)
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
    context_lines: List[str] = []
    new_messages: List[Message] = []
    seen: set[tuple[str, str]] = set()

    def _is_dup(sender: str, text: str) -> bool:
        if (sender, text) in seen:
            return True
        for msg in recent:
            if msg.sender == sender and (msg.content or "").strip() == text:
                return True
        return False

    # PHASE 1: Collect all message data without embedding
    pending_entries: List[Dict[str, Any]] = []
    
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
        if moderation_enabled and sender == "user":
            context = "\n".join(context_lines[-6:]) if context_lines else ""
            try: 
                mod_result = await moderate_message(text, context, db)
                if mod_result.action == "FLAG":
                    await handle_violation(
                        db=db,
                        user_id=user_id,
                        chat_id=chat_id,
                        influencer_id=resolved_influencer_id,
                        message=text,
                        context=context,
                        result=mod_result,
                    )
                    log.logging.warning(
                        "persist_transcript.violation chat=%s conv=%s msg=%s",
                        chat_id,
                        conversation_id,
                        text,
                    )
            except Exception as exc:
                log.exception(
                    "presist_transcript.moderation_failed chat=%s conv=%s err=%s",
                    chat_id,
                    conversation_id,
                    exc,
                )
        t_secs = entry.get("time_in_call_secs")
        created_at = (
            base_dt + timedelta(seconds=float(t_secs))
            if isinstance(t_secs, (int, float))
            else datetime.utcnow()
        )

        seen.add((sender, text))
        pending_entries.append({
            "sender": sender,
            "text": text,
            "created_at": created_at,
        })
        speaker = "User" if sender == "user" else "AI"
        context_lines.append(f"{speaker}: {text}")

    if not pending_entries:
        return 0

    # PHASE 2: Batch embed all texts in ONE API call (70-80% faster)
    texts_to_embed = [e["text"] for e in pending_entries]
    embeddings: List[Optional[List[float]]] = []
    try:
        from app.services.embeddings import get_embeddings_batch
        embeddings = await get_embeddings_batch(texts_to_embed)
    except Exception as exc:
        log.warning("persist_transcript.batch_embed_failed chat=%s err=%s", chat_id, exc)
        embeddings = [None] * len(pending_entries)

    # PHASE 3: Create Message objects with embeddings
    for i, entry in enumerate(pending_entries):
        embedding = embeddings[i] if i < len(embeddings) else None
        new_messages.append(
            Message(
                chat_id=chat_id,
                sender=entry["sender"],
                channel="call",
                content=entry["text"],
                created_at=entry["created_at"],
                embedding=embedding,
                conversation_id=conversation_id,
            )
        )

    if not new_messages:
        return 0

    db.add_all(new_messages)
    await db.commit()
    try:
        history = redis_history(chat_id)
        for msg in new_messages:
            if msg.sender == "user":
                history.add_user_message(msg.content)
            else:
                history.add_ai_message(msg.content)
        try:
            max_len = settings.MAX_HISTORY_WINDOW
            if max_len and len(history.messages) > max_len:
                trimmed = history.messages[-max_len:]
                history.clear()
                history.add_messages(trimmed)
        except Exception:
            pass
    except Exception as exc: 
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    first_message: Optional[str] = Query(None),
    greeting_mode: str = Query("random", pattern="^(random|rr)$"),
):
    user_id = current_user.id
    ok, cost_cents, free_left = await can_afford(
        db, user_id=user_id, influencer_id=influencer_id, feature="live_chat", units=10
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
    
    credits_remainder_secs = await get_remaining_units(db, user_id,influencer_id, feature="live_chat")

    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    chat_id = await get_or_create_chat(db, user_id, influencer_id)

    greeting: Optional[str] = first_message
    if not greeting:
        greeting = await _generate_contextual_greeting(db, chat_id, influencer_id)
    if not greeting:
        greeting = _pick_greeting(influencer_id, greeting_mode)

    client = await get_elevenlabs_client()
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
    user_timezone: str = Query("UTC"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.id
    ok, cost_cents, free_left = await can_afford(
        db, user_id=user_id, influencer_id=influencer_id, feature="live_chat", units=10
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
    
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    # Sequential to avoid SQLAlchemy AsyncSession concurrent access issue
    prompt_template = await get_global_prompt(db, True)
    influencer = await db.get(Influencer, influencer_id)
    chat_id = await get_or_create_chat(db, user_id, influencer_id)

    if not influencer:
        raise HTTPException(404, "Influencer not found")
    
    bio = influencer.bio_json or {}
    persona_likes = bio.get("likes", [])
    persona_dislikes = bio.get("dislikes", [])
    if not isinstance(persona_likes, list):
        persona_likes = []
    if not isinstance(persona_dislikes, list):
        persona_dislikes = []
    
    # Get stage prompts from DB, with potential bio_json override
    stages = await get_relationship_stage_prompts(db)
    bio_stages = bio.get("stages", {})
    if isinstance(bio_stages, dict) and bio_stages:
        for key, val in bio_stages.items():
            if val:  # Only override if value is non-empty
                stages[key.upper()] = val
    personality_rules = bio.get("personality_rules", "")
    tone = bio.get("tone", "")
    mbti_archetype = bio.get("mbti_architype", "")
    mbti_addon = bio.get("mbti_rules", "")
    mbti_rules = await get_mbti_rules_for_archetype(db, mbti_archetype, mbti_addon)
    daily_context = ""

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])

    now = datetime.now(timezone.utc)
    rel = await get_or_create_relationship(db, int(user_id), influencer_id)
    days_idle = apply_inactivity_decay(rel, now)

    can_ask = (
        rel.state == "DATING"
        and rel.safety >= 70
        and rel.trust >= 75
        and rel.closeness >= 70
        and rel.attraction >= 65
    )

    dtr_goal = plan_dtr_goal(rel, can_ask)
    time_context = get_time_context(user_timezone)

    users_name = await _build_user_name_block(db, user_id)

    prompt = build_relationship_prompt(
        prompt_template,
        rel=rel,
        days_idle=days_idle,
        dtr_goal=dtr_goal,
        personality_rules=personality_rules,
        stages=stages,
        persona_likes=persona_likes,
        persona_dislikes=persona_dislikes,
        mbti_rules=mbti_rules,
        memories="None",
        daily_context=daily_context,
        last_user_message=recent_ctx,
        mood=time_context,
        tone=tone,
        influencer_name=influencer.display_name,
        users_name=users_name,
    )
    
    log_prompt(log, prompt, cid="", input="")

    try:
        client = await get_elevenlabs_client()
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
    
    # chat_id already obtained at line 1350 - removed duplicate call
    credits_remainder_secs = await get_remaining_units(db, user_id, influencer_id, feature="live_chat")

    greeting: Optional[str] = await _generate_contextual_greeting(db, chat_id, influencer_id)
    
    if not greeting:
        greeting = _pick_greeting(influencer_id, "random")

    return {
        "token": token, 
        "agent_id": agent_id, 
        "credits_remainder_secs": credits_remainder_secs, 
        "greeting_used": greeting,
        "prompt": prompt.format(input=""),
        "voice_id": influencer.voice_id or DEFAULT_ELEVENLABS_VOICE_ID,
        "native_language": influencer.native_language if influencer else "en",
    }

@router.get("/signed-url-free")
async def get_signed_url_free(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    greeting = None

    client = await get_elevenlabs_client()
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

    client = await get_elevenlabs_client()
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
        except Exception as exc:  
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    chat_id = await save_pending_conversation(
        db, conversation_id, current_user.id, body.influencer_id, body.sid
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # OPTIMIZATION: Quick status check (max 5 seconds) instead of blocking for minutes
    client = await get_elevenlabs_client()
    try:
        snapshot = await _wait_until_terminal_status(
            client,
            conversation_id,
            max_wait_secs=5,  # Quick check only
        )
        snapshot = await _ensure_transcript_snapshot(client, conversation_id, snapshot)
        status = (snapshot.get("status") or "").lower()
    except Exception as exc:
        log.warning("finalize.quick_check_failed conv=%s err=%s", conversation_id, exc)
        status = "processing"
        snapshot = {}
    
    # If not done yet, schedule background processing and return immediately
    if status not in {"done", "failed"}:
        log.info("finalize.scheduling_background_poll conv=%s status=%s", conversation_id, status)
        
        # Look up chat_id for background task
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
                influencer_id_from_db = row[1]
                if not body.influencer_id and influencer_id_from_db:
                    body.influencer_id = influencer_id_from_db
        except Exception:
            pass
        
        # Schedule background processing
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
            log.warning("finalize.background_schedule_failed conv=%s err=%s", conversation_id, exc)
        
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "status": "processing",
            "charged": False,
            "message": "Conversation still processing. Polling in background. Check status via GET /elevenlabs/calls/{conversation_id}",
            "refresh_required": False,
        }
    
    # Conversation is done or failed - process immediately
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
        
        chat_id = meta.get("chat_id") if isinstance(meta, dict) else None
        if not chat_id:
            raise HTTPException(400, "Missing chat_id in meta for billing")

        influencer_id = await _get_influencer_id_from_chat(db, chat_id)

        await charge_feature(
            db,
            user_id=body.user_id,
            influencer_id=influencer_id,
            feature="live_chat",
            units=math.ceil(total_seconds),
            meta=meta,
        )
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

def _parse_labels(labels_json: str | None) -> str | None:

    if not labels_json:
        return None
    try:
        obj = json.loads(labels_json)
        if not isinstance(obj, dict):
            raise ValueError("labels_json must be a JSON object")
        return json.dumps(obj)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid labels_json: {e}")


async def _elevenlabs_create_voice(
    *,
    name: str,
    description: str | None,
    labels_str: str | None,
    remove_background_noise: bool,
    multipart_files: list[tuple[str, tuple[str, bytes, str]]],
) -> dict:
    data = {
        "name": _apply_env_suffix(name),
        "remove_background_noise": "true" if remove_background_noise else "false",
    }
    if description is not None:
        data["description"] = description
    if labels_str is not None:
        data["labels"] = labels_str

    client = await get_elevenlabs_client()
    r = await client.post(
        "/voices/add",
        headers=_headers(),
        data=data,
        files=multipart_files,
        timeout=60.0,
    )

    if r.status_code >= 400:
        log.error("ElevenLabs /v1/voices/add failed: %s %s", r.status_code, r.text[:1500])
        raise HTTPException(status_code=r.status_code, detail=r.text)

    payload = r.json() or {}
    if not payload.get("voice_id"):
        raise HTTPException(status_code=502, detail="ElevenLabs returned no voice_id")

    return payload


@router.post("/voices/add")
async def eleven_create_voice_clone(
    pre_influencer_id: int = Form(...),
    name: str = Form(...),
    description: str | None = Form(None),
    labels_json: str | None = Form(None),
    remove_background_noise: bool = Form(False),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    pre = await db.get(PreInfluencer, pre_influencer_id)
    if not pre:
        raise HTTPException(status_code=404, detail="PreInfluencer not found")

    if not files:
        raise HTTPException(status_code=400, detail="At least 1 audio file is required")

    labels_str = _parse_labels(labels_json)

    multipart_files: list[tuple[str, tuple[str, bytes, str]]] = []
    for f in files:
        b = await f.read()
        if not b:
            raise HTTPException(status_code=400, detail=f"Empty file: {f.filename}")
        ctype = f.content_type or "audio/mpeg"
        multipart_files.append(
            ("files", (f.filename or "sample.mp3", b, ctype))
        )

    payload = await _elevenlabs_create_voice(
        name=name,
        description=description,
        labels_str=labels_str,
        remove_background_noise=remove_background_noise,
        multipart_files=multipart_files,
    )

    pre.voice_id = payload["voice_id"]
    db.add(pre)
    await db.commit()
    await db.refresh(pre)

    return {
        "ok": True,
        "source": "upload",
        "pre_influencer_id": pre.id,
        "voice_id": payload["voice_id"],
        "requires_verification": payload.get("requires_verification", False),
    }

@router.post("/update-prompt")
async def update_elevenlabs_prompt(
    body: UpdatePromptBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    auto_commit: bool = Depends(_default_auto_commit),
):
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    call = await db.get(CallRecord, conversation_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if call.user_id != current_user.id:
        raise HTTPException(403, "Forbidden")

    transcript = call.transcript or []
    duration = call.call_duration_secs
    status = call.status
    agent_id = None

    if not transcript or duration is None:
        client = await get_elevenlabs_client()
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
