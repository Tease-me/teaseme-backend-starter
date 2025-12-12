import logging,asyncio
from uuid import uuid4
from app.core.config import settings
from app.agents.scoring import get_score, update_score, extract_triad_scores, format_score_value
from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt, get_convo_analyzer_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import get_global_audio_prompt, get_global_prompt, get_today_script, build_system_prompt, get_relationship_status_block
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory
from app.db.models import Influencer
from fastapi import HTTPException
from app.utils.tts_sanitizer import sanitize_tts_text

log = logging.getLogger("teaseme-turn")

def redis_history(chat_id: str, influencer_id: str | None = None):
    return RedisChatMessageHistory(
        session_id=chat_id, url=settings.REDIS_URL, ttl=settings.HISTORY_TTL)

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

            for line in lines[:5]:
                if line.lower() == "no new memories.":
                    continue
                await store_fact(db, chat_id, line)
        except Exception as ex:
            log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)

async def handle_turn(message: str, chat_id: str, influencer_id: str, user_id: str | None = None, db=None, is_audio: bool = False) -> str:
    cid = uuid4().hex[:8]
    
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    # Returns dict {"intimacy": X, "passion": Y, "commitment": Z}
    score = get_score(user_id or chat_id, influencer_id)

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    analysis_summary = "Intent: unknown\nMeaning: unknown\nEmotion: unknown\nUrgency/Risk: none noted"

    # Parallelize independent DB/LLM queries
    async def _run_analysis():
        try:
            analyzer_prompt = await get_convo_analyzer_prompt(db)
            analyzer_kwargs = {"msg": message, "ctx": recent_ctx}
            if "lollity_score" in analyzer_prompt.input_variables:
                # Use helper to format dict as string if prompt expects single value
                # or we just pass the formatted string.
                analyzer_kwargs["lollity_score"] = format_score_value(score)
            analysis_resp = await CONVO_ANALYZER.ainvoke(analyzer_prompt.format(**analyzer_kwargs))
            return analysis_resp.content.strip() if analysis_resp.content else analysis_summary
        except Exception as ex:
            log.error("[%s] Conversation analysis failed: %s", cid, ex, exc_info=True)
            return analysis_summary

    # Gather all independent async operations
    influencer, analysis_summary, prompt_template, daily_context = await asyncio.gather(
        db.get(Influencer, influencer_id),
        _run_analysis(),
        get_global_audio_prompt(db) if is_audio else get_global_prompt(db),
        get_today_script(db, influencer_id),
    )
    
    if not influencer:
        raise HTTPException(404, "Influencer not found")
        
    if not influencer:
        raise HTTPException(404, "Influencer not found")
        
    # Compute persona rules locally (mimics build_system_prompt logic)
    intimacy = score.get("intimacy", 0)
    passion = score.get("passion", 0)
    commitment = score.get("commitment", 0)
    composite = (intimacy + passion + commitment) / 3

    try:
        persona_rules = influencer.prompt_template.format(
            lollity_score=int(composite),
            intimacy=int(intimacy),
            passion=int(passion),
            commitment=int(commitment)
        )
    except Exception:
        persona_rules = influencer.prompt_template.replace("{lollity_score}", str(int(composite)))

    memories_result = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    if isinstance(memories_result, tuple):
        memories = memories_result[0]
    else:
        memories = memories_result
    
    mem_block = "\n".join(
        s for s in (_norm(m) for m in memories or []) if s
    )

    # Build Chain
    chain = RunnableWithMessageHistory(
        prompt_template | MODEL,
        lambda session_id: redis_history(session_id),
        input_messages_key="input",
        history_messages_key="history",
    )

    # Invoke
    response_msg = await chain.ainvoke(
        {
            "input": message,
            "intimacy": int(intimacy),
            "passion": int(passion),
            "commitment": int(commitment),
            "analysis": analysis_summary,
            "persona_rules": persona_rules,
            "daily_context": daily_context,
            "memories": mem_block,
            "last_user_message": message,
        },
        config={"configurable": {"session_id": chat_id}}
    )
    
    reply = response_msg.content
    
    update_score(user_id or chat_id, influencer_id, extract_triad_scores(reply, score))
    
    # background task
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
        tts_text = sanitize_tts_text(reply)
        return tts_text
    return reply
