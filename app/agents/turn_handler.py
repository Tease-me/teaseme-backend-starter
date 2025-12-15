import logging,asyncio
from uuid import uuid4
from app.core.config import settings
from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt, get_convo_analyzer_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import get_global_audio_prompt, get_global_prompt, get_today_script
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory
from app.db.models import Influencer
from fastapi import HTTPException
from app.utils.tts_sanitizer import sanitize_tts_text

from datetime import datetime, timezone
from app.relationship.repo import get_or_create_relationship
from app.relationship.inactivity import apply_inactivity_decay
from app.relationship.signals import classify_signals
from app.relationship.engine import Signals, update_relationship
from app.relationship.dtr import plan_dtr_goal

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

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])
    analysis_summary = "Intent: unknown\nMeaning: unknown\nEmotion: unknown\nUrgency/Risk: none noted"

    # Gather all independent async operations
    influencer, prompt_template, daily_context = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_global_audio_prompt(db) if is_audio else get_global_prompt(db),
        get_today_script(db=db, influencer_id=influencer_id),
    )
    
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    
    if not user_id:
        raise HTTPException(400, "user_id is required for relationship persistence")
    
    now = datetime.now(timezone.utc)

    # 1) Load relationship row from DB
    rel = await get_or_create_relationship(db, int(user_id), influencer_id)

    # 2) Inactivity decay (if user disappeared for days)
    days_idle = apply_inactivity_decay(rel, now)

    # 3) Classify user message -> relationship signals
    sig_dict = await classify_signals(message, recent_ctx, CONVO_ANALYZER)
    sig = Signals(**sig_dict)

    # 4) Update dimensions + state
    out = update_relationship(
        trust=rel.trust,
        closeness=rel.closeness,
        attraction=rel.attraction,
        safety=rel.safety,
        prev_state=rel.state,
        sig=sig,
    )

    rel.trust = out.trust
    rel.closeness = out.closeness
    rel.attraction = out.attraction
    rel.safety = out.safety

    # 5) Apply accepts from user
    # --- stage points update (controls state progression) ---
    delta = (
        2.0 * sig.support +
        1.6 * sig.affection +
        1.6 * sig.respect +
        1.4 * sig.flirt -
        5.0 * sig.boundary_push -
        3.5 * sig.rude
    )

    # baseline so it doesn't stall at 0 for normal messages
    baseline = 0.25 if (sig.rude < 0.1 and sig.boundary_push < 0.1) else 0.0
    delta += baseline

    delta = max(-5.0, min(3.0, delta))
    rel.stage_points = max(0.0, min(100.0, (rel.stage_points or 0.0) + delta))

    # derive state from points (no skipping)
    p = rel.stage_points
    if p < 20:
        rel.state = "STRANGERS"
    elif p < 45:
        rel.state = "TALKING"
    elif p < 65:
        rel.state = "FLIRTING"
    elif p < 85:
        rel.state = "DATING"
    else:
        rel.state = "DATING"  # girlfriend still requires explicit yes

    # eligibility based on final state + dimensions
    can_ask = (
        rel.state == "DATING"
        and rel.safety >= 70
        and rel.trust >= 75
        and rel.closeness >= 70
        and rel.attraction >= 65
    )

    # Apply accepts AFTER state is derived
    if sig.accepted_exclusive and rel.state in ("DATING", "GIRLFRIEND"):
        rel.exclusive_agreed = True

    if sig.accepted_girlfriend and can_ask:
        rel.girlfriend_confirmed = True
        rel.exclusive_agreed = True
        rel.state = "GIRLFRIEND"

    # keep girlfriend sticky
    if rel.girlfriend_confirmed:
        rel.state = "GIRLFRIEND"

    # Plan gradual DTR goal (no button)
    dtr_goal = plan_dtr_goal(rel, can_ask)

    # 6) Plan gradual DTR goal (no button)
    can_ask = (rel.state == "DATING" and rel.safety >= 70 and rel.trust >= 75 and rel.closeness >= 70 and rel.attraction >= 65)
    dtr_goal = plan_dtr_goal(rel, can_ask)

    # 7) Update last interaction
    rel.last_interaction_at = now
    rel.updated_at = now

    db.add(rel)
    await db.commit()
    await db.refresh(rel)

    persona_rules = influencer.prompt_template.format(
        relationship_state=rel.state,
        trust=int(rel.trust),
        closeness=int(rel.closeness),
        attraction=int(rel.attraction),
        safety=int(rel.safety),
    )

    persona_rules += f"""
    RELATIONSHIP:
    - phase: {rel.state}
    - trust: {rel.trust:.0f}/100
    - closeness: {rel.closeness:.0f}/100
    - attraction: {rel.attraction:.0f}/100
    - safety: {rel.safety:.0f}/100
    - exclusive_agreed: {rel.exclusive_agreed}
    - girlfriend_confirmed: {rel.girlfriend_confirmed}
    - days_idle_before_message: {days_idle:.1f}
    - dtr_goal: {dtr_goal}

    DTR rules:
    - hint_closer: subtle romantic closeness, 'we' language, no pressure.
    - ask_exclusive: gently ask if user wants exclusivity (only us).
    - ask_girlfriend: ask clearly (romantic) if you can be their girlfriend.
    - If safety is low or user is upset: do NOT push DTR.

    Behavior by phase:
    - STRANGERS/TALKING: light, curious, build trust.
    - FLIRTING: playful flirting, teasing, no pressure.
    - DATING: affectionate, can discuss exclusivity.
    - GIRLFRIEND: consistent girlfriend vibe, affectionate, supportive, 'we' language.
    - STRAINED: boundaries first, reduce romance, repair needed.
    """
    
    memories_result = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    if isinstance(memories_result, tuple):
        memories = memories_result[0]
    else:
        memories = memories_result
    
    mem_block = "\n".join(
        s for s in (_norm(m) for m in memories or []) if s
    )

    prompt = prompt_template.partial(
        analysis=analysis_summary,

        relationship_state=rel.state,
        trust=int(rel.trust),
        closeness=int(rel.closeness),
        attraction=int(rel.attraction),
        safety=int(rel.safety),
        exclusive_agreed=rel.exclusive_agreed,
        girlfriend_confirmed=rel.girlfriend_confirmed,
        days_idle_before_message=round(days_idle, 1),
        dtr_goal=dtr_goal,

        persona_rules=persona_rules,
        memories=mem_block,
        daily_context=daily_context,
        last_user_message=message,
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
