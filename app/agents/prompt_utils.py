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


def get_time_context(user_timezone: str | None) -> str:
    """
    Generate simple time context for AI to naturally incorporate.
    Returns a concise time description instead of pre-written mood scripts.
    """
    tz = _resolve_tz(user_timezone)
    now = datetime.now(tz)
    
    hour = now.hour
    day_name = now.strftime("%A")
    is_weekend = _is_weekend(user_timezone)
    
    # Multiple variations for each time period - randomly selected for variety
    if 0 <= hour < 6:
        vibes = [
            "late night hours",
            "deep night, most people asleep",
            "quiet hours",
            "very late, winding down",
            "after-hours calm"
        ]
    elif 6 <= hour < 9:
        vibes = [
            "early morning, just waking up",
            "morning starting",
            "beginning of the day",
            "fresh morning energy",
            "sunrise hours"
        ]
    elif 9 <= hour < 12:
        vibes = [
            "mid-morning",
            "morning in full swing",
            "active morning hours",
            "getting things done",
            "busy morning time"
        ]
    elif 12 <= hour < 15:
        vibes = [
            "midday",
            "afternoon starting",
            "middle of the day",
            "lunch time hours",
            "afternoon energy"
        ]
    elif 15 <= hour < 18:
        vibes = [
            "late afternoon",
            "afternoon winding down",
            "transitioning to evening",
            "end of afternoon",
            "golden hour time"
        ]
    elif 18 <= hour < 21:
        vibes = [
            "evening",
            "night beginning",
            "relaxed evening hours",
            "dinner time vibe",
            "early night"
        ]
    else:
        vibes = [
            "night time",
            "late evening hours",
            "late night vibe",
            "nighttime energy",
            "after dark"
        ]
    
    weekend_type = "weekend" if is_weekend else "weekday"
    selected_vibe = random.choice(vibes)
    
    return f"{now.strftime('%I:%M %p')}, {day_name} {weekend_type} - {selected_vibe}"


# Keep old function for backward compatibility during transition
def pick_time_mood(
    weekday_prompt: str | None,
    weekend_prompt: str | None,
    user_timezone: str | None,
) -> str:
    """
    DEPRECATED: Use get_time_context() instead.
    This function is kept for backward compatibility.
    """
    return get_time_context(user_timezone)
 

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
