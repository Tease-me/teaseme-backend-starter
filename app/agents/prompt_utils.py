import json
import random
from datetime import date, datetime, timezone
from typing import Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Influencer
from fastapi import Depends, HTTPException
from app.db.session import get_db
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

import logging
log = logging.getLogger("teaseme-script")



_mbti_cache: Optional[dict] = None
_stage_prompts_cache: Optional[dict] = None


async def get_relationship_stage_prompts(db: AsyncSession) -> dict:
    """
    Fetches relationship stage prompts from the database and returns them as a dict.
    The prompts are cached after the first fetch.
    Returns a dict mapping relationship state (uppercase) to prompt string.
    """
    global _stage_prompts_cache
    
    if _stage_prompts_cache is not None:
        return _stage_prompts_cache
    
    stage_json_str = await get_system_prompt(db, prompt_keys.RELATIONSHIP_STAGE_PROMPTS)
    if stage_json_str:
        try:
            raw = json.loads(stage_json_str)
            _stage_prompts_cache = {}
            for key, value in raw.items():
                if isinstance(value, list):
                    _stage_prompts_cache[key.upper()] = "\n".join(str(v) for v in value)
                else:
                    _stage_prompts_cache[key.upper()] = str(value)
        except json.JSONDecodeError as exc:
            log.warning("Failed to parse RELATIONSHIP_STAGE_PROMPTS: %s", exc)
            _stage_prompts_cache = {}
    else:
        log.warning("RELATIONSHIP_STAGE_PROMPTS system prompt not found")
        _stage_prompts_cache = {}
    
    return _stage_prompts_cache


async def get_mbti_rules_for_archetype(
    db: AsyncSession,
    mbti_archetype: str,
    mbti_addon: str = "",
) -> str:
    global _mbti_cache
    
    if not mbti_archetype:
        return mbti_addon.strip() if mbti_addon else ""
    
    if _mbti_cache is None:
        mbti_json_str = await get_system_prompt(db, "MBTI_JSON")
        if mbti_json_str:
            try:
                _mbti_cache = json.loads(mbti_json_str)
            except json.JSONDecodeError as exc:
                log.warning("Failed to parse MBTI_JSON: %s", exc)
                _mbti_cache = {}
        else:
            log.warning("MBTI_JSON system prompt not found")
            _mbti_cache = {}
    
    base_rules = ""
    personalities = _mbti_cache.get("personalities", [])
    archetype_upper = mbti_archetype.strip().upper()
    
    for personality in personalities:
        if personality.get("code", "").upper() == archetype_upper:
            name = personality.get("name", "")
            rules_list = personality.get("rules", [])
            if rules_list:
                rules_str = "\n".join(f"- {rule}" for rule in rules_list)
                base_rules = f"**{archetype_upper} - {name}**\n{rules_str}"
            break
    
    parts = []
    if base_rules:
        parts.append(base_rules)
    if mbti_addon and mbti_addon.strip():
        parts.append(f"\n**Additional personality notes:**\n{mbti_addon.strip()}")
    
    return "\n".join(parts)

async def get_base_system(db: AsyncSession, isAudio: bool) -> str:
    base = await get_system_prompt(db, prompt_keys.BASE_SYSTEM)
    if isAudio: 
        audio_base = await get_system_prompt(db, prompt_keys.BASE_AUDIO_SYSTEM)
        base += "\n" + audio_base
    return base

async def get_global_prompt(
    db: AsyncSession,
    isAudio: bool = False,
) -> ChatPromptTemplate:
    system_prompt = await get_base_system(db, isAudio=isAudio)

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder("history"),
            ("user", "{input}"),
        ]
    )


