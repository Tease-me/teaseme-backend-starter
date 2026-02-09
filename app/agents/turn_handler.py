import logging
import asyncio
from uuid import uuid4
from fastapi import HTTPException

from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.core.config import settings
from app.agents.memory import find_similar_memories, get_recent_facts, store_facts_batch
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import (
    get_global_prompt,
    build_relationship_prompt,
    pick_time_mood,
    get_mbti_rules_for_archetype,
    get_relationship_stage_prompts,
)
from app.db.models import Influencer
from app.utils.tts_sanitizer import sanitize_tts_text
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys
from app.utils.prompt_logging import log_prompt

from app.relationship.processor import process_relationship_turn

log = logging.getLogger("teaseme-turn")


def redis_history(chat_id: str):
    return RedisChatMessageHistory(
        session_id=chat_id,
        url=settings.REDIS_URL,
        ttl=settings.HISTORY_TTL,
    )


def _norm(m):
    if m is None:
        return ""
    if isinstance(m, str):
        return m.strip()
    if isinstance(m, (list, tuple)):
        parts = []
        for x in m:
            if isinstance(x, str):
                parts.append(x.strip())
            else:
                parts.append(str(x).strip())
        return " ".join(part for part in parts if part)
    if isinstance(m, dict):
        for key in ("content", "text", "message", "snippet", "summary"):
            if key in m and isinstance(m[key], str):
                return m[key].strip()
        return str(m).strip()
    return str(m).strip()


async def extract_and_store_facts_for_turn(
    message: str,
    recent_ctx: str,
    chat_id: str,
    cid: str,
) -> None:
    async with SessionLocal() as db:
        try:
            fact_prompt = await get_fact_prompt(db)

            facts_resp = await FACT_EXTRACTOR.ainvoke(
                fact_prompt.format(msg=message, ctx=recent_ctx)
            )

            facts_txt = facts_resp.content or ""
            lines = [ln.strip("- ").strip() for ln in facts_txt.split("\n") if ln.strip()]

            valid_facts = [line for line in lines[:5] if line.lower() != "no new memories."]

            if valid_facts:
                await store_facts_batch(db, chat_id, valid_facts)
                
        except Exception as ex:
            log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)


async def handle_turn(
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: str | None = None,
    db=None,
    is_audio: bool = False,
    user_timezone: str | None = None,
) -> str:
    cid = uuid4().hex[:8]
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])

    # System prompts use Redis caching (safe to parallelize)
    prompt_template, weekday_prompt, weekend_prompt = await asyncio.gather(
        get_global_prompt(db, is_audio),
        get_system_prompt(db, prompt_keys.WEEKDAY_TIME_PROMPT),
        get_system_prompt(db, prompt_keys.WEEKEND_TIME_PROMPT),
    )

    # DB gets must be sequential (AsyncSession concurrency restriction)
    influencer = await db.get(Influencer, influencer_id)
    
    mood = pick_time_mood(weekday_prompt, weekend_prompt, user_timezone)

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    if not user_id:
        raise HTTPException(400, "user_id is required for relationship persistence")

    rel_pack = await process_relationship_turn(
        db=db,
        user_id=int(user_id),
        influencer_id=influencer_id,
        message=message,
        recent_ctx=recent_ctx,
        cid=cid,
        convo_analyzer=CONVO_ANALYZER,
        influencer=influencer,
    )

   
    rel = rel_pack["rel"]
    days_idle = rel_pack["days_idle"]
    dtr_goal = rel_pack["dtr_goal"]

    memories_result = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    similar_mems = memories_result[0] if isinstance(memories_result, tuple) else memories_result
    recent_facts = await get_recent_facts(db, chat_id, limit=15) if (db and user_id) else []

    # COPILOT FIX: Properly merge similar memories + recent facts with deduplication
    seen = set()
    merged = []
    for m in list(similar_mems or []) + list(recent_facts or []):
        txt = _norm(m)
        if txt and txt not in seen:
            seen.add(txt)
            merged.append(txt)

    mem_block = "\n".join(merged)

    bio = influencer.bio_json or {}

    from app.services.preference_service import (
        get_persona_preference_labels,
        build_preference_context,
        build_preference_time_activity,
        build_preference_daily_topic,
    )
    persona_likes, persona_dislikes, pref_keys = await get_persona_preference_labels(db, influencer_id)
    
    stages = await get_relationship_stage_prompts(db)
    bio_stages = bio.get("stages", {})
    if isinstance(bio_stages, dict) and bio_stages:
        for key, val in bio_stages.items():
            if val: 
                stages[key.upper()] = val

    mbti_archetype = bio.get("mbti_architype", "")
    mbti_addon = bio.get("mbti_rules", "")
    mbti_rules = await get_mbti_rules_for_archetype(db, mbti_archetype, mbti_addon)
    personality_rules = bio.get("personality_rules", "")
    tone = bio.get("tone", "")

    pref_activity = build_preference_time_activity(pref_keys, user_timezone)
    if pref_activity:
        mood = f"{mood}. Right now you're {pref_activity}" if mood else f"Right now you're {pref_activity}"

    daily_topic = build_preference_daily_topic(pref_keys)

    from datetime import date
    today_script = ""
    if influencer.daily_scripts:
        idx = date.today().timetuple().tm_yday % len(influencer.daily_scripts)
        today_script = influencer.daily_scripts[idx]

    pref_ctx = ""
    if user_id:
        pref_ctx = await build_preference_context(db, int(user_id), influencer_id)

    try:
        from app.services.brave_search import fetch_trending_context
        live_ctx = await fetch_trending_context(pref_keys, influencer_id, user_timezone)
    except Exception as exc:
        log.warning("[%s] Brave search failed (non-fatal): %s", cid, exc)
        live_ctx = ""

    ctx_parts = [p for p in [today_script, daily_topic, pref_ctx, live_ctx] if p]
    daily_context = " ".join(ctx_parts)

    prompt = build_relationship_prompt(
        prompt_template,
        rel=rel,
        days_idle=days_idle,
        dtr_goal=dtr_goal,
        personality_rules=personality_rules,
        stages=stages,
        persona_likes=persona_likes,
        persona_dislikes=persona_dislikes,
        mbti_rules=mbti_rules,
        memories=mem_block,
        daily_context=daily_context,
        last_user_message=message,
        mood=mood,
        tone=tone,
        influencer_name=influencer.display_name,
    )

    hist_msgs = history.messages
    log_prompt(log, prompt, cid=cid, input=message, history=hist_msgs)

    chain = prompt | MODEL

    runnable = RunnableWithMessageHistory(
        chain,
        lambda _: history,
        input_messages_key="input",
        history_messages_key="history",
    )

    try:
        result = await runnable.ainvoke(
            {"input": message},
            config={"configurable": {"session_id": chat_id}},
        )
        reply = result.content
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"

    try:
        asyncio.create_task(
            extract_and_store_facts_for_turn(
                message=message,
                recent_ctx=recent_ctx,
                chat_id=chat_id,
                cid=cid,
            )
        )
    except Exception as ex:
        log.error("[%s] Failed to schedule fact extraction: %s", cid, ex, exc_info=True)

    if is_audio:
        return sanitize_tts_text(reply)

    return reply
