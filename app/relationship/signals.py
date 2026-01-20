import json
from app.services.system_prompt_service import get_system_prompt
from app.db.session import get_db
db = get_db()
DEFAULT = {
    "support": 0.0, "affection": 0.0, "flirt": 0.0, "respect": 0.0,
    "apology": 0.0, "commitment_talk": 0.0,

    "rude": 0.0, "boundary_push": 0.0,
    "dislike": 0.0, "hate": 0.0,

    "accepted_exclusive": False,
    "accepted_girlfriend": False,
}

NUM_KEYS = [
    "support","affection","flirt","respect","apology","commitment_talk",
    "rude","boundary_push","dislike","hate",
]

def _clampf(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0

async def classify_signals(
    message: str,
    recent_ctx: str,
    persona_likes: list[str],
    persona_dislikes: list[str],
    llm
) -> dict:
    prompt = get_system_prompt(db, "RELATIONSHIP_SIGNAL_PROMPT")
    try:
        r = await llm.ainvoke(prompt)
        data = json.loads((r.content or "").strip())
    except Exception:
        data = {}

    out = dict(DEFAULT)
    for k in NUM_KEYS:
        out[k] = _clampf(data.get(k, 0.0))
    out["accepted_exclusive"] = bool(data.get("accepted_exclusive", False))
    out["accepted_girlfriend"] = bool(data.get("accepted_girlfriend", False))

    msg_len = len(message.strip())
    if msg_len <= 4:
        scale = 0.15
    elif msg_len <= 12:
        scale = 0.35
    elif msg_len <= 30:
        scale = 0.85
    else:
        scale = 1.0

    for k in NUM_KEYS:
        out[k] *= scale

    return out