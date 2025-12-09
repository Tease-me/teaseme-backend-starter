import re
from redis import Redis
from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
SCORE_KEY = "lollity:v2:{user}:{persona}"
# Legacy key for migration
LEGACY_SCORE_KEY = "lollity:{user}:{persona}"

SCORE_RECOVERY_KEY = "lollity_cooldown:{user}:{persona}"

# Regex to catch older logs or prompts if needed, though we will rely on structured new data
SCORE_RE = re.compile(r"\[Lollity Score: (\d{1,3}(?:\.\d{1,2})?)/100]")

import time

_DEFAULT_INTIMACY = 3.0
_DEFAULT_PASSION = 3.0
_DEFAULT_COMMITMENT = 0.0  # Starts lower

# Decay rates per hour
DECAY_RATES = {
    "passion": 0.5,    # Fast decay (-12/day)
    "intimacy": 0.1,   # Slow decay (-2.4/day)
    "commitment": 0.0  # No natural decay
}

_MAX_UP_GAIN = 0.5
_COOLDOWN_GAIN = 0.25
_MAX_COOLDOWN = 4


def get_score(user: str, persona: str) -> dict:
    """
    Returns a dict with keys: intimacy, passion, commitment.
    Applies time-based decay since last interaction.
    """
    key_v2 = SCORE_KEY.format(user=user, persona=persona)
    stored = redis_client.hgetall(key_v2)

    now = time.time()

    if stored:
        triad = {
            "intimacy": float(stored.get("intimacy", _DEFAULT_INTIMACY)),
            "passion": float(stored.get("passion", _DEFAULT_PASSION)),
            "commitment": float(stored.get("commitment", _DEFAULT_COMMITMENT)),
        }
        last_ts = float(stored.get("last_interaction", now))
        
        # Apply decay
        decay_report = {}
        elapsed_hours = (now - last_ts) / 3600
        if elapsed_hours > 1.0: # Only decay if > 1 hour passed
            needs_update = False
            for k, rate in DECAY_RATES.items():
                if rate > 0 and triad[k] > 0:
                    loss = elapsed_hours * rate
                    if loss > 0:
                        # Don't decay below 0
                        actual_loss = min(triad[k], loss)
                        triad[k] -= actual_loss
                        decay_report[k] = -actual_loss
                        needs_update = True
            
            # If we applied decay, update the stored values + timestamp to now
            # so we don't double-decay next time.
            if needs_update:
                to_save = triad.copy()
                to_save["last_interaction"] = now
                redis_client.hset(key_v2, mapping=to_save)
                redis_client.expire(key_v2, settings.SCORE_TTL)
        
        # Inject metadata (not saved to Redis)
        triad["_last_decay"] = decay_report
        triad["_hours_since_last_interaction"] = elapsed_hours

        return triad

    # fallback / migration
    legacy_key = LEGACY_SCORE_KEY.format(user=user, persona=persona)
    legacy_val = redis_client.get(legacy_key)
    
    if legacy_val is not None:
        old_score = float(legacy_val)
        triad = {
            "intimacy": old_score,
            "passion": old_score,
            "commitment": old_score * 0.2
        }
    else:
        triad = {
            "intimacy": _DEFAULT_INTIMACY,
            "passion": _DEFAULT_PASSION,
            "commitment": _DEFAULT_COMMITMENT
        }
    
    # Save initialized values + timestamp
    to_save = triad.copy()
    to_save["last_interaction"] = now
    
    redis_client.hset(key_v2, mapping=to_save)
    redis_client.expire(key_v2, settings.SCORE_TTL)
    
    return triad


def update_score(user: str, persona: str, components: dict) -> dict:
    """
    Updates the triad scores and resets the decay timer (last_interaction = now).
    """
    key_v2 = SCORE_KEY.format(user=user, persona=persona)
    
    # We get_score first to ensure we have the latest base (including any decay that just happened)
    current = get_score(user, persona)
    
    new_state = current.copy()
    
    # Clean up internal metadata that shouldn't be saved to Redis
    new_state.pop("_last_decay", None)
    
    for k in ["intimacy", "passion", "commitment"]:
        if k in components:
            val = float(components[k])
            # Bound between 0 and 100
            val = max(0.0, min(100.0, val))
            new_state[k] = val
            
    # Always update timestamp on interaction
    new_state["last_interaction"] = time.time()
            
    redis_client.hset(key_v2, mapping=new_state)
    redis_client.expire(key_v2, settings.SCORE_TTL)
    
    return new_state



# Regex for Love Triad: e.g., [Relations: Intimacy=50, Passion=60, Commitment=10]
# Flexible on spacing and exact keywords to allow model variance
TRIAD_RE = re.compile(
    r"\[Relations:.*?"
    r"Intimacy\s*=\s*(\d+).*?"
    r"Passion\s*=\s*(\d+).*?"
    r"Commitment\s*=\s*(\d+).*?\]",
    re.IGNORECASE | re.DOTALL
)

def extract_triad_scores(text: str, current_scores: dict) -> dict:
    """
    Parses the text for [Relations: Intimacy=X, Passion=Y, Commitment=Z].
    Returns a new dict merged with current scores if found.
    If not found, returns current_scores as is.
    """
    m = TRIAD_RE.search(text)
    if not m:
        return current_scores
        
    try:
        i = float(m.group(1))
        p = float(m.group(2))
        c = float(m.group(3))
        
        return {
            "intimacy": max(0.0, min(100.0, i)),
            "passion": max(0.0, min(100.0, p)),
            "commitment": max(0.0, min(100.0, c)),
        }
    except (ValueError, IndexError):
        return current_scores

def format_score_value(score: float | dict) -> str:
    """
    Handles both legacy float and new dict.
    """
    if isinstance(score, dict):
        i = int(score.get("intimacy", 0))
        p = int(score.get("passion", 0))
        c = int(score.get("commitment", 0))
        return f"I:{i}/P:{p}/C:{c}"
        
    display = f"{score:.2f}".rstrip("0").rstrip(".")
    return display if display else "0"
