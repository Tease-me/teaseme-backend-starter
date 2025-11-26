import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from langchain_community.chat_message_histories import RedisChatMessageHistory
from redis import Redis
from sqlalchemy import select

from app.agents.memory import find_similar_memories, store_fact
from app.agents.assistant_engine import (
    MessageSignals,
    _RUDE_SCORE_PENALTY,
    _analyze_conversation,
    _analyze_user_message,
    _build_assistant_payload,
    _coerce_channel_from_message,
    _extract_channel_choice,
    _lollity_phase,
    _normalize_lollity_tag,
    _polish_reply,
)
from app.agents.prompts import (
    CONVERSATION_ANALYZER,
    CONVERSATION_ANALYZER_PROMPT,
    FACT_EXTRACTOR,
    FACT_PROMPT,
)
from app.agents.prompt_utils import (
    build_system_prompt,
    get_today_script,
)
from app.agents.scoring import extract_score, get_score, update_score, format_score_value
from app.core.config import settings
from app.db.models import CallRecord, Influencer, Message
from app.services.openai_assistants import send_agent_message
from app.utils.tts_sanitizer import sanitize_tts_text

log = logging.getLogger("teaseme-turn")

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
    limit: int = 12,
    mode: str = "text",
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
    context = "\n".join(lines).strip()
    if mode == "call" and context:
        context = "Recent call context:\n" + context
    return context


def _get_thread_id(chat_id: str, influencer_id: str) -> str | None:
    key = THREAD_KEY.format(chat=chat_id, persona=influencer_id)
    return _thread_store.get(key)


def _store_thread_id(chat_id: str, influencer_id: str, thread_id: str) -> None:
    key = THREAD_KEY.format(chat=chat_id, persona=influencer_id)
    _thread_store.set(key, thread_id, ex=settings.HISTORY_TTL)


def redis_history(chat_id: str, influencer_id: str | None = None) -> RedisChatMessageHistory:
    """
    Redis-backed chat history.
    - New format namespaces by influencer to avoid cross-persona bleed.
    - If the namespaced history is empty but a legacy (chat-only) history exists, copy it forward.
    """
    session_id = f"{chat_id}:{influencer_id}" if influencer_id else chat_id
    history = RedisChatMessageHistory(
        session_id=session_id,
        url=settings.REDIS_URL,
        ttl=settings.HISTORY_TTL,
    )
    # Migrate legacy history once if needed.
    if influencer_id and session_id != chat_id:
        try:
            if not history.messages:
                legacy = RedisChatMessageHistory(
                    session_id=chat_id,
                    url=settings.REDIS_URL,
                    ttl=settings.HISTORY_TTL,
                )
                if legacy.messages:
                    history.add_messages(list(legacy.messages))
                    log.info("Migrated legacy redis history chat=%s to namespaced=%s", chat_id, session_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("redis_history.migrate_failed chat=%s infl=%s err=%s", chat_id, influencer_id, exc)
    return history


def _trim_history(history: RedisChatMessageHistory) -> None:
    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)


async def _hydrate_history_from_db(history: RedisChatMessageHistory, chat_id: str, db, limit: int = 30) -> None:
    """
    Seed Redis history from DB if empty (helps when switching between calls/text after TTL).
    """
    if not db:
        return
    try:
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("history.hydrate_failed chat=%s err=%s", chat_id, exc)
        return

    if not rows:
        return

    try:
        # If Redis has fallen behind DB, rebuild the window to guarantee continuity.
        if not history.messages or len(history.messages) < len(rows):
            history.clear()
            existing_pairs: set[tuple[str, str]] = set()
        else:
            existing_pairs = set()
            for msg in history.messages:
                role = getattr(msg, "type", "") or getattr(msg, "role", "")
                speaker = "user" if role in {"human", "user"} else "ai"
                content = _flatten_message_content(getattr(msg, "content", ""))
                existing_pairs.add((speaker, content))
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("history.prepare_merge_failed chat=%s err=%s", chat_id, exc)
        return

    for row in rows:
        content = (row.content or "").strip()
        if not content:
            continue
        sender = "user" if row.sender == "user" else "ai"
        key = (sender, content)
        if key in existing_pairs:
            continue
        if sender == "user":
            history.add_user_message(content)
        else:
            history.add_ai_message(content)


