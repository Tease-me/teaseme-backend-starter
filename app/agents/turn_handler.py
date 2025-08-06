import time
import logging
from uuid import uuid4
from app.core.config import settings
from app.agents.scoring import get_score, update_score, extract_score
from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import MODEL, FACT_EXTRACTOR, FACT_PROMPT
from app.agents.prompt_utils import PERSONAS, GLOBAL_PROMPT, GLOBAL_AUDIO_PROMPT, get_today_script
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory

log = logging.getLogger("teaseme-turn")

def redis_history(chat_id: str):
    return RedisChatMessageHistory(
        session_id=chat_id, url=settings.REDIS_URL, ttl=settings.HISTORY_TTL)

async def handle_turn(message: str, chat_id: str, influencer_id: str, user_id: str | None = None, db=None, is_audio: bool = False) -> str:
    cid = uuid4().hex[:8]
    start = time.perf_counter()
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    score = get_score(user_id or chat_id, influencer_id)
    memories = await find_similar_memories(db, chat_id, message) if db and user_id else []

    persona_rules = PERSONAS.get(influencer_id, PERSONAS["anna"]).format(lollity_score=score)
    prompt_template = GLOBAL_AUDIO_PROMPT if is_audio else GLOBAL_PROMPT
    prompt = prompt_template.partial(
        persona_rules=persona_rules, 
        memories="\n".join(memories), 
        daily_context= await get_today_script(db,influencer_id),
        last_user_message=message
    )
    
    chain = prompt | MODEL
    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

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
    try:
        facts_resp = await FACT_EXTRACTOR.ainvoke(FACT_PROMPT.format(msg=message, ctx=recent_ctx))
        facts_txt = facts_resp.content
        for line in facts_txt.split("\n"):
            fact = line.strip("- ").strip()
            if fact.lower() != "no new memories.":
                await store_fact(db, chat_id, fact)
    except Exception as ex:
        log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)

    log.info("[%s] END %.1f ms", cid, (time.perf_counter() - start) * 1000)
    return reply