import os
import re
import time
import logging
from uuid import uuid4
from dotenv import load_dotenv

from redis import Redis
from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.api.utils import get_embedding, search_similar_memories, upsert_memory


# ──────────────────────────── 0. Setup ────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("teaseme-turn")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL      = os.getenv("REDIS_URL", "redis://localhost:6379/0")

score_redis = Redis.from_url(REDIS_URL, decode_responses=True)
SCORE_KEY   = "lollity:{user}:{persona}"       # Redis key pattern
SCORE_RE    = re.compile(r"\[Lollity Score: (\d{1,3})/100]")
MAX_WINDOW  = 50                               # short‑term history cap

# ──────────────────────────── 1. Prompt Layers ────────────────────────
from app.agents.prompt_utils import (
    PERSONAS,
    GLOBAL_PROMPT,
    GLOBAL_AUDIO_PROMPT,
    get_today_script
)
# ──────────────────────────── 2. Helpers ──────────────────────────────
MODEL = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model_name="gpt-4-turbo",
    temperature=0.8,
    max_tokens=512,
)

def redis_history(chat_id: str) -> RedisChatMessageHistory:
    return RedisChatMessageHistory(
        session_id=chat_id,
        url=REDIS_URL,
        ttl=60 * 60 * 24 * 3, 
    )

def extract_score(text: str, default: int) -> int:
    m = SCORE_RE.search(text)
    return max(0, min(100, int(m.group(1)))) if m else default

fact_extractor = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model="gpt-3.5-turbo")
extract_prompt = ChatPromptTemplate.from_template(
    "From this conversation, extract any *facts* or *personal info* the AI should remember "
    "(name, favorites, relationships, secrets…). If nothing new, output 'No new memories.'\n\n"
    "User message: {msg}\nContext: {ctx}\nBullet points:"
)

# ──────────────────────────── 3. Turn handler ────────────────────────
async def handle_turn(
    message: str,
    chat_id: str,
    persona_id: str,
    user_id: str | None = None,
    db=None,
    is_audio: bool = False,
) -> str:
    cid = uuid4().hex[:8]
    start = time.perf_counter()
    log.info("[%s] START persona=%s chat=%s user=%s", cid, persona_id, chat_id, user_id)

    # 1. SCORE (Redis)
    score_key = SCORE_KEY.format(user=user_id or chat_id, persona=persona_id)
    score     = int(score_redis.get(score_key) or 50)
    log.info("[%s] Current Lollity Score: %s", cid, score)


    # 2. VECTOR‑MEMORY LOOKUP
    memories = []
    if db and user_id:
        emb = await get_embedding(message)
        memories = await search_similar_memories(db, chat_id, emb, top_k=7)
        memories = list(dict.fromkeys([m for m in memories if m]))
    log.info("[%s] Found memories: %s", cid, memories)
    mem_block = "\n".join(f"- {m}" for m in memories) or "None"

    # 3. PROMPT VARIABLES
    persona_tpl   = PERSONAS.get(persona_id, PERSONAS["anna"])
    persona_rules = persona_tpl.format(lollity_score=score)
    log.info("[%s] Persona rules: %s", cid, persona_rules)

    # 4. BUILD CHAIN (prompt | llm) + short‑term memory
    prompt_template = GLOBAL_AUDIO_PROMPT if is_audio else GLOBAL_PROMPT
    prompt = prompt_template.partial(persona_rules=persona_rules, memories=mem_block,daily_context=get_today_script())
    
    chain   = prompt | MODEL
    history = redis_history(chat_id)
    log.info("[%s] Current history: %s", cid, history.messages)

    # cap janela
    if len(history.messages) > MAX_WINDOW:
        log.info("[%s] Trimming history from %d to %d messages", cid, len(history.messages), MAX_WINDOW)

        trimmed = history.messages[-MAX_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    runnable = RunnableWithMessageHistory(
        chain,
        lambda _: history,
        input_messages_key="input",
        history_messages_key="history",
    )

    # 5. CALL LLM
    try:
        result = await runnable.ainvoke(
            {"input": message, "memories": mem_block},
            config={"configurable": {"session_id": chat_id}},
        )
        reply = result.content
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"

    log.info("[%s] LLM reply: %r", cid, reply)

    # 6. UPDATE SCORE
    new_score = extract_score(reply, score)
    score_redis.set(score_key, new_score, ex=60 * 60 * 24 * 30)
    log.info("[%s] Score %s → %s", cid, score, new_score)

    # 7. FACT EXTRACTION → VECTOR DB
    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    try:
        facts_resp = await fact_extractor.ainvoke(
            extract_prompt.format(msg=message, ctx=recent_ctx)
        )
        facts_txt = facts_resp.content
        if facts_txt.strip().lower() != "no new memories.":
            for line in facts_txt.split("\n"):
                fact = line.strip("- ").strip()
                if fact and fact.lower() != "no new memories.":
                    emb = await get_embedding(fact)
                    await upsert_memory(
                        db=db,
                        chat_id=chat_id,
                        content=fact,
                        embedding=emb,
                        sender="user",
                    )
                    log.info("[%s] Upserted fact: %s", cid, fact)
    except Exception as ex:
        log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)

    log.info("[%s] END  %.1f ms", cid, (time.perf_counter() - start) * 1000)
    return reply