import json
import time
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

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
    db,
    message: str,
    recent_ctx: str,
    persona_likes: list[str],
    persona_dislikes: list[str],
    llm
) -> dict:
    prompt_template = await get_system_prompt(db, prompt_keys.RELATIONSHIP_SIGNAL_PROMPT)
    prompt = prompt_template.format(
        persona_likes=persona_likes,
        persona_dislikes=persona_dislikes,
        recent_ctx=recent_ctx,
        message=message
    )
    try:
        t0 = time.perf_counter()
        r = await llm.ainvoke(prompt)
        sig_ms = int((time.perf_counter() - t0) * 1000)
        data = json.loads((r.content or "").strip())

        # Track convo analysis usage
        from app.services.token_tracker import track_usage_bg
        usage = getattr(r, "usage_metadata", None) or {}
        track_usage_bg(
            "system", "openai", "gpt-4o-mini", "convo_analysis",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=sig_ms,
        )
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
