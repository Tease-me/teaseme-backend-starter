import asyncio
import logging
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import Influencer, Message18
from app.agents.prompt_utils import get_global_prompt, get_today_script, build_relationship_prompt
from app.agents.prompts import MODEL

log = logging.getLogger("teaseme-turn-18")


def _render_recent_ctx(rows: list[Message18]) -> str:
    lines = []
    for m in rows:
        role = "user" if (m.sender or "").lower() == "user" else "ai"
        txt = (m.content or "").strip()
        if txt:
            lines.append(f"{role}: {txt}")
    return "\n".join(lines)


async def _load_recent_ctx_18(db, chat_id: str, limit: int = 12) -> str:
    q = (
        select(Message18)
        .where(Message18.chat_id == chat_id)
        .order_by(Message18.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(q)
    rows = list(res.scalars().all())
    rows.reverse()  # oldest -> newest
    return _render_recent_ctx(rows)


async def handle_turn_18(
    *,
    message: str,
    chat_id: str,
    influencer_id: str,
    user_id: int,  # kept for signature compatibility, not used
    db,
) -> str:
    cid = uuid4().hex[:8]
    log.info("[%s] START(18) persona=%s chat=%s user=%s", cid, influencer_id, chat_id, user_id)

    influencer, prompt_template, daily_context, recent_ctx = await asyncio.gather(
        db.get(Influencer, influencer_id),
        get_global_prompt(db, is_audio=False),
        get_today_script(db=db, influencer_id=influencer_id),
        _load_recent_ctx_18(db, chat_id, limit=12),
    )

    if not influencer:
        raise HTTPException(404, "Influencer not found")

    bio = influencer.bio_json or {}
    tone = bio.get("tone", "")
    mbti_rules = bio.get("mbti_rules", "")
    personality_rules = bio.get("personality_rules", "")
    stages = bio.get("stages", {})
    if not isinstance(stages, dict):
        stages = {}

    # ✅ We reuse build_relationship_prompt, but with a "fake" lightweight rel object
    # so we don't need RelationshipState at all.
    class _Rel:
        state = "STRANGERS"
        trust = 0.0
        closeness = 0.0
        attraction = 0.0
        safety = 100.0
        exclusive_agreed = False
        girlfriend_confirmed = False
        stage_points = 0.0
        sentiment_score = 0.0

    prompt = build_relationship_prompt(
        prompt_template,
        rel=_Rel(),                 # <-- no DB row
        days_idle=0,
        dtr_goal="",
        personality_rules=personality_rules,
        stages=stages,
        persona_likes=[],
        persona_dislikes=[],
        mbti_rules=mbti_rules,
        memories="",
        daily_context=daily_context,
        last_user_message=message,
        tone=tone,
        persona_rules=getattr(influencer, "prompt_template", "") or "",
    )

    # Add DB history into the input (so the model has context)
    # If your prompt template already consumes "history", keep this.
    chain = prompt | MODEL

    try:
        result = await chain.ainvoke(
            {"input": message, "history": recent_ctx}
        )
        reply = getattr(result, "content", None) or str(result)
        return reply
    except Exception as e:
        log.error("[%s] LLM error: %s", cid, e, exc_info=True)
        return "Sorry, something went wrong. 😔"