import asyncio
import logging
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.agents.prompt_utils import pick_time_mood
from app.db.models import Influencer, Message18, User
from app.agents.prompts import XAI_MODEL
from app.utils.tts_sanitizer import sanitize_tts_text
from app.utils.prompt_logging import log_prompt
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys
from langchain_core.prompts import ChatPromptTemplate
log = logging.getLogger("teaseme-turn-18")


def _render_recent_ctx(rows: list[Message18]) -> list[BaseMessage]:

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
    rows.reverse() 
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

    # Phase 1: Fetch system prompts in parallel
    # Uses Redis-backed caching; cache misses use separate DB sessions,
    # avoiding concurrent access to the shared AsyncSession.
    base_adult_prompt, base_audio_prompt, weekday_prompt, weekend_prompt = await asyncio.gather(
        get_system_prompt(db, prompt_keys.BASE_ADULT_PROMPT),
        get_system_prompt(db, prompt_keys.BASE_ADULT_AUDIO_PROMPT),
        get_system_prompt(db, prompt_keys.WEEKDAY_TIME_PROMPT_ADULT),
        get_system_prompt(db, prompt_keys.WEEKEND_TIME_PROMPT_ADULT),
    )
    
    # Phase 2: DB operations sequentially (AsyncSession doesn't allow concurrent access)
    influencer = await db.get(Influencer, influencer_id)
    user = await db.get(User, user_id)
    recent_ctx = await _load_recent_ctx_18(db, chat_id, limit=12)

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    system_prompt = base_adult_prompt
    if is_audio and base_audio_prompt:
        system_prompt = f"{base_adult_prompt}\n{base_audio_prompt}"

    # Load persona preferences and generate 18+ time-of-day activity
    from app.services.preference_service import (
        get_persona_preference_labels,
        build_preference_time_activity,
    )
    _, _, pref_keys = await get_persona_preference_labels(db, influencer_id)
    pref_activity = build_preference_time_activity(pref_keys, user_timezone, is_adult=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )
    mood = pick_time_mood(weekday_prompt, weekend_prompt, user_timezone)
    if pref_activity:
        mood = f"{mood}. Right now you're {pref_activity}" if mood else f"Right now you're {pref_activity}"

    user_adult_prompt = user.custom_adult_prompt if user else None
    prompt = prompt.partial(user_prompt=user_adult_prompt, history=recent_ctx, mood=mood)
    chain = prompt | XAI_MODEL

    try:
        result = await chain.ainvoke({"input": message})
        log_prompt(
            log,
            prompt,
            cid=cid,
            input=message,
            history=recent_ctx,
            user_prompt=user_adult_prompt,
        )
        reply = getattr(result, "content", None) or str(result)

        if is_audio:
            return sanitize_tts_text(reply)

        return reply
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"