def build_relationship_prompt(
    prompt_template: ChatPromptTemplate,
    rel,
    days_idle: float,
    dtr_goal: str,
    personality_rules: str = "",
    stages: dict | None = None,
    persona_likes: list[str] | None = None,
    persona_dislikes: list[str] | None = None,
    mbti_rules: str = "",
    memories: str = "",
    daily_context: str = "",
    last_user_message: str = "",
    tone: str = "",
    mood: str = "",
    analysis: str | None = None,
    influencer_name: str = "",
):
    stages = stages or {}
    rel_state = (getattr(rel, "state", "") or "").strip().upper()
    stage_prompt = ""

    if stages:
        # Try uppercase key first (DB format), then lowercase (bio_json format)
        stage_prompt = stages.get(rel_state, "") or stages.get(rel_state.lower(), "")

    partial_vars = {
        "relationship_state": rel.state,
        "influencer_name": influencer_name,
        "stage_prompt": stage_prompt,
        "trust": int(rel.trust or 0),
        "closeness": int(rel.closeness or 0),
        "attraction": int(rel.attraction or 0),
        "safety": int(rel.safety or 0),
        "exclusive_agreed": bool(rel.exclusive_agreed),
        "girlfriend_confirmed": bool(rel.girlfriend_confirmed),
        "days_idle_before_message": round(float(days_idle or 0.0), 1),
        "dtr_goal": dtr_goal,
        "personality_rules": personality_rules,
        "likes": ", ".join(map(str, persona_likes or [])),
        "dislikes": ", ".join(map(str, persona_dislikes or [])),
        "mbti_rules": mbti_rules,
        "memories": memories,
        "daily_context": daily_context,
        "last_user_message": last_user_message,
        "tone": tone,
        "mood": mood,
    }
    
    if analysis is not None:
        partial_vars["analysis"] = analysis

    expected = set(getattr(prompt_template, "input_variables", []) or [])
    filtered = {k: v for k, v in partial_vars.items() if k in expected}
    return prompt_template.partial(**filtered)

# ── stage-aware daily-script selection ────────────────────────────
_ALL_TIERS = ["universal", "talking", "flirting", "dating"]

_STAGE_UNLOCK: dict[str, list[str]] = {
    "HATE": [],
    "DISLIKE": [],
    "STRANGER": ["universal"],
    "STRANGERS": ["universal"],
    "TALKING": ["universal", "talking"],
    "FRIENDS": ["universal", "talking"],
    "FLIRTING": ["universal", "talking", "flirting"],
    "DATING": _ALL_TIERS,
    "IN LOVE": _ALL_TIERS,
    "GIRLFRIEND": _ALL_TIERS,
}


def pick_daily_script(
    daily_scripts,
    rel_state: str = "STRANGERS",
    chat_id: str = "",
) -> str:
    """Select a stage-appropriate daily script.

    Accepts either new dict format ``{"universal": [...], ...}``
    or legacy flat ``[...]``.  Returns "" when nothing is eligible.
    """
    import hashlib

    if not daily_scripts:
        return ""

    # ── collect eligible scripts ──────────────────────────────────
    state_upper = (rel_state or "STRANGERS").strip().upper()
    allowed_tiers = _STAGE_UNLOCK.get(state_upper, ["universal"])

    if isinstance(daily_scripts, dict):
        pool: list[str] = []
        for tier in allowed_tiers:
            pool.extend(daily_scripts.get(tier, []))
    elif isinstance(daily_scripts, list):
        # legacy flat list – treat everything as universal
        pool = list(daily_scripts)
    else:
        return ""

    if not pool:
        return ""

    # ── deterministic but daily-rotating pick ─────────────────────
    seed = hashlib.md5(f"{date.today().isoformat()}:{chat_id}".encode()).hexdigest()
    rng = random.Random(seed)
    return rng.choice(pool)


async def get_today_script(
    db: AsyncSession = Depends(get_db),
    influencer_id: str = None,
) -> str:
    if not influencer_id:
        raise HTTPException(400, "influencer_id is required")
    influencer = await db.get(Influencer, influencer_id)
    scripts = influencer.daily_scripts if influencer and influencer.daily_scripts else []
    if not scripts:
        return ""
    return pick_daily_script(scripts)


# ── unified inner-state brief ────────────────────────────────────

def build_inner_state(
    *,
    mood: str = "",
    daily_topic: str = "",
    trending: str = "",
    pref_ctx: str = "",
) -> str:
    """Assemble a structured 'Inner State' brief from separate context pieces.

    Each non-empty piece gets a labeled section.  The overall block includes
    a "pick at most one" guardrail so the LLM doesn't force all of them
    into a single reply.
    """
    sections: list[str] = []

    if mood:
        sections.append(f"MOOD: {mood}")

    if daily_topic:
        sections.append(f"WHAT'S ON YOUR MIND: {daily_topic}")

    if trending:
        sections.append(f"SOMETHING YOU SAW ON YOUR PHONE: {trending}")

    if pref_ctx:
        sections.append(f"SHARED INTERESTS WITH THE USER: {pref_ctx}")

    if not sections:
        return ""

    body = "\n\n".join(sections)

    return (
        "\u2501\u2501\u2501 YOUR INNER STATE TODAY \u2501\u2501\u2501\n\n"
        f"{body}\n\n"
        "RULES: Pick AT MOST ONE of these to weave in naturally. "
        "Do NOT force any of them. "
        "If nothing fits the conversation, ignore all of this.\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    )


