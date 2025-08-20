import hmac
import json
import os
import time
from hashlib import sha256
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.services.billing import charge_feature  # must be idempotent by conversation_id
from app.api.elevenlabs import _extract_total_seconds  # reuse the same logic

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ELEVENLABS_CONVAI_WEBHOOK_SECRET = settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"


def _verify_hmac(raw_body: bytes, signature_header: Optional[str]) -> None:
    """
    Verify ElevenLabs HMAC signature.
    Header format: 't=<timestamp>,v0=<hex>' where v0 is HMAC_SHA256(f"{t}.{body}")
    using ELEVENLABS_CONVAI_WEBHOOK_SECRET.
    """
    if not ELEVENLABS_CONVAI_WEBHOOK_SECRET:
        raise HTTPException(500, "ELEVENLABS_CONVAI_WEBHOOK_SECRET not configured")
    if not signature_header:
        raise HTTPException(401, "Missing ElevenLabs-Signature")

    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        ts = int(parts["t"])
        v0 = parts["v0"]
    except Exception:
        raise HTTPException(401, "Malformed ElevenLabs-Signature")

    # Reject very old signatures (30 minutes)
    if ts < int(time.time()) - 30 * 60:
        raise HTTPException(401, "Stale signature")

    mac = hmac.new(
        ELEVENLABS_CONVAI_WEBHOOK_SECRET.encode("utf-8"),
        f"{ts}.{raw_body.decode('utf-8')}".encode("utf-8"),
        sha256,
    ).hexdigest()
    expected = "v0=" + mac
    provided = v0 if v0.startswith("v0=") else "v0=" + v0
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid signature")


async def _resolve_user_for_conversation(db: AsyncSession, conversation_id: str) -> Dict[str, Any]:
    """
    Look up your user/influencer/sid for a given conversation_id.
    This assumes the client called /register when the call started.
    Implement this to match your DB schema (calls table).
    """
    # TODO:
    # row = await db.execute(select(Calls).where(Calls.conversation_id == conversation_id))
    # return {"user_id": row.user_id, "influencer_id": row.influencer_id, "sid": row.sid}
    return {"user_id": None, "influencer_id": None, "sid": conversation_id}


@router.post("/elevenlabs")
async def elevenlabs_post_call(request: Request, db: AsyncSession = Depends(get_db)):
    """
    ElevenLabs post-call webhook handler.
    - Validates HMAC signature.
    - Bills when status == "done" (idempotent by conversation_id).
    - Responds 200 quickly (webhooks may be disabled after repeated failures).
    """
    # Handle possible chunked bodies (when "Send audio data" is enabled)
    if request.headers.get("transfer-encoding", "").lower() == "chunked":
        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
        raw = bytes(buf)
    else:
        raw = await request.body()

    sig = request.headers.get("ElevenLabs-Signature") or request.headers.get("elevenlabs-signature")
    _verify_hmac(raw, sig)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    event_type = payload.get("type")  # "post_call_transcription" or "post_call_audio"
    data = payload.get("data") or {}

    conversation_id = data.get("conversation_id")
    if not conversation_id:
        # Nothing we can do without a conversation_id
        return {"ok": False, "reason": "no-conversation-id"}

    status = (data.get("status") or "done").lower()
    total_seconds = _extract_total_seconds(data)

    # Derive your user mapping. Prefer the stored mapping from /register.
    meta_map = await _resolve_user_for_conversation(db, conversation_id)
    user_id = meta_map.get("user_id") or data.get("user_id")  # last-resort fallback
    sid = meta_map.get("sid") or conversation_id

    # Only bill when the conversation is fully done (avoid processing/in-progress).
    if status == "done" and user_id:
        meta = {
            "session_id": sid,
            "conversation_id": conversation_id,
            "status": status,
            "agent_id": data.get("agent_id"),
            "start_time_unix_secs": (data.get("metadata") or {}).get("start_time_unix_secs"),
            "has_audio": data.get("has_audio", False),
            "has_user_audio": data.get("has_user_audio", False),
            "has_response_audio": data.get("has_response_audio", False),
            "source": "webhook",
            "event_type": event_type,
        }
        # Important: charge_feature must be idempotent by conversation_id
        charge_feature(db, user_id, "live_chat", int(total_seconds), meta=meta)

    # Always respond quickly with 200 on success.
    return {"ok": True, "conversation_id": conversation_id, "status": status, "total_seconds": int(total_seconds)}