import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.db.models import Influencer
from app.relationship.repo import get_or_create_relationship
from app.relationship.inactivity import apply_inactivity_decay
from app.relationship.signals import classify_signals
from app.relationship.engine import Signals, update_relationship
from app.relationship.dtr import plan_dtr_goal

log = logging.getLogger("teaseme-relationship")

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

    # 1) Load relationship row from DB
    rel = await get_or_create_relationship(db, int(user_id), influencer_id)

    # 2) Inactivity decay (if user disappeared for days)
    days_idle = apply_inactivity_decay(rel, now)

    if influencer is None:
        influencer = await db.get(Influencer, influencer_id)
    if influencer is None:
        raise ValueError(f"Influencer not found: {influencer_id}")

    # --- Persona preferences from bio_json ---
    bio = influencer.bio_json or {}

    persona_likes: List[str] = bio.get("likes", []) or []
    persona_dislikes: List[str] = bio.get("dislikes", []) or []

    # Ensure lists (defensive)
    if not isinstance(persona_likes, list):
        persona_likes = []
    if not isinstance(persona_dislikes, list):
        persona_dislikes = []

    # 3) Classify user message -> relationship signals
    sig_dict = await classify_signals(
        message, recent_ctx, persona_likes, persona_dislikes, convo_analyzer
    )
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

    # 7) Update last interaction
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
