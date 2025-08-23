import asyncio
import logging
import random
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from itertools import chain
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.db.models import Influencer
from app.db.session import get_db
from app.schemas.elevenlabs import FinalizeConversationBody, RegisterConversationBody
from app.services.billing import charge_feature
from sqlalchemy import insert, select
from app.db.models import CallRecord 
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.services.billing import can_afford, get_remaining_units

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])
log = logging.getLogger(__name__)

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"

# Temporary in-memory greetings (no DB). Keep the content SFW and generic.
_GREETINGS: Dict[str, List[str]] = {
    "playful": [
        "Hey there! Ready to chat?",
        "Look who’s here—let’s get started.",
        "You’re back! What’s on your mind?",
        "Good to see you again!",
    ],
    "anna": [
        "Nyaa~ welcome back!",
        "Ooh, it’s you! Ready?",
        "UwU—my favorite user just arrived!",
    ],
    "bella": [
        "Hi! I’ve been looking forward to this.",
        "Hey there, I was hoping you’d call.",
        "My day just got better.",
    ],
}
_rr_index: Dict[str, int] = {}


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
        return random.choice(all_opts) if all_opts else "Hello!"
    if mode == "rr":
        i = _rr_index.get(influencer_id, -1) + 1
        i %= len(options)
        _rr_index[influencer_id] = i
        return options[i]
    return random.choice(options)


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
    agent_id: str,
    *,
    first_message: Optional[str] = None,
    prompt_text: Optional[str] = None,
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build a PATCH payload for ElevenLabs agent updates.
    Only include fields you actually want to update.
    """
    agent_cfg: Dict[str, Any] = {}

    if first_message is not None:
        agent_cfg["first_message"] = first_message

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

    return {
        "agent_id": agent_id,
        "conversation_config": {"agent": agent_cfg},
    }


async def _patch_agent_config(
    client: httpx.AsyncClient,
    agent_id: str,
    *,
    first_message: Optional[str] = None,
    prompt_text: Optional[str] = None,
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> None:
    """PATCH /convai/agents/{agent_id} with the minimal update payload."""
    payload = _build_agent_patch_payload(
        agent_id,
        first_message=first_message,
        prompt_text=prompt_text,
        llm=llm,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not payload["conversation_config"]["agent"]:
        return  # nothing to update

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
        # Consider truncating resp.text to avoid logging PII.
        log.error("ElevenLabs PATCH failed: %s %s", resp.status_code, resp.text[:500])
        raise HTTPException(
            status_code=424,
            detail=f"Failed to update ElevenLabs agent: {resp.status_code}",
        )


# === DO NOT RENAME: you said you call this elsewhere ===
async def _push_prompt_to_elevenlabs(
    agent_id: str,
    prompt_text: str,
    first_message: Optional[str] = None,
    *,
    llm: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> None:
    """
    Update the agent's prompt (and optionally first_message) on ElevenLabs.
    """
    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        await _patch_agent_config(
            client,
            agent_id,
            first_message=first_message,
            prompt_text=prompt_text,
            llm=llm,
            temperature=temperature,
            max_tokens=max_tokens,
        )


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


def _extract_total_seconds(conversation_json: Dict[str, Any]) -> int:
    """
    Primary: metadata.call_duration_secs
    Fallback: max transcript[*].time_in_call_secs
    """
    md = conversation_json.get("metadata") or {}
    dur = md.get("call_duration_secs")
    if isinstance(dur, (int, float)) and dur >= 0:
        return int(dur)
    transcript = conversation_json.get("transcript") or []
    try:
        max_sec = (
            max(int(t.get("time_in_call_secs") or 0) for t in transcript) if transcript else 0
        )
    except Exception:
        max_sec = 0
    return max(0, int(max_sec))


@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    user_id: int = Query(..., description="Numeric user id"),
    db: AsyncSession = Depends(get_db),
    first_message: Optional[str] = Query(None),
    # "random" or "rr" (round-robin). Use pattern instead of deprecated regex.
    greeting_mode: str = Query("random", pattern="^(random|rr)$"),
):
    """
    (1) Check user credits before starting a live chat call.
    (2) Optionally update the agent's first_message (greeting).
    (3) Return a signed_url for the client to open a conversation.
    
    NOTE: PATCHing the agent updates it globally.
    If concurrent users need distinct greetings, prefer a per-conversation override.
    """
    # --- Check credits before starting call ---

    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    greeting = first_message or _pick_greeting(influencer_id, greeting_mode)

    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        # Only update first_message here. Prompt updates should use _push_prompt_to_elevenlabs elsewhere.
        await _patch_agent_config(client, agent_id, first_message=greeting)
        signed_url = await _get_conversation_signed_url(client, agent_id)

    return {
        "signed_url": signed_url,
        "greeting_used": greeting,
        "agent_id": agent_id,
    }

@router.get("/signed-url_test")
async def get_signed_url_test(
    influencer_id: str,
    user_id: int = Query(..., description="Numeric user id"),
    db: AsyncSession = Depends(get_db),
    first_message: Optional[str] = Query(None),
    greeting_mode: str = Query("random", pattern="^(random|rr)$"),
):
    """
    (1) Check user credits before starting a live chat call.
    (2) Optionally update the agent's first_message (greeting).
    (3) Return a signed_url for the client to open a conversation.

    NOTE: PATCHing the agent updates it globally.
    """
    # --- Check credits before starting call ---
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

    # --- Resolve agent + greeting ---
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    greeting = first_message or _pick_greeting(influencer_id, greeting_mode)

    # --- Concrete per-call meta for the webhook tool ---
    chat_id = f"{user_id}_{influencer_id}"
    PUBLIC_BASE = settings.PUBLIC_BASE_URL
    WEBHOOK_SECRET = settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET
    if not PUBLIC_BASE:
        raise HTTPException(500, "PUBLIC_BASE_URL is not configured")

    tool_def = {
        "name": "reply_with_backend",
        "type": "webhook",
        "api_schema": {
            "url": f"{PUBLIC_BASE}/webhooks/reply",
            "method": "POST",
            "request_headers": { "X-Webhook-Token": WEBHOOK_SECRET or "" }
        },
    }

    # Força o agente a usar o tool a cada turno
    agent_rules = {
        "prompt": {
            "prompt": "For every user turn, always call the tool `reply_with_backend`. Do not compose responses yourself."
        }
    }

    # PATCH payload: mantém first_message + tools + client_events
    patch_payload = {
        "agent_id": agent_id,
        "conversation_config": {
            "agent": {
                "first_message": greeting,   # (global)
                **agent_rules,
                "tools": [tool_def],
            },
            "conversation": {
                "client_events": ["conversation_initiation_metadata"],
                 "client_data": {
                    "chat_id": '3f1c3f2d-cf3d-43cf-b8c6-e0cfe5b0b669',
                    "user_id": 1,
                    "influencer_id": 'bella'
                }
            }
        }
    }

    # HTTP/2 fallback se h2 não estiver instalado
    try:
        import h2  # noqa: F401
        _http2 = True
    except Exception:
        _http2 = False

    async with httpx.AsyncClient(http2=_http2, base_url=ELEVEN_BASE_URL, timeout=20.0) as client:
        # PATCH com greeting + tool + client_events
        patch = await client.patch(
            f"/convai/agents/{agent_id}",
            headers=_headers(),
            json=patch_payload,
        )
        if patch.status_code >= 400:
            log.error("ElevenLabs PATCH failed: %s %s", patch.status_code, patch.text[:500])
            raise HTTPException(status_code=424, detail="Failed to update agent config")

        # GET signed URL
        r = await client.get(
            "/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=_headers(),
        )
        if r.status_code != 200:
            log.error("signed-url failed: %s %s", r.status_code, r.text[:500])
            raise HTTPException(status_code=400, detail="Failed to get signed url")
        signed_url = r.json()["signed_url"]

    return {
        "signed_url": signed_url,
        "greeting_used": greeting,
        "agent_id": agent_id,
        "credits_remainder_secs": credits_remainder_secs,
    }


# ---------- Persistence hooks (stubs) ----------

async def save_pending_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: int,
    influencer_id: Optional[str],
    sid: Optional[str],
) -> None:
    """
    Upsert a pending conversation mapping (PostgreSQL).
    Idempotent on the primary key (conversation_id).
    """
    stmt = (
        pg_insert(CallRecord)
        .values(
            conversation_id=conversation_id,
            user_id=user_id,
            influencer_id=influencer_id,
            sid=sid,
            status="pending",
        )
        # Use the PK or a unique constraint name here
        .on_conflict_do_update(
            index_elements=[CallRecord.conversation_id],
            set_={
                "user_id": user_id,
                "influencer_id": influencer_id,
                "sid": sid,
                "status": "pending",
            },
        )
    )
    await db.execute(stmt)
    await db.commit()


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
    """
    Call this right after startSession resolves a conversationId.
    It lets the server bill even if the client goes offline later (webhook path).
    """
    await save_pending_conversation(db, conversation_id, body.user_id, body.influencer_id, body.sid)
    return {"ok": True, "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/finalize")
async def finalize_conversation(
    conversation_id: str,
    body: FinalizeConversationBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Client-side finalize (optional if you rely on webhooks for billing).
    - Polls ElevenLabs until terminal status.
    - Extracts total_seconds.
    - Bills if (status == "done") AND (body.charge_if_not_billed is True) AND (not already billed).
    Returns a UI-friendly summary either way.
    """
    async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
        snapshot = await _wait_until_terminal_status(
            client,
            conversation_id,
            max_wait_secs=max(10, int(body.timeout_secs or 180)),
        )

    status = (snapshot.get("status") or "").lower()
    total_seconds = _extract_total_seconds(snapshot)

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
    if body.influencer_id:
        meta["influencer_id"] = body.influencer_id

    if status == "failed":
        log.warning("Conversation %s ended as FAILED; skipping charge.", conversation_id)
        return {
            "ok": False,
            "reason": "failed",
            "conversation_id": conversation_id,
            "status": status,
            "total_seconds": total_seconds,
            "meta": meta,
        }

    # If not yet done, return status only (no billing).
    if status != "done":
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "status": status,
            "charged": False,
            "total_seconds": total_seconds,
            "meta": meta,
            "note": "Conversation not done yet; waiting for webhook or try again later.",
        }

    # Idempotency: bill only if not already billed AND caller explicitly asked to bill here.
    if body.charge_if_not_billed and not await was_already_billed(db, conversation_id):
        charge_feature(db, body.user_id, "live_chat", int(total_seconds), meta=meta)
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "status": status,
            "charged": True,
            "total_seconds": total_seconds,
            "meta": meta,
        }

    # Default path (webhook will bill; this is UI-only)
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": status,
        "charged": False,
        "total_seconds": total_seconds,
        "meta": meta,
    }

