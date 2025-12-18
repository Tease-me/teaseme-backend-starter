import logging,asyncio
from uuid import uuid4
from app.core.config import settings
from app.agents.memory import find_similar_memories, store_fact
from app.agents.prompts import MODEL, FACT_EXTRACTOR, CONVO_ANALYZER, get_fact_prompt
from app.db.session import SessionLocal
from app.agents.prompt_utils import get_global_prompt, get_today_script
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

STAGES = ["HATE", "DISLIKE", "STRANGERS", "TALKING", "FLIRTING", "DATING"]

def stage_from_signals_and_points(stage_points: float, sig) -> str:
    # HARD NEGATIVE overrides
    if getattr(sig, "threat", 0.0) > 0.20 or getattr(sig, "hate", 0.0) > 0.60:
        return "HATE"
    if getattr(sig, "dislike", 0.0) > 0.40 or getattr(sig, "rejecting", 0.0) > 0.40:
        return "DISLIKE"

    # Positive progression by points
    p = float(stage_points or 0.0)
    if p < 20.0:
        return "STRANGERS"
    if p < 45.0:
        return "TALKING"
    if p < 65.0:
        return "FLIRTING"
    return "DATING"


def compute_stage_delta(sig) -> float:
    # Positive contributions
    delta = (
        2.0 * sig.support +
        1.6 * sig.affection +
        1.6 * sig.respect +
        1.4 * sig.flirt
    )

    # Existing negatives
    delta -= 5.0 * sig.boundary_push
    delta -= 3.5 * sig.rude

    # New negatives
    delta -= 4.0 * getattr(sig, "dislike", 0.0)
    delta -= 8.0 * getattr(sig, "hate", 0.0)
    delta -= 10.0 * getattr(sig, "threat", 0.0)
    delta -= 4.0 * getattr(sig, "rejecting", 0.0)
    delta -= 2.0 * getattr(sig, "insult", 0.0)

    # Baseline only if message is non-negative overall
    baseline = 0.25 if (
        sig.rude < 0.1 and sig.boundary_push < 0.1
        and getattr(sig, "dislike", 0.0) < 0.1
        and getattr(sig, "hate", 0.0) < 0.1
        and getattr(sig, "threat", 0.0) < 0.05
        and getattr(sig, "rejecting", 0.0) < 0.1
    ) else 0.0

    delta += baseline

    # Allow stronger downward movement than upward (more realistic)
    return max(-8.0, min(3.0, delta))


def compute_sentiment_delta(sig) -> float:
    d = (
        + 6*sig.respect
        + 6*sig.support
        + 4*sig.affection
        + 6*sig.apology
        -10*sig.rude
        -14*sig.boundary_push
        - 8*getattr(sig, "dislike", 0.0)
        -16*getattr(sig, "hate", 0.0)
        -20*getattr(sig, "threat", 0.0)
        - 6*getattr(sig, "insult", 0.0)
        - 6*getattr(sig, "rejecting", 0.0)
    )
    # cap per message
    return max(-10.0, min(5.0, d))

