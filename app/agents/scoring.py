import re
from redis import Redis
from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
SCORE_KEY = "lollity:{user}:{persona}"
SCORE_RE = re.compile(r"\[Lollity Score: (\d{1,3})/100]")

def get_score(user: str, persona: str) -> int:
    key = SCORE_KEY.format(user=user, persona=persona)
    return int(redis_client.get(key) or 50)

def update_score(user: str, persona: str, new_score: int):
    key = SCORE_KEY.format(user=user, persona=persona)
    current_raw = redis_client.get(key)
    current_score = int(current_raw) if current_raw is not None else 50
    bounded = max(0, min(100, new_score))
    if bounded > current_score:
        bounded = min(current_score + 3, bounded)
    redis_client.set(key, bounded, ex=settings.SCORE_TTL)

def extract_score(text: str, default: int) -> int:
    m = SCORE_RE.search(text)
    return max(0, min(100, int(m.group(1)))) if m else default
