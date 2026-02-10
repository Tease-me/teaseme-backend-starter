import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.db.models import Influencer
from app.relationship.repo import get_or_create_relationship
from app.relationship.inactivity import apply_inactivity_decay, check_and_trigger_reengagement
from app.relationship.signals import classify_signals
from app.relationship.engine import Signals, update_relationship
from app.relationship.dtr import plan_dtr_goal

log = logging.getLogger("teachme-relationship")


STAGES = ["HATE", "DISLIKE", "STRANGERS", "FRIENDS", "FLIRTING", "DATING", "GIRLFRIEND"]


def stage_from_signals_and_points(stage_points: float, sig) -> str:
  """
  Determine relationship stage PURELY from accumulated stage_points.
  
  Thresholds:
  - HATE: -11 or less (accumulated negative interactions)
  - DISLIKE: -10 to -1 (negative relationship)
  - STRANGERS: 0-24 (neutral, building connection)
  - FRIENDS: 25-49 (friendly relationship)
  - FLIRTING: 50-74 (romantic interest)
  - DATING: 75-89 (committed relationship)
  - GIRLFRIEND: 90-100 (ultimate level)
  
  Note: Signals affect the DELTA (how points change), not the stage directly.
  Stage is determined by the cumulative points total.
  """
  p = float(stage_points or 0.0)
  
  # Pure points-based progression
  if p <= -11.0:
      return "HATE"
  if p < 0.0:
      return "DISLIKE"
  if p < 25.0:
      return "STRANGERS"
  if p < 50.0:
      return "FRIENDS"
  if p < 75.0:
      return "FLIRTING"
  if p < 90.0:
      return "DATING"
  return "GIRLFRIEND"


def compute_stage_delta(sig) -> float:
  delta = (
      2.0 * sig.support +
      1.6 * sig.affection +
      1.6 * sig.respect +
      1.4 * sig.flirt
  )

  delta -= 5.0 * sig.boundary_push
  delta -= 3.5 * sig.rude

  delta -= 4.0 * getattr(sig, "dislike", 0.0)
  delta -= 8.0 * getattr(sig, "hate", 0.0)
  delta -= 10.0 * getattr(sig, "threat", 0.0)
  delta -= 4.0 * getattr(sig, "rejecting", 0.0)
  delta -= 2.0 * getattr(sig, "insult", 0.0)

  baseline = 0.25 if (
      sig.rude < 0.1 and sig.boundary_push < 0.1
      and getattr(sig, "dislike", 0.0) < 0.1
      and getattr(sig, "hate", 0.0) < 0.1
      and getattr(sig, "threat", 0.0) < 0.05
      and getattr(sig, "rejecting", 0.0) < 0.1
  ) else 0.0

  delta += baseline

  return max(-8.0, min(3.0, delta))


def compute_sentiment_delta(sig) -> float:
  """
  Calculate sentiment change from interaction signals.
  Returns a value between -3.0 and +2.0 for gradual sentiment shifts.
  """
  d = (
      + 2.0*sig.respect
      + 2.0*sig.support
      + 1.5*sig.affection
      + 2.0*sig.apology
      - 3.0*sig.rude
      - 4.0*sig.boundary_push
      - 2.5*getattr(sig, "dislike", 0.0)
      - 5.0*getattr(sig, "hate", 0.0)
      - 6.0*getattr(sig, "threat", 0.0)
      - 2.0*getattr(sig, "insult", 0.0)
      - 2.0*getattr(sig, "rejecting", 0.0)
  )
  return max(-3.0, min(2.0, d))


