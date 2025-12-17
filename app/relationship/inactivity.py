from datetime import datetime, timezone

def apply_inactivity_decay(rel, now: datetime) -> float:
    # returns days_idle for logging
    last = rel.last_interaction_at or rel.updated_at
    if not last:
        return 0.0

    days_idle = (now - last).total_seconds() / 86400.0
    if days_idle < 2:
        return days_idle

    # closeness cools down
    rel.closeness = max(0.0, rel.closeness - min(8.0, days_idle * 1.5))

    # attraction cools down a bit faster
    if days_idle >= 3:
        rel.attraction = max(0.0, rel.attraction - min(10.0, days_idle * 1.8))

    # trust only slightly after long gaps
    if days_idle >= 7:
        rel.trust = max(0.0, rel.trust - min(5.0, (days_idle - 6) * 0.8))

    # safety does not decay by time
    return days_idle