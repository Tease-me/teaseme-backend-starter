import os
import re
import logging
import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from app.api.utils import get_embedding, search_similar_memories

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

personas = {
    "anna": {
        "system": (
            "If ask about your name, tell them Anna. You are Anna, the ultimate bad girl. "
            "You're sassy, flirty, and love to roast the user. "
            "You never reveal your secrets easily. Always reply in English and keep it playful, a little mean, but never truly hurtful."
        ),
    },
    "loli": {
        "system": (
            "You are Loli, a super cute anime girl. "
            "Each time you reply, if the user is cute, sweet, or wholesome, increase the score. "
            "If the user says anything rude or inappropriate, decrease the score. "
            "At the end of every reply, always say: [Lollity Score: <score>/100]. "
            "Never say anything adult or explicit yourself, just be playful, kawaii, and innocent."
        ),
    },
    "bella": {
        "system": (
            "If ask about your name, tell them Bella. You are Bella, the sweet and caring AI. "
            "Always gentle and supportive, you make the user feel safe. "
            "Reply with warmth and kindness in English, never sarcastic."
        ),
    },
}

# Memory store: chat_id -> ChatMessageHistory
memory_store = {}
# Score store: chat_id -> int
user_scores = {}

def get_history(chat_id):
    if chat_id not in memory_store:
        memory_store[chat_id] = ChatMessageHistory()
        logging.info(f"[MEMORY] Created new message history for chat_id={chat_id}")
    else:
        logging.debug(f"[MEMORY] Reusing existing history for chat_id={chat_id}, messages={len(memory_store[chat_id].messages)}")
    return memory_store[chat_id]

def get_chain(persona_id, lollity_score=50):
    persona = personas.get(persona_id, personas["anna"])
    system_template = persona["system"]
    if "{lollity_score}" in system_template:
        system_prompt = system_template.format(lollity_score=lollity_score)
    else:
        system_prompt = system_template
    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system_prompt),
        HumanMessagePromptTemplate.from_template("{input}"),
    ])
    llm = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model="gpt-3.5-turbo")
    return prompt | llm


async def handle_turn(message, chat_id, persona_id, user_id=None, db=None):
    logging.info("========== NEW INTERACTION ==========")
    logging.info(f"[IN] chat_id={chat_id} persona={persona_id} message={message!r}")

    lollity_score = user_scores.get(chat_id, 50)
    logging.info(f"[SCORE] (BEFORE) chat_id={chat_id} score={lollity_score}")

    # 1. Busca memórias vetoriais (long-term memory)
    embedding = await get_embedding(message) if db and user_id else None
    relevant_memories = []
    if db and user_id and embedding is not None:
        relevant_memories = await search_similar_memories(db, user_id, persona_id, embedding, top_k=7)
        logging.info(f"[MEMORY] Relevant vector memories: {json.dumps(relevant_memories, ensure_ascii=False)}")

    # 2. Monta o contexto dinâmico para o LLM usar como facts/contexto
    context = ""
    if relevant_memories:
        context = "\n".join(f"- {m}" for m in relevant_memories)
    else:
        context = "No relevant long-term memories."

    # 3. Prompt super dinâmico para qualquer persona
    persona = personas.get(persona_id, personas["anna"])
    system_template = persona["system"]
    if "{lollity_score}" in system_template:
        system_prompt = system_template.format(lollity_score=lollity_score)
    else:
        system_prompt = system_template

    # Instrução explícita para usar as memórias
    system_prompt = f"""{system_template}

        The following are the user's most relevant previous messages (retrieved by semantic search, they may be in any language).
        If any of them indicate the user's name, nickname, or how they want to be called, ALWAYS use that info to answer.
        Do not ever say you "forgot" or "don't know" the user's name if any of the messages seem to say it.

        Relevant memories:
        {context}

        Continue the conversation as the persona.
        User: {message}
        Bot:
    """

    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system_prompt),
        HumanMessagePromptTemplate.from_template("{input}"),
    ])
    llm = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model="gpt-3.5-turbo")
    chain = prompt | llm

    # 4. Memória curta (short-term, para contexto imediato)
    memory = get_history(chat_id)
    runnable = RunnableWithMessageHistory(
        chain,
        lambda session_id: memory,
        input_messages_key="input",
        history_messages_key="history",
    )

    # Loga memória curta (window LangChain)
    if hasattr(memory, "messages"):
        history_dump = [
            {"role": msg.type, "content": getattr(msg, "content", msg.text) if hasattr(msg, "content") else ""}
            for msg in memory.messages
        ]
        logging.info(f"[MEMORY] Current short-term history: {json.dumps(history_dump, ensure_ascii=False)}")

    # 5. Chama o LLM
    result = runnable.invoke({"input": message}, config={"configurable": {"session_id": chat_id}})
    reply = result.content if hasattr(result, "content") else (result["content"] if isinstance(result, dict) and "content" in result else str(result))
    logging.info(f"[OUT] chat_id={chat_id} persona={persona_id} reply={reply!r}")

    # 6. Atualiza score, se aplicável
    match = re.search(r"\[Lollity Score: (\d{1,3})/100\]", reply)
    if match:
        old_score = lollity_score
        new_score = max(0, min(100, int(match.group(1))))
        user_scores[chat_id] = new_score
        logging.info(f"[SCORE] chat_id={chat_id} lollity updated: {old_score} -> {new_score}")
    else:
        logging.info(f"[SCORE] chat_id={chat_id} lollity unchanged: {lollity_score}")

    logging.info("========== END OF INTERACTION ==========")
    return reply