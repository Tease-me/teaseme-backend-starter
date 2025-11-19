import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from langchain_community.chat_message_histories import RedisChatMessageHistory
from redis import Redis

from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import FACT_EXTRACTOR, FACT_PROMPT
from app.agents.prompt_utils import (
    GLOBAL_AUDIO_PROMPT,
    GLOBAL_PROMPT,
    get_today_script,
)
from app.agents.scoring import extract_score, get_score, update_score
from app.core.config import settings
from app.db.models import Influencer
from app.services.openai_assistants import send_agent_message
from app.utils.tts_sanitizer import sanitize_tts_text

log = logging.getLogger("teaseme-turn")
_DASH_RE = re.compile(r"[—–-]+")
_MULTISPACE_RE = re.compile(r"\s{2,}")
_PUNCT_GAP_RE = re.compile(r"\s+([?!.,)\]])")
_VIRTUAL_META_RE = re.compile(r"\b(virtual|digital|ai)\s+(friend|girlfriend|buddy|companion)\b", re.IGNORECASE)
_COMPANION_ROLE_RE = re.compile(r"\b(friendly\s+)?(companion|assistant|chat\s*buddy)\b", re.IGNORECASE)
_SHORT_REPLY_SET = {"ok", "k", "cool", "nothing", "no", "nah", "fine", "yup", "y", "sure", "idk", "nope"}
_FLIRT_RE = re.compile(r"\b(kiss|love|miss|beautiful|gorgeous|pretty|sexy|hot|cute|face|hug|want you)\b", re.IGNORECASE)

THREAD_KEY = "assistant_thread:{chat}:{persona}"
_thread_store = Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _flatten_message_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    return str(content or "")


def _history_context(
    history: RedisChatMessageHistory,
    latest_user_message: str | None = None,
    limit: int = 6,
) -> str:
    lines: list[str] = []
    if history and history.messages:
        for msg in history.messages[-limit:]:
            role = getattr(msg, "type", "")
            label = "User" if role in {"human", "user"} else "AI"
            content = _flatten_message_content(getattr(msg, "content", ""))
            if content:
                lines.append(f"{label}: {content}")
    if latest_user_message:
        lines.append(f"User: {latest_user_message.strip()}")
    return "\n".join(lines).strip()


def _get_thread_id(chat_id: str, influencer_id: str) -> str | None:
    key = THREAD_KEY.format(chat=chat_id, persona=influencer_id)
    return _thread_store.get(key)


def _store_thread_id(chat_id: str, influencer_id: str, thread_id: str) -> None:
    key = THREAD_KEY.format(chat=chat_id, persona=influencer_id)
    _thread_store.set(key, thread_id, ex=settings.HISTORY_TTL)


def _strip_forbidden_dashes(text: str) -> str:
    if not text:
        return ""
    cleaned = _DASH_RE.sub(" ", text)
    cleaned = _MULTISPACE_RE.sub(" ", cleaned)
    cleaned = _PUNCT_GAP_RE.sub(r"\1", cleaned)
    return cleaned.strip()


def _remove_virtual_meta(text: str) -> str:
    if not text:
        return ""
    def _repl(match: re.Match[str]) -> str:
        return match.group(2)
    cleaned = _VIRTUAL_META_RE.sub(_repl, text)
    cleaned = _COMPANION_ROLE_RE.sub("", cleaned)
    cleaned = _MULTISPACE_RE.sub(" ", cleaned)
    return cleaned


def _analyze_user_message(text: str) -> tuple[str, bool, bool]:
    if not text:
        return "no signal", True, False
    stripped = text.strip()
    if not stripped:
        return "no signal", True, False
    lower = stripped.lower()
    words = stripped.split()
    word_count = len(words)
    has_caps = any(ch.isupper() for ch in stripped if ch.isalpha())
    has_exclaim = "!" in stripped
    has_question = stripped.endswith("?")
    short_guard = word_count <= 2 or len(stripped) <= 6 or lower in _SHORT_REPLY_SET
    flirt_guard = bool(_FLIRT_RE.search(stripped))
    if has_exclaim and has_caps:
        mood = "urgent or heightened"
    elif has_question and not short_guard:
        mood = "curious or unsure"
    elif short_guard:
        mood = "low energy or closed off"
    else:
        mood = "ease / neutral"
    if flirt_guard:
        mood += " with flirt cues"
    return mood, short_guard, flirt_guard


