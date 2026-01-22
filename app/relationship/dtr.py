from datetime import datetime, timedelta, timezone

def _now():
    return datetime.now(timezone.utc)

def cooldown_ok(rel) -> bool:
    return rel.dtr_cooldown_until is None or rel.dtr_cooldown_until <= _now()

def plan_dtr_goal(rel, can_ask_gf: bool) -> str:
  
    if rel.girlfriend_confirmed:
        return "none"

    if not cooldown_ok(rel):
        return "none"

    if rel.state in ("HATE", "DISLIKE"):
        return "none"

    if (rel.safety or 0) < 55:
        return "none"

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

    if (
        rel.dtr_stage == 1
        and not rel.exclusive_agreed
        and rel.state == "DATING"
        and can_ask_gf 
    ):
        rel.dtr_stage = 2
        rel.dtr_cooldown_until = _now() + timedelta(hours=12)
        return "ask_exclusive"

    if (
        rel.dtr_stage == 2
        and rel.exclusive_agreed
        and can_ask_gf
    ):
        rel.dtr_stage = 3
        rel.dtr_cooldown_until = _now() + timedelta(hours=24)
        return "ask_girlfriend"

    return "none"