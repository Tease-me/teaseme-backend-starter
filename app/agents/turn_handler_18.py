import asyncio
import logging
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select

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
) -> str:
    cid = uuid4().hex[:8]
    log.info("[%s] START(18) persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    influencer, base_adult_prompt, base_audio_prompt, prompt_template, daily_context, recent_ctx = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_system_prompt(db, "BASE_ADULT_PROMPT"),
        get_system_prompt(db, "BASE_ADULT_AUDIO_PROMPT"),
        get_global_prompt(db, False),
        get_today_script(db=db, influencer_id=influencer_id),
        _load_recent_ctx_18(db, chat_id, limit=12),
    )

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    bio = influencer.bio_json or {}
    tone = bio.get("tone", "")
    mbti_rules = bio.get("mbti_rules", "")
    personality_rules = bio.get("personality_rules", "")
    stages = bio.get("stages", {})
    if not isinstance(stages, dict):
        stages = {}

    adult_prompt = influencer.custom_adult_prompt or base_adult_prompt
    audio_prompt = influencer.custom_audio_prompt or base_audio_prompt

    system_prompt = adult_prompt
    if is_audio and audio_prompt:
        system_prompt = f"{adult_prompt}\n{audio_prompt}"


    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )

    chain = prompt | XAI_MODEL

    try:
        result = await chain.ainvoke({"input": message, "history": recent_ctx})
        rendered = prompt.format_prompt(input=message, history=recent_ctx)
        full_prompt_text = rendered.to_string()
        log.info("[%s] ==== FULL PROMPT ====\n%s", cid, full_prompt_text)
        reply = getattr(result, "content", None) or str(result)

        if is_audio:
            return sanitize_tts_text(reply)

        return reply
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"