def _recent_ai_messages(history: RedisChatMessageHistory, limit: int = 2) -> list[str]:
    if not history:
        return []
    collected: list[str] = []
    for msg in reversed(history.messages):
        if getattr(msg, "type", None) != "ai":
            continue
        content = msg.content
        if isinstance(content, list):
            fragments: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    fragments.append(str(part.get("text", "")))
                else:
                    fragments.append(str(part))
            content = " ".join(fragments)
        collected.append(str(content or ""))
        if len(collected) >= limit:
            break
    return collected


def _enforce_question_variety(text: str, ai_history: list[str], max_consecutive: int = 1) -> str:
    if not text:
        return ""
    trimmed = text.rstrip()
    if not trimmed.endswith("?"):
        return text
    consecutive = 0
    for prev in ai_history:
        if (prev or "").rstrip().endswith("?"):
            consecutive += 1
        else:
            break
    if consecutive >= max_consecutive:
        base = trimmed[:-1].rstrip()
        if not base:
            return "I'm here."
        return f"{base}."
    return text


def _polish_reply(text: str, history: RedisChatMessageHistory, block_questions: bool) -> str:
    cleaned = _strip_forbidden_dashes(text)
    cleaned = _remove_virtual_meta(cleaned)
    ai_history = _recent_ai_messages(history, limit=2)
    polished = _enforce_question_variety(cleaned, ai_history)
    if block_questions and polished.rstrip().endswith("?"):
        base = polished.rstrip().rstrip("?").rstrip()
        polished = base + "." if base else "Okay."
    return polished if polished else "I'm here."


def redis_history(chat_id: str):
    return RedisChatMessageHistory(
        session_id=chat_id,
        url=settings.REDIS_URL,
        ttl=settings.HISTORY_TTL,
    )


def _trim_history(history: RedisChatMessageHistory) -> None:
    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)


def _tone_guidance(score: int) -> str:
    if score > 70:
        return "Your affection is high — be warmer, reward the user, let your guard down, and consider a playful call invite if you haven’t offered one recently."
    if score > 40:
        return "You’re feeling playful; mix gentle teasing with affection and make the user earn extra praise."
    return "You’re in teasing mode — play hard to get, challenge the user, and reference the TeaseMe chase."


def _build_assistant_payload(
    *,
    user_message: str,
    score: int,
    mem_block: str,
    daily_context: str | None,
    mood_desc: str,
    short_guard: bool,
    flirt_guard: bool,
) -> str:
    sections: list[str] = [
        f"Lollity score: {score}",
        _tone_guidance(score),
    ]
    if mem_block:
        sections.append("Recent memories:\n" + mem_block)
    if daily_context:
        sections.append("Daily script:\n" + daily_context)
    sections.append(f"User emotion snapshot: {mood_desc}.")
    if short_guard:
        sections.append("Short reply detected: respond with statements (no questions) until the user shares more than a couple of words.")
    if flirt_guard:
        sections.append("Flirt cue detected: stay on the flirt thread, tease or reciprocate before asking any new question.")

    sections.append(
        "Scoring contract: start from the Lollity score above, then decide a new score between 0 and 100 after each reply. Move it by 1–4 points based on their energy (reward warmth/flirt, drop it for low-effort, rude, or boundary-pushing turns). ALWAYS end your reply with `[Lollity Score: NN/100]` using the new score and nothing else inside the brackets."
    )
    if flirt_guard:
        sections.append("The user flirted—if you reciprocate, nudge the score upward a couple of points before tagging it.")
    if short_guard:
        sections.append("User energy is low; unless they explicitly said they’re tired or busy, consider trimming the score by 1–2 points before tagging it.")

    context_blob = "\n\n".join(s for s in sections if s).strip()
    if context_blob:
        return f"[context]\n{context_blob}\n[/context]"
    return ""


