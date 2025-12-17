from datetime import datetime, timedelta, timezone

def _now():
    return datetime.now(timezone.utc)

def cooldown_ok(rel) -> bool:
    return rel.dtr_cooldown_until is None or rel.dtr_cooldown_until <= _now()

def plan_dtr_goal(rel, can_ask_gf: bool) -> str:
    """
    Returns: "none" | "hint_closer" | "ask_exclusive" | "ask_girlfriend"
    Also updates rel.dtr_stage + cooldown.

    Notes:
    - Uses your stages: HATE, DISLIKE, STRANGERS, TALKING, FLIRTING, DATING (+ GIRLFRIEND sticky)
    - DTR goals are disabled during negative stages or low safety.
    """
    # already girlfriend -> no DTR
    if rel.girlfriend_confirmed:
        return "none"

    # cooldown gate
    if not cooldown_ok(rel):
        return "none"

    # negative stages gate (new)
    if rel.state in ("HATE", "DISLIKE"):
        return "none"

    # safety gate (acts like your old "STRAINED")
    if (rel.safety or 0) < 55:
        return "none"

    # Stage 0 -> 1: subtle closeness
    if (
        rel.dtr_stage == 0
        and rel.state in ("FLIRTING", "DATING")
        and rel.trust >= 60
        and rel.closeness >= 55
        and rel.safety >= 65
    ):
        rel.dtr_stage = 1
        rel.dtr_cooldown_until = _now() + timedelta(hours=6)
        return "hint_closer"

    # Stage 1 -> 2: exclusivity talk
    # Only if not already exclusive and we're in DATING
    if (
        rel.dtr_stage == 1
        and not rel.exclusive_agreed
        and rel.state == "DATING"
        and can_ask_gf  # your eligibility gate
    ):
        rel.dtr_stage = 2
        rel.dtr_cooldown_until = _now() + timedelta(hours=12)
        return "ask_exclusive"

    # Stage 2 -> 3: girlfriend ask
    if (
        rel.dtr_stage == 2
        and rel.exclusive_agreed
        and can_ask_gf
    ):
        rel.dtr_stage = 3
        rel.dtr_cooldown_until = _now() + timedelta(hours=24)
        return "ask_girlfriend"

    return "none"