async def process_relationship_turn(
    *,
    db,
    user_id: int,
    influencer_id: str,
    message: str,
    recent_ctx: str,
    cid: str,
    convo_analyzer,
    influencer: Any | None = None,
) -> Dict[str, Any]:
    """
    Shared relationship update pipeline used by chat turns and webhooks.
    Returns the updated RelationshipState plus derived metadata.
    """
    now = datetime.now(timezone.utc)
    log.info("[REL %s] START user_id=%s influencer_id=%s", cid, user_id, influencer_id)

    rel = await get_or_create_relationship(db, int(user_id), influencer_id)

    days_idle = apply_inactivity_decay(rel, now)

    if days_idle >= 3:
        await check_and_trigger_reengagement(
            db=db,
            user_id=int(user_id),
            influencer_id=influencer_id,
            days_idle=days_idle,
        )

    if influencer is None:
        influencer = await db.get(Influencer, influencer_id)
    if influencer is None:
        raise ValueError(f"Influencer not found: {influencer_id}")

    bio = influencer.bio_json or {}

    from app.services.preference_service import (
        get_persona_preference_labels,
        compute_preference_alignment,
    )
    persona_likes, persona_dislikes, _ = await get_persona_preference_labels(db, influencer_id)

    sig_dict = await classify_signals(
        db, message, recent_ctx, persona_likes, persona_dislikes, convo_analyzer
    )
    log.info("[%s] SIG_DICT=%s", cid, sig_dict)
    sig = Signals(**sig_dict)

    d_sent = compute_sentiment_delta(sig)
    prev_sentiment = float(rel.sentiment_score or 0.0)
    new_sentiment = max(-100.0, min(100.0, prev_sentiment + d_sent))
    
    rel.sentiment_score = new_sentiment
    rel.sentiment_delta = d_sent

    # For girlfriends, reduce negative signal impact by 60% (they're more forgiving)
    if rel.girlfriend_confirmed:
        dampened_sig = Signals(
            support=sig.support,
            affection=sig.affection,
            flirt=sig.flirt,
            respect=sig.respect,
            rude=sig.rude * 0.4,  # Reduce negative signals
            boundary_push=sig.boundary_push * 0.4,
            dislike=getattr(sig, 'dislike', 0.0) * 0.4,
            hate=getattr(sig, 'hate', 0.0) * 0.4,
            apology=sig.apology,
            commitment_talk=sig.commitment_talk,
            accepted_exclusive=sig.accepted_exclusive,
            accepted_girlfriend=sig.accepted_girlfriend,
        )
        out = update_relationship(rel.trust, rel.closeness, rel.attraction, rel.safety, rel.state, dampened_sig)
    else:
        out = update_relationship(rel.trust, rel.closeness, rel.attraction, rel.safety, rel.state, sig)

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

    prev_sp = float(rel.stage_points or 0.0)
    delta = compute_stage_delta(sig)

    alignment = await compute_preference_alignment(db, int(user_id), influencer_id)
    pref_bonus = alignment * 0.3
    delta += pref_bonus
    delta = max(-8.0, min(3.0, delta))

    rel.stage_points = max(-20.0, min(100.0, prev_sp + delta))  # Allow negative points down to -20

    # CHECK girlfriend_confirmed FIRST to preserve relationship status
    if rel.girlfriend_confirmed:
        # Once girlfriend, maintain at least GIRLFRIEND level unless serious negative interaction
        if sig.hate > 0.6 or getattr(sig, "threat", 0.0) > 0.20:
            rel.state = "HATE"
            rel.girlfriend_confirmed = False  # Reset on severe negativity
            rel.exclusive_agreed = False
        elif sig.dislike > 0.4 or getattr(sig, "rejecting", 0.0) > 0.40:
            rel.state = "DISLIKE"
            rel.girlfriend_confirmed = False
            rel.exclusive_agreed = False
        else:
            rel.state = "GIRLFRIEND"  # Keep as girlfriend
    else:
        # Normal state calculation for non-girlfriends
        rel.state = stage_from_signals_and_points(rel.stage_points, sig)

    can_ask = (
        rel.state == "DATING"
        and rel.safety >= 70
        and rel.trust >= 75
        and rel.closeness >= 70
        and rel.attraction >= 65
    )

    if rel.state in ("HATE", "DISLIKE"):
        can_ask = False

    if sig.accepted_exclusive and rel.state in ("DATING", "GIRLFRIEND"):
        rel.exclusive_agreed = True

    if sig.accepted_girlfriend and can_ask:
        rel.girlfriend_confirmed = True
        rel.exclusive_agreed = True
        rel.state = "GIRLFRIEND"

    dtr_goal = plan_dtr_goal(rel, can_ask)

    log.info(
        "[%s] STAGE prev=%.2f delta=%.2f new=%.2f state=%s can_ask=%s",
        cid, prev_sp, delta, rel.stage_points, rel.state, can_ask
    )

    rel.last_interaction_at = now
    rel.updated_at = now

    log.info(
        "[REL %s] BEFORE COMMIT id=%s user=%s infl=%s trust=%.4f close=%.4f attr=%.4f safe=%.4f sp=%.2f state=%s sent=%.2f",
        cid,
        getattr(rel, "id", None),
        rel.user_id,
        rel.influencer_id,
        rel.trust, rel.closeness, rel.attraction, rel.safety,
        float(rel.stage_points or 0.0),
        rel.state,
        float(rel.sentiment_score or 0.0),
    )

    db.add(rel)
    await db.commit()
    await db.refresh(rel)

    log.info(
        "[REL %s] AFTER COMMIT updated_at=%s trust=%.4f sp=%.2f state=%s",
        cid,
        rel.updated_at,
        rel.trust,
        float(rel.stage_points or 0.0),
        rel.state,
    )

    return {
        "rel": rel,
        "sig": sig,
        "persona_likes": persona_likes,
        "persona_dislikes": persona_dislikes,
        "days_idle": days_idle,
        "dtr_goal": dtr_goal,
        "can_ask": can_ask,
        "timestamp": now,
    }