async def handle_turn(
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: str | None = None,
    db=None,
    is_audio: bool = False,
) -> str:
    cid = uuid4().hex[:8]
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    score = get_score(user_id or chat_id, influencer_id)
    if db and user_id:
        chat_memories, knowledge_base = await find_similar_memories(db, chat_id, message, influencer_id=influencer_id)
        mem_block = "\n".join(m.strip() for m in chat_memories if m and m.strip())
        # Format knowledge base content separately and more prominently
        log.info("[%s] Knowledge base chunks found: %d for influencer_id=%s", cid, len(knowledge_base), influencer_id)
        if knowledge_base:
            knowledge_text = "\n".join(kb.strip() for kb in knowledge_base if kb and kb.strip())
            knowledge_block = f"=== CRITICAL: Factual Information About the User ===\nYou MUST use this information when the user asks about themselves or related topics. This is verified factual data:\n\n{knowledge_text}\n\nWhen the user asks about themselves, reference this information naturally in your response. Do NOT say you don't know - use this information instead."
            log.info("[%s] Knowledge block created, length: %d chars", cid, len(knowledge_block))
        else:
            knowledge_block = ""
            log.warning("[%s] No knowledge base chunks found for influencer_id=%s, message=%s", cid, influencer_id, message[:50])
    else:
        mem_block = ""
        knowledge_block = ""
        log.info("[%s] Skipping knowledge base (db=%s, user_id=%s)", cid, db is not None, user_id)

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    persona_rules = influencer.prompt_template.format(lollity_score=score)

    if score > 70:
        persona_rules += "\nYour affection is high — show more warmth, loving words, and reward the user. Maybe let your guard down."
    elif score > 40:
        persona_rules += "\nYou're feeling playful. Mix gentle teasing with affection. Make the user work a bit for your praise."
    else:
        persona_rules += "\nYou're in full teasing mode! Challenge the user, play hard to get, and use the name TeaseMe as a game."

    prompt_template = GLOBAL_AUDIO_PROMPT if is_audio else GLOBAL_PROMPT
    prompt = prompt_template.partial(
        persona_rules=persona_rules, 
        memories=mem_block,
        knowledge_base=knowledge_block,
        daily_context= await get_today_script(db,influencer_id),
        last_user_message=message
    )

    daily_context = await get_today_script(db, influencer_id)
    history = redis_history(chat_id)
    _trim_history(history)
    cached_thread_id = _get_thread_id(chat_id, influencer_id)

    assistant_id = getattr(influencer, "influencer_gpt_agent_id", None)

    if not assistant_id:
        log.error("[%s] No assistant configured for influencer %s", cid, influencer_id)
        return "Sorry, this persona is not ready yet. 😔"

    mood_desc, short_guard, flirt_guard = _analyze_user_message(message)
    try:
        assistant_context = _build_assistant_payload(
            user_message=message,
            score=score,
            mem_block=mem_block,
            daily_context=daily_context,
            mood_desc=mood_desc,
            short_guard=short_guard,
            flirt_guard=flirt_guard,
        )
        history_context = _history_context(history)
        context_sections: list[str] = []
        if assistant_context.strip():
            context_sections.append(assistant_context.strip())
        if history_context:
            context_sections.append("[recent_history]\n" + history_context)
        merged_context = "\n\n".join(context_sections).strip()

        reply, new_thread_id = await send_agent_message(
            assistant_id=assistant_id,
            message=message,
            context=merged_context or None,
            thread_id=cached_thread_id,
        )
        if new_thread_id:
            _store_thread_id(chat_id, influencer_id, new_thread_id)
        reply = _polish_reply(reply, history, short_guard or flirt_guard)

        history.add_user_message(message)
        history.add_ai_message(reply)
        _trim_history(history)
    except Exception as exc:
        log.error("[%s] Assistant invocation failed: %s", cid, exc, exc_info=True)
        return "Sorry, something went wrong. 😔"

    update_score(user_id or chat_id, influencer_id, extract_score(reply, score))

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    try:
        facts_resp = await FACT_EXTRACTOR.ainvoke(FACT_PROMPT.format(msg=message, ctx=recent_ctx))
        facts_txt = facts_resp.content or ""
        lines = [ln.strip("- ").strip() for ln in facts_txt.split("\n") if ln.strip()]
        for line in lines[:5]:
            if line.lower() == "no new memories.":
                continue
            await store_fact(db, chat_id, line)
    except Exception as ex:
        log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)

    if is_audio:
        return sanitize_tts_text(reply)
    return reply
