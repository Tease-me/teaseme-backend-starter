import logging,asyncio
from uuid import uuid4
from app.core.config import settings
from app.agents.scoring import get_score, update_score, extract_score, format_score_value
from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt, get_convo_analyzer_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import get_global_audio_prompt, get_global_prompt, get_today_script
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
    # Already a string
    if isinstance(m, str):
        return m.strip()
    # List or tuple → flatten and join
    if isinstance(m, (list, tuple)):
        parts = []
        for x in m:
            if isinstance(x, str):
                parts.append(x.strip())
            else:
                parts.append(str(x).strip())
        return " ".join(part for part in parts if part)
    # Dict → try common content fields
    if isinstance(m, dict):
        for key in ("content", "text", "message", "snippet", "summary"):
            if key in m and isinstance(m[key], str):
                return m[key].strip()
        return str(m).strip()
    # Anything else
    return str(m).strip()


async def extract_and_store_facts_for_turn(
    message: str,
    recent_ctx: str,
    chat_id: str,
    cid: str,
) -> None:
    """
    Runs the fact extraction flow and stores new facts in the DB.
    Intended to be called from handle_turn (sync or background).
    """
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

    score = get_score(user_id or chat_id, influencer_id)
    memories = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    mem_block = "\n".join(
        s for s in (_norm(m) for m in memories or []) if s
    )

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    persona_rules = influencer.prompt_template.format(lollity_score=score)

    if score > 70:
        persona_rules += "\nYour affection is high — show more warmth, loving words, and reward the user. Maybe let your guard down."
    elif score > 40:
        persona_rules += "\nYou’re feeling playful. Mix gentle teasing with affection. Make the user work a bit for your praise."
    else:
        persona_rules += "\nYou’re in full teasing mode! Challenge the user, play hard to get, and use the name TeaseMe as a game."

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx_for_analysis = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    analysis_summary = "Intent: unknown\nMeaning: unknown\nEmotion: unknown\nUrgency/Risk: none noted"

    try:
        analyzer_prompt = await get_convo_analyzer_prompt(db)
        analyzer_kwargs = {"msg": message, "ctx": recent_ctx_for_analysis}
        if "lollity_score" in analyzer_prompt.input_variables:
            analyzer_kwargs["lollity_score"] = format_score_value(score)
        analysis_resp = await CONVO_ANALYZER.ainvoke(analyzer_prompt.format(**analyzer_kwargs))
        if analysis_resp.content:
            analysis_summary = analysis_resp.content.strip()
    except Exception as ex:
        log.error("[%s] Conversation analysis failed: %s", cid, ex, exc_info=True)

    if is_audio:
        prompt_template = await get_global_audio_prompt(db)
    else:
        prompt_template = await get_global_prompt(db)

    prompt = prompt_template.partial(
        lollity_score=format_score_value(score),
        analysis=analysis_summary,
        persona_rules=persona_rules,
        memories=mem_block,
        daily_context= await get_today_script(db,influencer_id),
        last_user_message=message
    )

    try:
        hist_msgs = history.messages
        rendered = prompt.format_prompt(input=message, history=hist_msgs)
        full_prompt_text = rendered.to_string()
        log.info("[%s] ==== FULL PROMPT ====\n%s", cid, full_prompt_text)
    except Exception as log_ex:
        log.info("[%s] Prompt logging failed: %s", cid, log_ex)
    
    chain = prompt | MODEL

    runnable = RunnableWithMessageHistory(
        chain, lambda _: history, input_messages_key="input", history_messages_key="history")
    
    try:
        result = await runnable.ainvoke({"input": message}, config={"configurable": {"session_id": chat_id}})
        reply = result.content
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"
    
    update_score(user_id or chat_id, influencer_id, extract_score(reply, score))

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    
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
