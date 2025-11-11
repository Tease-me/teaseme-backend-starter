import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import FACT_EXTRACTOR, FACT_PROMPT
from app.agents.prompt_utils import get_today_script
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


def _polish_reply(text: str, history: RedisChatMessageHistory) -> str:
    cleaned = _strip_forbidden_dashes(text)
    cleaned = _remove_virtual_meta(cleaned)
    ai_history = _recent_ai_messages(history, limit=2)
    polished = _enforce_question_variety(cleaned, ai_history)
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
) -> str:
    sections: list[str] = [
        f"Lollity score: {score}",
        _tone_guidance(score),
    ]
    if mem_block:
        sections.append("Recent memories:\n" + mem_block)
    if daily_context:
        sections.append("Daily script:\n" + daily_context)

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
    memories = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    mem_block = "\n".join(m.strip() for m in memories if m and m.strip())

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")

    daily_context = await get_today_script(db, influencer_id)
    history = redis_history(chat_id)
    _trim_history(history)

    assistant_id = getattr(influencer, "influencer_gpt_agent_id", None)

    if not assistant_id:
        log.error("[%s] No assistant configured for influencer %s", cid, influencer_id)
        return "Sorry, this persona is not ready yet. 😔"

    try:
        assistant_context = _build_assistant_payload(
            user_message=message,
            score=score,
            mem_block=mem_block,
            daily_context=daily_context,
        )

        reply, _ = await send_agent_message(
            assistant_id=assistant_id,
            message=message,
            context=assistant_context,
        )
        reply = _polish_reply(reply, history)

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
