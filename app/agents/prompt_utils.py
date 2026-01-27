import json
from typing import Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Influencer
from datetime import date
from fastapi import Depends, HTTPException
from app.db.session import get_db
from app.services.system_prompt_service import get_system_prompt

import logging
log = logging.getLogger("teaseme-script")


_mbti_cache: Optional[dict] = None


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
    base = await get_system_prompt(db, "BASE_SYSTEM")
    if isAudio: 
        audio_base = await get_system_prompt(db, "BASE_AUDIO_SYSTEM")
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
            (
                "system",
                "Today’s inspiration for you (use ONLY if it fits the current conversation, otherwise ignore): {daily_context}"
            ),
            (
                "system",
                "These past memories may help:\n{memories}\n"
                "If you see the user’s preferred name here, use it *occasionally and naturally, only when it fits the conversation or for affection*. Don’t overuse the name.\n"
                "Here is the user’s latest message for your reference only:\n"
                "\"{last_user_message}\"\n"
                "If the user changed topic, you do NOT need to talk about this. Use only if it makes the reply feel natural."
            ),
            MessagesPlaceholder("history"),
            ("user", "{input}"),
        ]
    )

def build_relationship_prompt(
    prompt_template: ChatPromptTemplate,
    *,
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
    persona_rules: str | None = None,
    analysis: str | None = None,
):
    stages = stages or {}

    partial_vars = {
        "relationship_state": rel.state,
        "trust": int(rel.trust or 0),
        "closeness": int(rel.closeness or 0),
        "attraction": int(rel.attraction or 0),
        "safety": int(rel.safety or 0),
        "exclusive_agreed": bool(rel.exclusive_agreed),
        "girlfriend_confirmed": bool(rel.girlfriend_confirmed),
        "days_idle_before_message": round(float(days_idle or 0.0), 1),
        "dtr_goal": dtr_goal,
        "personality_rules": personality_rules,
        "dating_stage": stages.get("dating", ""),
        "dislike_stage": stages.get("dislike", ""),
        "talking_stage": stages.get("talking", ""),
        "flirting_stage": stages.get("flirting", ""),
        "hate_stage": stages.get("hate", ""),
        "strangers_stage": stages.get("strangers", ""),
        "in_love_stage": stages.get("in_love", ""),
        "likes": ", ".join(map(str, persona_likes or [])),
        "dislikes": ", ".join(map(str, persona_dislikes or [])),
        "mbti_rules": mbti_rules,
        "memories": memories,
        "daily_context": daily_context,
        "last_user_message": last_user_message,
        "tone": tone,
    }

    if persona_rules is not None:
        partial_vars["persona_rules"] = persona_rules
    if analysis is not None:
        partial_vars["analysis"] = analysis

    expected = set(getattr(prompt_template, "input_variables", []) or [])
    filtered = {k: v for k, v in partial_vars.items() if k in expected}
    return prompt_template.partial(**filtered)

async def get_today_script(
    db: AsyncSession = Depends(get_db),
    influencer_id: str = None
) -> str:
    if not influencer_id:
        raise HTTPException(400, "influencer_id is required")
    influencer = await db.get(Influencer, influencer_id)
    scripts = influencer.daily_scripts if influencer and influencer.daily_scripts else []
    if not scripts:
        return ""
    idx = date.today().timetuple().tm_yday % len(scripts)
    frase = scripts[idx]
    return frase

