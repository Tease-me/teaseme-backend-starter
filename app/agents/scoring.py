import re
from redis import Redis
from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
SCORE_KEY = "lollity:{user}:{persona}"
SCORE_RECOVERY_KEY = "lollity_cooldown:{user}:{persona}"
SCORE_RE = re.compile(r"\[Lollity Score: (\d{1,3}(?:\.\d{1,2})?)/100]")
_DEFAULT_SCORE = 3.0
_MAX_UP_GAIN = 0.5
_COOLDOWN_GAIN = 0.25
_MAX_COOLDOWN = 4

def get_score(user: str, persona: str) -> float:
    key = SCORE_KEY.format(user=user, persona=persona)
    stored = redis_client.get(key)
    return float(stored) if stored is not None else _DEFAULT_SCORE

def update_score(user: str, persona: str, new_score: float) -> float:
    key = SCORE_KEY.format(user=user, persona=persona)
    cooldown_key = SCORE_RECOVERY_KEY.format(user=user, persona=persona)
    current_raw = redis_client.get(key)
    current_score = float(current_raw) if current_raw is not None else _DEFAULT_SCORE
    cooldown_raw = redis_client.get(cooldown_key)
    cooldown = int(cooldown_raw) if cooldown_raw is not None else 0
    bounded = max(0.0, min(100.0, float(new_score)))
    if bounded > current_score:
        max_gain = _COOLDOWN_GAIN if cooldown > 0 else _MAX_UP_GAIN
        bounded = min(current_score + max_gain, bounded)
        if bounded > current_score and cooldown > 0:
            cooldown = max(0, cooldown - 1)
    elif bounded < current_score:
        drop = current_score - bounded
        drop_penalty = max(1, int(drop // 2) if drop >= 2 else 1)
        cooldown = min(_MAX_COOLDOWN, cooldown + drop_penalty)
    redis_client.set(key, bounded, ex=settings.SCORE_TTL)
    if cooldown > 0:
        redis_client.set(cooldown_key, cooldown, ex=settings.SCORE_TTL)
    else:
        redis_client.delete(cooldown_key)
    return bounded

def extract_score(text: str, default: float) -> float:
    m = SCORE_RE.search(text)
    return max(0.0, min(100.0, float(m.group(1)))) if m else default


def format_score_value(score: float) -> str:
    display = f"{score:.2f}".rstrip("0").rstrip(".")
    return display if display else "0"
