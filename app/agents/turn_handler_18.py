import asyncio
import logging
import time
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.db.models import Influencer, Message18, User
from app.agents.prompts import XAI_MODEL
from app.agents.prompt_utils import get_time_context
from app.utils.messaging.tts_sanitizer import sanitize_tts_text
from app.utils.logging.prompt_logging import log_prompt
from app.services.system_prompt_service import get_system_prompt
from app.services.token_tracker import track_usage_bg
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


async def _build_user_name_block(db, user_id) -> str:

    user = None
    if user_id:
        try:
            user = await db.get(User, int(user_id))
        except Exception as exc:
            log.warning("_build_user_name_block: failed to fetch user %s: %s", user_id, exc)

    if user:
        parts = []
        full_name = (user.full_name or "").strip()
        username = (user.username or "").strip()
        gender = (user.gender or "").strip()
        dob = user.date_of_birth

        if full_name:
            parts.append(f"Full name: {full_name}")
        if username:
            parts.append(f"Username: {username}")
        if gender:
            parts.append(f"Gender: {gender}")
        if dob:
            parts.append(f"Date of birth: {dob.strftime('%B %d, %Y')}")

        if parts:
            return (
                ", ".join(parts) + ". "
                "Use their name naturally and sparingly — don't overuse it. "
                "If the user has told you to call them something else "
                "(check your memories), use that preferred name instead."
            )
    return (
        "You don't know the user's name yet. "
        "If you've learned it in past conversations, use it from memory. "
        "Otherwise, don't assume a name."
    )


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

    # OPTIMIZATION: Fetch cached system prompts in parallel (Redis cache, no DB contention)
    # These are independent Redis lookups that benefit from parallel execution
    base_adult_prompt, base_audio_prompt = await asyncio.gather(
        get_system_prompt(db, prompt_keys.BASE_ADULT_PROMPT),
        get_system_prompt(db, prompt_keys.BASE_ADULT_AUDIO_PROMPT),
    )
    
    # Phase 2: DB operations sequentially (AsyncSession doesn't allow concurrent access)
    influencer = await db.get(Influencer, influencer_id)
    recent_ctx = await _load_recent_ctx_18(db, chat_id, limit=12)

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
    
    # Generate simple time context instead of picking from mood arrays
    time_context = get_time_context(user_timezone)

    user = await db.get(User, user_id) if user_id else None
    user_adult_prompt = user.custom_adult_prompt if user else None
    users_name = await _build_user_name_block(db, user_id)
    prompt = prompt.partial(
        user_prompt=user_adult_prompt or "",
        history=recent_ctx,
        mood=time_context,
        users_name=users_name
    )
    chain = prompt | XAI_MODEL

    try:
        t0 = time.perf_counter()
        result = await chain.ainvoke({"input": message})
        main_ms = int((time.perf_counter() - t0) * 1000)

        log_prompt(
            log,
            prompt,
            cid=cid,
            input=message,
            history=recent_ctx,
            user_prompt=user_adult_prompt,
        )
        reply = getattr(result, "content", None) or str(result)

        # Track 18+ LLM usage
        usage = getattr(result, "usage_metadata", None) or {}
        track_usage_bg(
            "18_chat", "xai", "grok-4-1-fast-reasoning", "main_reply",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=main_ms,
            user_id=user_id,
            influencer_id=influencer_id,
            chat_id=chat_id,
        )

        if is_audio:
            return sanitize_tts_text(reply)

        return reply
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        track_usage_bg(
            "18_chat", "xai", "grok-4-1-fast-reasoning", "main_reply",
            user_id=user_id,
            influencer_id=influencer_id,
            chat_id=chat_id,
            success=False,
            error_message=str(e)[:400],
        )
        return "Sorry, something went wrong. 😔"
