# app/api/elevenlabs.py
from fastapi import APIRouter, HTTPException, Depends, Query
import httpx
from typing import Dict, List, Optional
import random
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Influencer
from app.core.config import settings

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])
log = logging.getLogger(__name__)

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"

# Temporary in-memory greetings (no DB)
_GREETINGS: Dict[str, List[str]] = {
    "loli": [
        "Mmm… I’ve been waiting for you. Ready to tease me?",
        "Well, look who showed up. Think you can handle me today?",
        "Hey trouble… I missed you. What’s your excuse?",
        "Hey there, you! Did you miss me?",
    ],
    "anna": [
        "Nyaa~! You’re back! I was just thinking about you!",
        "Ooh! It’s you! Did you bring me something cute?",
        "UwU~ guess who’s my favorite human?",
    ],
    "bella": [
        "Hi love… you’ve been on my mind all day.",
        "Hey darling, I was hoping you’d call.",
        "Mmm… my day just got better.",
    ],
}
_rr_index: Dict[str, int] = {}


def _headers() -> Dict[str, str]:
    if not ELEVENLABS_API_KEY:
        # Fail fast with a clear error if API key is missing
        raise HTTPException(500, "ELEVENLABS_API_KEY is not configured.")
    return {"xi-api-key": ELEVENLABS_API_KEY}


def _pick_greeting(influencer_id: str, mode: str) -> str:
    """Pick a greeting: random or round-robin for that influencer id."""
    options = _GREETINGS.get(influencer_id)
    if not options:
        # Flatten all as fallback
        all_opts = sum(_GREETINGS.values(), [])
        return random.choice(all_opts) if all_opts else "Hey there."
    if mode == "rr":
        i = _rr_index.get(influencer_id, -1) + 1
        i %= len(options)
        _rr_index[influencer_id] = i
        return options[i]
    return random.choice(options)


async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str) -> str:
    """
    Public helper (kept without underscore in case you call it from elsewhere).
    Looks up the ElevenLabs agent id stored on the Influencer row.
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
) -> Dict:
    """
    Build a PATCH payload for ElevenLabs agent updates.
    Only include the fields you actually want to update.
    """
    agent_cfg: Dict = {}
    if first_message is not None:
        agent_cfg["first_message"] = first_message

    if any(v is not None for v in (prompt_text, llm, temperature, max_tokens)):
        prompt_block: Dict = {}
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
    """Send a single PATCH to ElevenLabs with exactly what needs updating."""
    payload = _build_agent_patch_payload(
        agent_id,
        first_message=first_message,
        prompt_text=prompt_text,
        llm=llm,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # If nothing to update, do nothing.
    if not payload["conversation_config"]["agent"]:
        return

    resp = await client.patch(
        f"{ELEVEN_BASE_URL}/convai/agents/{agent_id}",
        headers=_headers(),
        json=payload,
        timeout=20.0,
    )
    if resp.status_code >= 400:
        log.error("ElevenLabs PATCH failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=424,
            detail=f"Failed to update ElevenLabs agent: {resp.status_code} {resp.text}",
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
    Keeps the exact function name you requested.
    """
    async with httpx.AsyncClient(http2=True) as client:
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
    r = await client.get(
        f"{ELEVEN_BASE_URL}/convai/conversation/get-signed-url",
        params={"agent_id": agent_id},
        headers=_headers(),
        timeout=20.0,
    )
    if r.status_code != 200:
        log.error("ElevenLabs signed-url failed: %s %s", r.status_code, r.text)
        raise HTTPException(status_code=400, detail="Failed to get signed url")
    return r.json()["signed_url"]


@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    first_message: Optional[str] = Query(None),
    # "random" or "rr" (round-robin)
    greeting_mode: str = Query("random", regex="^(random|rr)$"),
):
    """
    1) Update the agent's first_message (greeting).
    2) Return a signed_url for the client to open a conversation.
    """
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    greeting = first_message or _pick_greeting(influencer_id, greeting_mode)

    async with httpx.AsyncClient(http2=True) as client:
        # Only update first_message here. (Prompt updates should use _push_prompt_to_elevenlabs elsewhere.)
        await _patch_agent_config(client, agent_id, first_message=greeting)
        signed_url = await _get_conversation_signed_url(client, agent_id)

    return {"signed_url": signed_url, "greeting_used": greeting, "agent_id": agent_id}

'''
from fastapi import APIRouter, HTTPException, Depends, Query
import httpx
from app.db.session import get_db
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from typing import Dict, List, Optional
import random

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY

# --- TEMP in-memory greetings (no DB) ---
_GREETINGS: Dict[str, List[str]] = {
    "loli": [
        "Mmm… I’ve been waiting for you. Ready to tease me?",
        "Well, look who showed up. Think you can handle me today?",
        "Hey trouble… I missed you. What’s your excuse?",
    ],
    "anna": [
        "Nyaa~! You’re back! I was just thinking about you!",
        "Ooh! It’s you! Did you bring me something cute?",
        "UwU~ guess who’s my favorite human?",
    ],
    "bella": [
        "Hi love… you’ve been on my mind all day.",
        "Hey darling, I was hoping you’d call.",
        "Mmm… my day just got better.",
    ],
}
_rr_index: Dict[str, int] = {}

def _pick_greeting(influencer_id: str, mode: str) -> str:
    options = _GREETINGS.get(influencer_id)
    if not options:
        # flatten all as a fallback
        all_opts = sum(_GREETINGS.values(), [])
        return random.choice(all_opts) if all_opts else "Hey there."
    if mode == "rr":
        i = _rr_index.get(influencer_id, -1) + 1
        i %= len(options)
        _rr_index[influencer_id] = i
        return options[i]
    return random.choice(options)

async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str):
    influencer = await db.get(Influencer, influencer_id)
    if influencer and getattr(influencer, "influencer_agent_id_third_part", None):
        return influencer.influencer_agent_id_third_part
    raise HTTPException(404, "Influencer or influencer_agent_id_third_part not found")

async def _push_prompt_to_elevenlabs(agent_id: str, prompt_text: str):
    """
    PATCH the agent on ElevenLabs with the latest prompt (and optional first message).
    """
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    payload = {
        "agent_id": agent_id,
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt_text,
                    # Optionally tune these:
                    # "llm": "gpt-4o-mini",
                    # "temperature": 0.5,
                    # "max_tokens": 512,
                }
            }
        }
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.patch(
            f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=424,
                detail=f"Failed to update ElevenLabs agent: {resp.status_code} {resp.text}",
            )
        
@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    
    first_message: Optional[str] = Query(None),
    # random or rr (round-robin)
    greeting_mode: str = Query("random", regex="^(random|rr)$"),
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    headers = {"xi-api-key": ELEVENLABS_API_KEY}

    greeting = first_message or _pick_greeting(influencer_id, greeting_mode)

    async with httpx.AsyncClient() as client:
        payload = {
            "agent_id": agent_id,
            "conversation_config": {
                "agent": {
                    "first_message": greeting
                }
            }
        }
        patch = await client.patch(
            f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
            headers=headers,
            json=payload,
        )
        if patch.status_code >= 400:
            raise HTTPException(status_code=424, detail=f"Failed to update first message: {patch.text}")

        r = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=headers,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get signed url")
        return {"signed_url": r.json()["signed_url"]}
'''