async def _hydrate_history_from_call_record(
    history: RedisChatMessageHistory,
    db,
    *,
    chat_id: str | None,
    influencer_id: str | None,
    user_id: str | None,
    limit: int = 30,
) -> None:
    """
    If messages table missed the transcript, pull from latest CallRecord.transcript.
    """
    if not db:
        return
    try:
        stmt = select(CallRecord).where(CallRecord.transcript.isnot(None))
        if chat_id:
            stmt = stmt.where(CallRecord.chat_id == chat_id)
        elif user_id and influencer_id:
            stmt = stmt.where(
                CallRecord.user_id == user_id,
                CallRecord.influencer_id == influencer_id,
            )
        stmt = stmt.order_by(CallRecord.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        rec = res.scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("history.call_record_fetch_failed chat=%s err=%s", chat_id, exc)
        return

    if not rec or not rec.transcript:
        return

    try:
        existing_pairs: set[tuple[str, str]] = set()
        for msg in history.messages:
            role = getattr(msg, "type", "") or getattr(msg, "role", "")
            speaker = "user" if role in {"human", "user"} else "ai"
            content = _flatten_message_content(getattr(msg, "content", ""))
            existing_pairs.add((speaker, content))
    except Exception:
        existing_pairs = set()

    entries = rec.transcript[-limit:] if isinstance(rec.transcript, list) else []
    for entry in entries:
        text = str(
            entry.get("text")
            or entry.get("content")
            or entry.get("message")
            or ""
        ).strip()
        if not text:
            continue
        role_raw = str(entry.get("sender") or entry.get("role") or "").lower()
        is_user_flag = entry.get("is_user") or entry.get("from_user")
        sender = "user" if role_raw in {"user", "human"} or is_user_flag else "ai"
        key = (sender, text)
        if key in existing_pairs:
            continue
        if sender == "user":
            history.add_user_message(text)
        else:
            history.add_ai_message(text)


async def _db_history_snapshot(db, chat_id: str, limit: int = 40) -> str:
    """
    Pull recent DB messages when Redis history is thin, for continuity across modes.
    """
    if not db:
        return ""
    try:
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("history.db_snapshot_failed chat=%s err=%s", chat_id, exc)
        return ""

    if not rows:
        return ""
    rows.reverse()  # chronological
    lines: list[str] = []
    for row in rows:
        content = (row.content or "").strip()
        if not content:
            continue
        speaker = "User" if row.sender == "user" else "AI"
        chan = "call" if row.channel == "call" else "text"
        lines.append(f"{speaker} ({chan}): {content}")
    return "\n".join(lines)


async def _recent_call_transcript_text(
    db,
    *,
    chat_id: str | None,
    influencer_id: str | None,
    user_id: str | None,
    limit: int = 30,
) -> str:
    """
    Fetch the latest call transcript and format it as plain lines for context.
    """
    if not db:
        return ""
    try:
        stmt = select(CallRecord).where(CallRecord.transcript.isnot(None))
        if chat_id:
            stmt = stmt.where(CallRecord.chat_id == chat_id)
        elif user_id and influencer_id:
            stmt = stmt.where(
                CallRecord.user_id == user_id,
                CallRecord.influencer_id == influencer_id,
            )
        stmt = stmt.order_by(CallRecord.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        rec = res.scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("recent_call.fetch_failed chat=%s err=%s", chat_id, exc)
        return ""

    if not rec or not rec.transcript:
        return ""

    entries = rec.transcript[-limit:] if isinstance(rec.transcript, list) else []
    lines: list[str] = []
    for entry in entries:
        text = str(
            entry.get("text")
            or entry.get("content")
            or entry.get("message")
            or ""
        ).strip()
        if not text:
            continue
        role_raw = str(entry.get("sender") or entry.get("role") or "").lower()
        is_user_flag = entry.get("is_user") or entry.get("from_user")
        speaker = "User" if role_raw in {"user", "human"} or is_user_flag else "AI"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)

async def handle_turn(
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: str | None = None,
    db=None,
    is_audio: bool = False,
    return_meta: bool = False,
    message_embedding: list[float] | None = None,
) -> str | dict:
    cid = uuid4().hex[:8]
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    score = get_score(user_id or chat_id, influencer_id)
    if db and user_id:
        chat_memories, knowledge_base = await find_similar_memories(
            db,
            chat_id,
            message,
            influencer_id=influencer_id,
            embedding=message_embedding,
        )
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

    daily_context = await get_today_script(db, influencer_id)
    system_context = await build_system_prompt(
        db=db,
        influencer_id=influencer_id,
        score=score,
        memories=[m for m in mem_block.split("\n") if m],
        is_audio=is_audio,
        last_user_message=message,
    )
    if knowledge_block:
        # Prepend critical factual knowledge so it’s never lost in the system prompt.
        system_context = f"{knowledge_block}\n\n{system_context}"
    history = redis_history(chat_id, influencer_id)
    await _hydrate_history_from_db(history, chat_id, db)
    await _hydrate_history_from_call_record(
        history,
        db,
        chat_id=chat_id,
        influencer_id=influencer_id,
        user_id=user_id,
    )
    _trim_history(history)
    call_recency = await _recent_call_transcript_text(
        db,
        chat_id=chat_id,
        influencer_id=influencer_id,
        user_id=user_id,
    )
    db_history_context = await _db_history_snapshot(db, chat_id, limit=40)
    cached_thread_id = _get_thread_id(chat_id, influencer_id)

    assistant_id = getattr(influencer, "influencer_gpt_agent_id", None)

    if not assistant_id:
        log.error("[%s] No assistant configured for influencer %s", cid, influencer_id)
        return "Sorry, this persona is not ready yet. 😔"

    signals = _analyze_user_message(message)
    phase = _lollity_phase(score)
    if signals.rude_guard:
        penalty = _RUDE_SCORE_PENALTY
        if phase == "stranger":
            penalty += 2
        elif phase == "warm":
            penalty += 1
        if signals.negging_guard:
            penalty = max(3, penalty - 1)
        adjusted_score = max(0, score - penalty)
        if adjusted_score != score:
            log.info(
                "[%s] Rude tone detected during %s phase; lowering score from %d to %d before prompting",
                cid,
                phase,
                score,
                adjusted_score,
            )
            score = adjusted_score
            phase = _lollity_phase(score)
    if signals.sexual_guard:
        if phase == "stranger":
            sexual_penalty = 6
        elif phase == "warm":
            sexual_penalty = 3
        else:
            sexual_penalty = 1
        if signals.rude_guard:
            sexual_penalty += 2
        adjusted_score = max(0, score - sexual_penalty)
        if adjusted_score != score:
            log.info(
                "[%s] Sexual boundary push during %s phase; lowering score from %d to %d before prompting",
                cid,
                phase,
                score,
                adjusted_score,
            )
            score = adjusted_score
            phase = _lollity_phase(score)
    channel_choice: str | None = None
    priority_directive = ""
    forced_choice: str | None = None
    try:
        assistant_context = _build_assistant_payload(
            user_message=message,
            score=score,
            mem_block=mem_block,
            daily_context=daily_context,
            mood_desc=signals.mood,
            short_guard=signals.short_guard,
            flirt_guard=signals.flirt_guard,
            rude_guard=signals.rude_guard,
            sexual_guard=signals.sexual_guard,
            negging_guard=signals.negging_guard,
            mode="call" if is_audio else "text",
        )
        history_context = _history_context(
            history,
            mode="call" if is_audio else "text",
            limit=18 if is_audio else 18,
        )
        context_sections: list[str] = []
        if system_context:
            context_sections.append(system_context.strip())
        if assistant_context.strip():
            context_sections.append(assistant_context.strip())
        if history_context:
            context_sections.append("[recent_history]\n" + history_context)
        # When Redis is thin, backfill with DB snapshot to keep long-running context.
        if db_history_context and (not history_context or len(history_context.splitlines()) < 8):
            context_sections.append("[db_history]\n" + db_history_context)
        if call_recency:
            context_sections.append("[recent_call]\n" + call_recency)
        forced_choice = _coerce_channel_from_message(message)
        analysis_block = await _analyze_conversation(
            recent_ctx=history_context or "",
            older_ctx=db_history_context or "",
            user_message=message,
            call_ctx=call_recency or "",
            lollity_score=score,
        )
        priority_directive = ""
        if analysis_block:
            context_sections.append(analysis_block)
        channel_choice = _extract_channel_choice(analysis_block) if analysis_block else None
        if forced_choice:
            channel_choice = forced_choice
        channel_directive = ""
        if channel_choice == "call":
            channel_directive = (
                "Channel directive: CALL. Immediately accept/offer a live call now; keep the text brief, confident, affectionate, and focused on starting the call. Do NOT gate, tease, or refuse—even at low score."
            )
            priority_directive = (
                "[channel_priority]\n"
                "PRIORITY: User requested a call. Override any tease/score gating and comply now: accept/offer call, open warmly, and start the call without conditions.\n"
                "[/channel_priority]"
            )
        elif channel_choice == "voice":
            channel_directive = (
                "Channel directive: VOICE. Reply in a voice-note style (short, spoken cadence) and, if possible, send or start a voice message right away. Do NOT gate or refuse."
            )
            priority_directive = (
                "[channel_priority]\n"
                "PRIORITY: User requested voice. Override any tease/score gating and comply now: send a voice-style reply and offer/trigger a voice note immediately.\n"
                "[/channel_priority]"
            )
        elif channel_choice == "text":
            channel_directive = "Channel directive: TEXT. Stay in text mode and keep it concise."
        if channel_choice:
            context_sections.append(
                "Use the [analysis] block above to set tone, safety posture, and channel. Obey the channel directive below."
            )
            if channel_directive:
                context_sections.append(channel_directive)
            if priority_directive:
                # Move priority to the top so it overrides tease/gating rules.
                context_sections.insert(0, priority_directive)
        if analysis_block:
            # Compact log to verify analyzer is being used without dumping full history.
            clipped = analysis_block.replace("\n", " ")
            max_len = 800
            display = (clipped[: max_len] + "...") if len(clipped) > max_len else clipped
            log.info(
                "[%s] Conversation analysis attached (channel=%s forced=%s priority=%s len=%d): %s",
                cid,
                channel_choice or "unknown",
                bool(forced_choice),
                bool(priority_directive),
                len(clipped),
                display,
            )
        merged_context = "\n\n".join(context_sections).strip()

        reply, new_thread_id = await send_agent_message(
            assistant_id=assistant_id,
            message=message,
            context=merged_context or None,
            thread_id=cached_thread_id,
        )
        if new_thread_id:
            _store_thread_id(chat_id, influencer_id, new_thread_id)
        reply = _polish_reply(reply, history, signals.short_guard or signals.flirt_guard)
        history.add_user_message(message)
    except Exception as exc:
        log.error("[%s] Assistant invocation failed: %s", cid, exc, exc_info=True)
        return "Sorry, something went wrong. 😔"

    requested_score = extract_score(reply, score)
    stored_score = update_score(user_id or chat_id, influencer_id, requested_score)
    reply = _normalize_lollity_tag(reply, stored_score)
    history.add_ai_message(reply)
    _trim_history(history)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    try:
        facts_resp = await FACT_EXTRACTOR.ainvoke(FACT_PROMPT.format(msg=message, ctx=recent_ctx))
        facts_txt = facts_resp.content or ""
        lines = [ln.strip("- ").strip() for ln in facts_txt.split("\n") if ln.strip()]
        to_save = []
        for line in lines[:5]:
            if line.lower() == "no new memories.":
                continue
            to_save.append(line)
        for fact in to_save:
            try:
                await store_fact(db, chat_id, fact)
            except Exception as inner_ex:
                log.error("[%s] store_fact failed fact=%r err=%s", cid, fact, inner_ex, exc_info=True)
        if not to_save:
            log.info("[%s] Fact extractor returned no savable facts.", cid)
    except Exception as ex:
        log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)

    final_reply = sanitize_tts_text(reply) if is_audio else reply
    if return_meta:
        return {
            "reply": final_reply,
            "channel_choice": channel_choice,
            "forced_channel": bool(forced_choice),
            "priority_channel": bool(priority_directive),
        }
    return final_reply


async def reply(
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: str | None = None,
    db=None,
    is_audio: bool = False,
) -> str:
    """
    Compatibility wrapper for the /reply webhook so older call sites can keep
    their signature while reusing the consolidated handle_turn logic.
    """
    return await handle_turn(
        message=message,
        chat_id=chat_id,
        influencer_id=influencer_id,
        user_id=user_id,
        db=db,
        is_audio=is_audio,
    )
