import json

DEFAULT = {
    "support": 0.0, "affection": 0.0, "flirt": 0.0, "respect": 0.0,
    "rude": 0.0, "boundary_push": 0.0, "apology": 0.0,
    "commitment_talk": 0.0,
    "accepted_exclusive": False,
    "accepted_girlfriend": False,
}

def _clampf(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0

async def classify_signals(message: str, recent_ctx: str, llm) -> dict:
    prompt = f"""
    You are a strict relationship signal classifier.

    Return ONLY valid JSON with keys:
    support, affection, flirt, respect, rude, boundary_push, apology, commitment_talk (floats 0..1),
    accepted_exclusive, accepted_girlfriend (booleans).

    IMPORTANT RULES:
    - boundary_push MUST be 0 unless the user is pressuring, ignoring consent, threatening, manipulating,
    or pushing sexual content without invitation.
    - A romantic request like "I want to be your boyfriend/girlfriend" is NOT boundary_push.
    - rude MUST be 0 unless there is an insult, profanity, hostility, or disrespect.
    - Very short messages (e.g. "hey") should have values near 0.

    Context:
    {recent_ctx}

    User message:
    {message}
    """
    try:
        r = await llm.ainvoke(prompt)
        data = json.loads((r.content or "").strip())
    except Exception:
        data = DEFAULT

    out = dict(DEFAULT)
    for k in ["support","affection","flirt","respect","rude","boundary_push","apology","commitment_talk"]:
        out[k] = _clampf(data.get(k, 0.0))
    out["accepted_exclusive"] = bool(data.get("accepted_exclusive", False))
    out["accepted_girlfriend"] = bool(data.get("accepted_girlfriend", False))

    msg_len = len(message.strip())

    if msg_len <= 4:        # "hey", "oi", "yo"
        scale = 0.15
    elif msg_len <= 12:     # "how are you"
        scale = 0.35
    elif msg_len <= 30:
        scale = 0.6
    else:
        scale = 1.0

    for k in ["support","affection","flirt","respect","rude","boundary_push","apology","commitment_talk"]:
        out[k] *= scale
    return out