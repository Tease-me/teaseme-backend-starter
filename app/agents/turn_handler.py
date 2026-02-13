import logging
import asyncio
import time
from uuid import uuid4
from fastapi import HTTPException

from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.core.config import settings
from app.agents.memory import find_similar_memories, store_facts_batch
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import (
    get_global_prompt,
    build_relationship_prompt,
    get_time_context,
    get_mbti_rules_for_archetype,
    get_relationship_stage_prompts,
)
from app.db.models import Influencer, User
from app.utils.messaging.tts_sanitizer import sanitize_tts_text
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys
from app.utils.logging.prompt_logging import log_prompt

from app.relationship.processor import process_relationship_turn
from app.services.token_tracker import track_usage_bg, UsageTimer

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


async def extract_and_store_facts_for_turn(
    message: str,
    recent_ctx: str,
    chat_id: str,
    cid: str,
) -> None:
    async with SessionLocal() as db:
        try:
            fact_prompt = await get_fact_prompt(db)

            t = time.perf_counter()
            facts_resp = await FACT_EXTRACTOR.ainvoke(
                fact_prompt.format(msg=message, ctx=recent_ctx)
            )
            fact_ms = int((time.perf_counter() - t) * 1000)

            facts_txt = facts_resp.content or ""
            lines = [ln.strip("- ").strip() for ln in facts_txt.split("\n") if ln.strip()]
            
            # Track fact extraction usage
            usage = getattr(facts_resp, "usage_metadata", None) or {}
            track_usage_bg(
                "extraction", "openai", "gpt-4o-mini", "fact_extraction",
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                latency_ms=fact_ms,
                user_id=int(user_id) if user_id else None,
                influencer_id=influencer_id,
                chat_id=chat_id,
            )

            # Filter out empty/skip lines
            valid_facts = [line for line in lines[:5] if line.lower() != "no new memories."]
            
            if valid_facts:
                # Use batch storage - single API call for all facts
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

    # Phase 1: Fetch cached prompts in parallel (Redis cache, no DB contention)
    prompt_template = await get_global_prompt(db, is_audio)
    
    influencer = await db.get(Influencer, influencer_id)
    
    # Generate simple time context instead of picking from mood arrays
    time_context = get_time_context(user_timezone)

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    if not user_id:
        raise HTTPException(400, "user_id is required for relationship persistence")

    from app.services.embeddings import get_embedding
    message_embedding = await get_embedding(message) if (db and user_id) else None

    # Run in parallel with separate DB sessions for optimal performance
    # Each task gets its own session to avoid SQLAlchemy concurrency issues
    async def _rel_pack_with_session():
        async with SessionLocal() as db_rel:
            return await process_relationship_turn(
                db=db_rel,
                user_id=int(user_id),
                influencer_id=influencer_id,
                message=message,
                recent_ctx=recent_ctx,
                cid=cid,
                convo_analyzer=CONVO_ANALYZER,
                influencer=influencer,
            )

    async def _memories_with_session():
        if not (db and user_id):
            return []
        async with SessionLocal() as db_mem:
            return await find_similar_memories(
                db_mem,
                chat_id,
                message,
                embedding=message_embedding  # Reuse precomputed embedding
            )

    # Execute both in parallel - each with independent DB session
    rel_pack, memories_result = await asyncio.gather(
        _rel_pack_with_session(),
        _memories_with_session()
    )
   
    rel = rel_pack["rel"]
    days_idle = rel_pack["days_idle"]
    dtr_goal = rel_pack["dtr_goal"]

    memories = memories_result[0] if isinstance(memories_result, tuple) else memories_result
    mem_block = "\n".join(s for s in (_norm(m) for m in memories or []) if s)

    bio = influencer.bio_json or {}

    persona_likes = bio.get("likes", [])
    persona_dislikes = bio.get("dislikes", [])
    if not isinstance(persona_likes, list):
        persona_likes = []
    if not isinstance(persona_dislikes, list):
        persona_dislikes = []
    
    # OPTIMIZATION: Parallelize system prompt fetches
    # These are independent Redis/DB lookups that can run concurrently
    mbti_archetype = bio.get("mbti_architype", "")  
    mbti_addon = bio.get("mbti_rules", "")
    
    stages, mbti_rules = await asyncio.gather(
        get_relationship_stage_prompts(db),
        get_mbti_rules_for_archetype(db, mbti_archetype, mbti_addon)
    )
    
    bio_stages = bio.get("stages", {})
    if isinstance(bio_stages, dict) and bio_stages:
        for key, val in bio_stages.items():
            if val: 
                stages[key.upper()] = val

    personality_rules = bio.get("personality_rules", "")
    tone = bio.get("tone", "")
    daily_context = ""  
    users_name = await _build_user_name_block(db, user_id)

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
        last_user_message=recent_ctx,
        mood=time_context,
        tone=tone,
        influencer_name=influencer.display_name,
        users_name=users_name,
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
        t0 = time.perf_counter()
        result = await runnable.ainvoke(
            {"input": message},
            config={"configurable": {"session_id": chat_id}},
        )
        main_ms = int((time.perf_counter() - t0) * 1000)
        reply = result.content

        # Track main reply usage
        usage = getattr(result, "usage_metadata", None) or {}
        track_usage_bg(
            "text", "openai", "gpt-5.2", "main_reply",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=main_ms,
            user_id=int(user_id) if user_id else None,
            influencer_id=influencer_id,
            chat_id=chat_id,
        )
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        track_usage_bg(
            "text", "openai", "gpt-5.2", "main_reply",
            user_id=int(user_id) if user_id else None,
            influencer_id=influencer_id,
            chat_id=chat_id,
            success=False,
            error_message=str(e)[:400],
        )
        return "Sorry, something went wrong. 😔"

    # Schedule background fact extraction (fire-and-forget)
    # Store task reference to prevent premature garbage collection
    try:
        fact_task = asyncio.create_task(
            extract_and_store_facts_for_turn(
                message=message,
                recent_ctx=recent_ctx,
                chat_id=chat_id,
                cid=cid,
            )
        )
        # Add done callback to log any exceptions
        fact_task.add_done_callback(
            lambda t: log.error("[%s] Fact extraction failed: %s", cid, t.exception()) 
            if t.exception() else None
        )
    except Exception as ex:
        log.error("[%s] Failed to schedule fact extraction: %s", cid, ex, exc_info=True)

    if is_audio:
        return sanitize_tts_text(reply)

    return reply

