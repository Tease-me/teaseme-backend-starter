import hmac
import json
import time
import logging
import logging

from hashlib import sha256
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.services.billing import charge_feature
from app.api.elevenlabs import _extract_total_seconds
from sqlalchemy import select
from app.db.models import CallRecord

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ELEVENLABS_CONVAI_WEBHOOK_SECRET = settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"

log = logging.getLogger(__name__)  # <-- logger


def _redact(val: Any) -> str:
    """Redact potentially sensitive IDs in logs; works for int/str/None."""
    if val is None:
        return "-"
    s = str(val)
    if len(s) <= 6:
        return "***"
    return f"{s[:3]}…{s[-2:]}"


def _verify_hmac(raw_body: bytes, signature_header: Optional[str]) -> None:
    """
    Verify ElevenLabs HMAC signature.
    Header format: 't=<timestamp>,v0=<hex>' where v0 is HMAC_SHA256(f"{t}.{body}")
    using ELEVENLABS_CONVAI_WEBHOOK_SECRET.
    """
    if not ELEVENLABS_CONVAI_WEBHOOK_SECRET:
        log.error("webhook.hmac.missing_secret")
        raise HTTPException(500, "ELEVENLABS_CONVAI_WEBHOOK_SECRET not configured")
    if not signature_header:
        log.warning("webhook.hmac.missing_signature_header")
        raise HTTPException(401, "Missing ElevenLabs-Signature")

    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        ts_str = parts["t"]
        v0 = parts["v0"]
        ts = int(ts_str)
    except Exception:
        log.warning("webhook.hmac.malformed_header header=%s", signature_header)
        raise HTTPException(401, "Malformed ElevenLabs-Signature")

    now = int(time.time())
    # Reject very old signatures (30 minutes)
    if ts < now - 30 * 60:
        log.warning("webhook.hmac.stale_signature ts=%s now=%s skew=%ss", ts, now, now - ts)
        raise HTTPException(401, "Stale signature")

    msg = f"{ts}.{raw_body.decode('utf-8')}".encode("utf-8")
    mac = hmac.new(ELEVENLABS_CONVAI_WEBHOOK_SECRET.encode("utf-8"), msg, sha256).hexdigest()
    expected = "v0=" + mac
    provided = v0 if v0.startswith("v0=") else "v0=" + v0

    if not hmac.compare_digest(provided, expected):
        log.warning(
            "webhook.hmac.invalid_signature provided=%s expected_prefix=%s",
            provided[:10] + "…",
            expected[:10] + "…",
        )
        raise HTTPException(401, "Invalid signature")

    log.debug("webhook.hmac.valid ts=%s", ts)


async def _resolve_user_for_conversation(db, conversation_id: str):
    log.info("resolver.called conversation_id=%s", conversation_id)
    q = select(CallRecord.user_id, CallRecord.influencer_id, CallRecord.sid)\
        .where(CallRecord.conversation_id == conversation_id)
    res = await db.execute(q)
    row = res.first()
    if not row:
        log.info("resolver.miss conversation_id=%s", conversation_id)
        return {"user_id": None, "influencer_id": None, "sid": conversation_id}
    user_id, influencer_id, sid = row
    log.info("resolver.hit conversation_id=%s user_id=%s", conversation_id, user_id)
    return {"user_id": user_id, "influencer_id": influencer_id, "sid": sid or conversation_id}


@router.post("/elevenlabs")
async def elevenlabs_post_call(request: Request, db: AsyncSession = Depends(get_db)):
    """
    ElevenLabs post-call webhook handler.
    - Validates HMAC signature.
    - Bills when status == "done" (idempotent by conversation_id).
    - Responds 200 quickly (webhooks may be disabled after repeated failures).
    """
    client_ip = request.client.host if request.client else "-"
    te = (request.headers.get("transfer-encoding") or "").lower()
    log.info("webhook.receive start ip=%s transfer_encoding=%s", client_ip, te)

    # Handle possible chunked bodies (when "Send audio data" is enabled)
    if te == "chunked":
        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
        raw = bytes(buf)
    else:
        raw = await request.body()

    log.debug("webhook.receive.body bytes=%d", len(raw))

    sig = request.headers.get("ElevenLabs-Signature") or request.headers.get("elevenlabs-signature")
    _verify_hmac(raw, sig)
    log.info("webhook.verified ip=%s", client_ip)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        log.warning("webhook.json.invalid ip=%s", client_ip)
        raise HTTPException(400, "Invalid JSON payload")

    event_type = payload.get("type")  # "post_call_transcription" or "post_call_audio"
    data = payload.get("data") or {}

    conversation_id = data.get("conversation_id")
    status = (data.get("status") or "done").lower()
    total_seconds = _extract_total_seconds(data)

    log.info(
        "webhook.parsed type=%s conv_id=%s status=%s seconds=%s ip=%s",
        event_type, _redact(conversation_id), status, total_seconds, client_ip
    )

    if not conversation_id:
        log.warning("webhook.no_conversation_id ip=%s", client_ip)
        return {"ok": False, "reason": "no-conversation-id"}

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
        log.info(     
            "webhook.billing.start user=%s conv_id=%s seconds=%s",
            _redact(user_id), _redact(conversation_id), total_seconds
        )
        try:
            # Important: charge_feature must be idempotent by conversation_id
            await charge_feature(
                db,
                user_id=user_id,
                feature="live_chat",
                units=int(total_seconds),
                meta=meta,
            )
            log.info(
                "webhook.billing.success user=%s conv_id=%s seconds=%s",
                _redact(user_id), _redact(conversation_id), total_seconds
            )
        except Exception as e:
            # Keep behavior: let the exception bubble (you may choose to swallow and still 200)
            log.exception(
                "webhook.billing.error user=%s conv_id=%s err=%s",
                _redact(user_id), _redact(conversation_id), repr(e)
            )
            raise

    else:
        # Not billing: either not done or no user mapping
        reason = "not_done" if status != "done" else "no_user"
        log.info(
            "webhook.billing.skipped reason=%s conv_id=%s status=%s user=%s",
            reason, _redact(conversation_id), status, _redact(user_id)
        )

    log.info(
        "webhook.response ok=True conv_id=%s status=%s seconds=%s",
        _redact(conversation_id), status, total_seconds
    )
    # Always respond quickly with 200 on success.
    return {"ok": True, "conversation_id": conversation_id, "status": status, "total_seconds": int(total_seconds)}