async def handle_turn(message: str, chat_id: str, influencer_id: str, user_id: str | None = None, db=None, is_audio: bool = False) -> str:
    cid = uuid4().hex[:8]
    
    log.info("[%s] START persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])

    # Gather all independent async operations
    influencer, prompt_template, daily_context = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_global_prompt(db, is_audio),
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

    # --- Persona preferences from bio_json ---
    bio = influencer.bio_json or {}

    persona_likes = bio.get("likes", [])
    persona_dislikes = bio.get("dislikes", [])

    # Ensure lists (defensive)
    if not isinstance(persona_likes, list):
        persona_likes = []
    if not isinstance(persona_dislikes, list):
        persona_dislikes = []

    # 3) Classify user message -> relationship signals
    sig_dict = await classify_signals(message, recent_ctx,persona_likes, persona_dislikes, CONVO_ANALYZER)
    log.info("[%s] SIG_DICT=%s", cid, sig_dict)
    sig = Signals(**sig_dict)

    # --- sentiment_score (-100..100): Sims-like mood (can be negative) ---
    d_sent = compute_sentiment_delta(sig)
    rel.sentiment_score = max(
        -100.0,
        min(100.0, float(rel.sentiment_score or 0.0) + d_sent)
    )

    # 4) Update dimensions (trust/closeness/attraction/safety)
    out = update_relationship(rel.trust, rel.closeness, rel.attraction, rel.safety, sig)

    log.info(
        "[%s] DIM before->after | t %.4f->%.4f c %.4f->%.4f a %.4f->%.4f s %.4f->%.4f",
        cid,
        rel.trust, out.trust,
        rel.closeness, out.closeness,
        rel.attraction, out.attraction,
        rel.safety, out.safety,
    )

    rel.trust = out.trust
    rel.closeness = out.closeness
    rel.attraction = out.attraction
    rel.safety = out.safety

    # --- stage points update (controls state progression) ---
    prev_sp = float(rel.stage_points or 0.0)
    delta = compute_stage_delta(sig)
    rel.stage_points = max(0.0, min(100.0, prev_sp + delta))

    # Derive stage from BOTH points and negative dominance
    rel.state = stage_from_signals_and_points(rel.stage_points, sig)

    # eligibility based on final state + dimensions
    # (Only allow girlfriend/exclusive talk if not in negative stages)
    can_ask = (
        rel.state == "DATING"
        and rel.safety >= 70
        and rel.trust >= 75
        and rel.closeness >= 70
        and rel.attraction >= 65
    )

    # Block commitment if user is in DISLIKE/HATE
    if rel.state in ("HATE", "DISLIKE"):
        can_ask = False

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

    dtr_goal = plan_dtr_goal(rel, can_ask)

    log.info(
        "[%s] STAGE prev=%.2f delta=%.2f new=%.2f state=%s can_ask=%s",
        cid, prev_sp, delta, rel.stage_points, rel.state, can_ask
    )

    log.info("[%s] STAGE prev=%.2f delta=%.2f new=%.2f state=%s can_ask=%s",
            cid, prev_sp, delta, rel.stage_points, rel.state, can_ask)
    # 7) Update last interaction
    rel.last_interaction_at = now
    rel.updated_at = now

    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    
    memories_result = await find_similar_memories(db, chat_id, message) if (db and user_id) else []
    if isinstance(memories_result, tuple):
        memories = memories_result[0]
    else:
        memories = memories_result
    
    mem_block = "\n".join(
        s for s in (_norm(m) for m in memories or []) if s
    )

    stages = bio.get("stages", {})

    dating_stage = stages["dating"]
    dislike_stage = stages["dislike"]
    talking_stage = stages["talking"]
    flirting_stage = stages["flirting"]
    hate_stage = stages["hate"]
    strangers_stage = stages["strangers"]
    in_love_stage = stages["in_love"]

    mbti_rules = bio.get("mbti_rules", "")
    personality_rules = bio.get("personality_rules", "")
    tone=bio.get("tone", "")

    prompt = prompt_template.partial(
        relationship_state=rel.state,
        trust=int(rel.trust),
        closeness=int(rel.closeness),
        attraction=int(rel.attraction),
        safety=int(rel.safety),
        exclusive_agreed=rel.exclusive_agreed,
        girlfriend_confirmed=rel.girlfriend_confirmed,
        days_idle_before_message=round(days_idle, 1),
        dtr_goal=dtr_goal,
        personality_rules=personality_rules,
        dating_stage=dating_stage,
        dislike_stage=dislike_stage,
        talking_stage=talking_stage,
        flirting_stage=flirting_stage,
        hate_stage=hate_stage,
        strangers_stage=strangers_stage,
        in_love_stage=in_love_stage,
        likes=", ".join(map(str, persona_likes or [])),
        dislikes=", ".join(map(str, persona_dislikes or [])),
        mbti_rules=mbti_rules,
        memories=mem_block,
        daily_context=daily_context,
        last_user_message=message,
        tone=tone,
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
