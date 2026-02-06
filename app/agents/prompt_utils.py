import json
import random
import re
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

_TIME_RANGE_RE = re.compile(r"^\s*(\d{1,2})\s*(AM|PM)\s*-\s*(\d{1,2})\s*(AM|PM)\s*$", re.IGNORECASE)


def _resolve_tz(tz_name: str | None):
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _is_weekend(user_timezone: str | None) -> bool:
    tz = _resolve_tz(user_timezone)
    now = datetime.now(tz)
    return now.weekday() >= 5 


def _hour_from_12h(hour: int, meridiem: str) -> int:
    hour = hour % 12
    if meridiem.upper() == "PM":
        hour += 12
    return hour


def _range_span(start: int, end: int) -> int:
    if start <= end:
        return end - start + 1
    return (24 - start) + (end + 1)


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _parse_time_range(label: str):
    m = _TIME_RANGE_RE.match(label or "")
    if not m:
        return None
    start_raw, start_ampm, end_raw, end_ampm = m.groups()
    start = _hour_from_12h(int(start_raw), start_ampm)
    end = _hour_from_12h(int(end_raw), end_ampm)
    return (start, end)


def pick_time_mood(
    weekday_prompt: str | None,
    weekend_prompt: str | None,
    user_timezone: str | None,
) -> str:
    is_weekend = _is_weekend(user_timezone)
    time_prompt = weekend_prompt if is_weekend else weekday_prompt

    if not time_prompt:
        return ""
    try:
        mood_map = json.loads(time_prompt)
    except json.JSONDecodeError:
        log.warning("Invalid TIME_PROMPT JSON; using empty mood")
        return ""
    if not isinstance(mood_map, dict):
        return ""

    hour = datetime.now(_resolve_tz(user_timezone)).hour

    matches: list[tuple[int, list[str]]] = []
    for label, options in mood_map.items():
        if not isinstance(options, list) or not options:
            continue
        parsed = _parse_time_range(label)
        if not parsed:
            continue
        start, end = parsed
        if _hour_in_range(hour, start, end):
            matches.append((_range_span(start, end), options))

    if matches:
        matches.sort(key=lambda item: item[0])
        return random.choice(matches[0][1])

    flat = [m for opts in mood_map.values() if isinstance(opts, list) for m in opts]
    return random.choice(flat) if flat else ""


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
        if rel_state == "HATE":
            stage_prompt = stages.get("hate", "")
        elif rel_state == "DISLIKE":
            stage_prompt = stages.get("dislike", "")
        elif rel_state == "STRANGERS":
            stage_prompt = stages.get("strangers", "")
        elif rel_state == "FRIENDS":
            stage_prompt = stages.get("friends", "")
        elif rel_state == "FLIRTING":
            stage_prompt = stages.get("flirting", "")
        elif rel_state == "DATING":
            stage_prompt = stages.get("dating", "")
        elif rel_state == "GIRLFRIEND":
            stage_prompt = stages.get("girlfriend", "")
        else:
            stage_prompt = stages.get(rel_state.lower(), "")

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
