import asyncio
import json
import logging
import random
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.db.models import Influencer, Message18
from app.agents.prompt_utils import get_global_prompt, get_today_script, build_relationship_prompt
from app.agents.prompts import XAI_MODEL
from app.utils.tts_sanitizer import sanitize_tts_text
from app.services.system_prompt_service import get_system_prompt
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
log = logging.getLogger("teaseme-turn-18")

_TIME_RANGE_RE = re.compile(r"^\s*(\d{1,2})\s*(AM|PM)\s*-\s*(\d{1,2})\s*(AM|PM)\s*$", re.IGNORECASE)

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
    start_raw,start_ampm,end_raw,end_ampm = m.groups()
    start = _hour_from_12h(int(start_raw), start_ampm)
    end = _hour_from_12h(int(end_raw), end_ampm)

    return (start, end)

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
    return now.weekday() >= 5  # 5 = Saturday, 6 = Sunday


def pick_time_mood(
    weekday_prompt: str | None,
    weekend_prompt: str | None,
    user_timezone: str | None
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

def _render_recent_ctx(rows: list[Message18]) -> list[BaseMessage]:
    """
    IMPORTANT: LangChain expects history as a list of BaseMessage, not a string.
    """
    msgs: list[BaseMessage] = []
    for m in rows:
        role = (m.sender or "").lower()
        txt = (m.content or "").strip()
        if not txt:
            continue

        if role == "user":
            msgs.append(HumanMessage(content=txt))
        else:
            msgs.append(AIMessage(content=txt))

    return msgs


async def _load_recent_ctx_18(db, chat_id: str, limit: int = 12) -> list[BaseMessage]:
    q = (
        select(Message18)
        .where(Message18.chat_id == chat_id)
        .order_by(Message18.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(q)
    rows = list(res.scalars().all())
    rows.reverse()  # oldest -> newest
    return _render_recent_ctx(rows)


async def handle_turn_18(
    *,
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: int,
    db,
    is_audio: bool = False,
    user_timezone: str | None = None,
) -> str:
    cid = uuid4().hex[:8]
    log.info("[%s] START(18) persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    influencer, base_adult_prompt, base_audio_prompt, weekday_prompt, weekend_prompt, recent_ctx = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_system_prompt(db, "BASE_ADULT_PROMPT"),
        get_system_prompt(db, "BASE_ADULT_AUDIO_PROMPT"),
        get_system_prompt(db, "WEEKDAY_TIME_PROMPT"),
        get_system_prompt(db, "WEEKEND_TIME_PROMPT"),
        _load_recent_ctx_18(db, chat_id, limit=12),
    )

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    system_prompt = base_adult_prompt
    if is_audio and base_audio_prompt:
        system_prompt = f"{base_adult_prompt}\n{base_audio_prompt}"


    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )
    mood = pick_time_mood(weekday_prompt, weekend_prompt, user_timezone)

    prompt = prompt.partial(main_prompt=influencer.custom_adult_prompt, history=recent_ctx, mood=mood)
    chain = prompt | XAI_MODEL

    try:
        result = await chain.ainvoke({"input": message})
        rendered = prompt.format_prompt(input=message, history=recent_ctx, main_prompt=influencer.custom_adult_prompt)
        full_prompt_text = rendered.to_string()
        log.info("[%s] ==== FULL PROMPT ====\n%s", cid, full_prompt_text)
        reply = getattr(result, "content", None) or str(result)

        if is_audio:
            return sanitize_tts_text(reply)

        return reply
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"
