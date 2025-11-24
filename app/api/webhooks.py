import asyncio, time, logging, json, hmac
import httpx

from hashlib import sha256
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.services.billing import charge_feature
from app.api.elevenlabs import (
    _extract_total_seconds,
    _get_conversation_snapshot,
    _persist_transcript_to_chat,
    _normalize_transcript,
)
from sqlalchemy import select
from app.db.models import CallRecord
from app.agents.turn_handler import handle_turn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ELEVENLABS_CONVAI_WEBHOOK_SECRET = settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"

log = logging.getLogger(__name__)

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
    q = select(CallRecord.user_id, CallRecord.influencer_id, CallRecord.sid, CallRecord.chat_id)\
        .where(CallRecord.conversation_id == conversation_id)
    res = await db.execute(q)
    row = res.first()
    if not row:
        log.info("resolver.miss conversation_id=%s", conversation_id)
        return {"user_id": None, "influencer_id": None, "sid": conversation_id, "chat_id": None}
    user_id, influencer_id, sid, chat_id = row
    log.info("resolver.hit conversation_id=%s user_id=%s", conversation_id, user_id)
    return {
        "user_id": user_id,
        "influencer_id": influencer_id,
        "sid": sid or conversation_id,
        "chat_id": chat_id,
    }

def _verify_token(shared: str, token: str | None) -> None:
    """Simple shared-secret check (constant time if you prefer)."""
    if not shared:  # secret disabled
        return
    if not token:
        raise HTTPException(status_code=403, detail="Missing webhook token")
    # constant-time compare (avoid timing attacks)
    if not hmac.compare_digest(shared, token):
        raise HTTPException(status_code=403, detail="Invalid webhook token")


@router.post("/reply")
async def eleven_webhook_reply(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    """
    ElevenLabs ConvAI tool webhook.
    Recebe a fala do usuário e devolve o texto para o TTS.
    """
    # 1) Auth
    _verify_token(ELEVENLABS_CONVAI_WEBHOOK_SECRET, x_webhook_token)

    # 2) Parse payload
    try:
        payload = await req.json()
    except Exception:
        return {"text": "Sorry, I didn’t catch that. Could you repeat?"}

    try:
        log.info("[EL TOOL] payload(head)=%s", str(payload)[:800])
    except Exception:
        pass

    # 3) Texto do usuário (aceita formatos comuns)
    args = payload.get("arguments") or {}
    raw_text = (
        payload.get("text")
        or payload.get("input")
        or (args.get("text") if isinstance(args, dict) else None)
        or ""
    )
    user_text = str(raw_text).strip()
    if not user_text:
        return {"text": "I didn’t catch that. Could you repeat?"}

    conversation_id = payload.get("conversation_id")

    # 3b) Contexto: primeiro meta, depois fallback por conversation_id
    meta = payload.get("meta") or {}
    user_id       = meta.get("user_id")
    influencer_id = meta.get("influencer_id")
    chat_id       = meta.get("chat_id")

    if (not user_id or not influencer_id or not chat_id) and conversation_id:
        try:
            res = await db.execute(
                select(CallRecord).where(CallRecord.conversation_id == conversation_id)
            )
            rec = res.scalar_one_or_none()
            if rec:
                user_id       = user_id or rec.user_id
                influencer_id = influencer_id or rec.influencer_id
                chat_id = rec.chat_id
        except Exception as e:
            log.exception("[EL TOOL] lookup CallRecord failed: %s", e)

    # 3c) Validações finais (sem defaults perigosos!)
    if not user_id or not influencer_id:
        log.warning(
            "[EL TOOL] missing context (user_id=%s, influencer_id=%s, conv=%s)",
            user_id, influencer_id, conversation_id
        )
        return {"text": "Hmm, I lost track of our chat. Could you say that again?"}

    if not chat_id:
        chat_id = f"{user_id}_{influencer_id}"

    # 4) Gera a resposta (timeout + métricas)
    started = time.perf_counter()
    try:
        reply = await asyncio.wait_for(
            handle_turn(
                message=user_text,
                chat_id=chat_id,
                influencer_id=influencer_id,
                user_id=user_id,
                db=db,
                is_audio=True,
            ),
            timeout=8.5,  # ajuste conforme sua latência média
        )
    except asyncio.TimeoutError:
        reply = "One sec… could you say that again?"
    except Exception as e:
        log.exception("[EL TOOL] handle_turn failed: %s", e)
        reply = "Sorry, something went wrong."
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "[EL TOOL] reply ms=%d conv=%s user=%s infl=%s",
            ms, conversation_id, user_id, influencer_id
        )

    # 5) Poda de segurança (fala muito longa atrapalha a UX de voz)
    if isinstance(reply, str) and len(reply) > 320:
        reply = reply[:317] + "…"

    return {"text": reply}

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

    event_type = payload.get("type")
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
    chat_id = meta_map.get("chat_id")

    snapshot_for_history = data
    if not snapshot_for_history.get("transcript"):
        try:
            async with httpx.AsyncClient(http2=True, base_url=ELEVEN_BASE_URL) as client:
                snapshot_for_history = await _get_conversation_snapshot(client, conversation_id)
        except Exception as exc:
            log.warning(
                "webhook.snapshot_fetch_failed conv=%s err=%s",
                _redact(conversation_id),
                exc,
            )
            snapshot_for_history = data
    normalized_transcript = _normalize_transcript(snapshot_for_history)

    # Only bill when the conversation is fully done (avoid processing/in-progress).
    if status == "done" and user_id:
        meta = {
            "session_id": sid,
            "conversation_id": conversation_id,
            "status": status,
            "agent_id": data.get("agent_id"),
            "start_time_unix_secs": (data.get("metadata") or {}).get("start_time_unix_secs"),
            "has_audio": data.get("has_audio", False),
            "has_user_audio": data.get("has_user_auƒdio", False),
            "has_response_audio": data.get("has_response_audio", False),
            "source": "webhook",
            "event_type": event_type,
        }
        log.info(
            "webhook.billing.start user=%s conv_id=%s seconds=%s",
            _redact(user_id), _redact(conversation_id), total_seconds
        )
        if chat_id:
            try:
                await _persist_transcript_to_chat(
                    db,
                    conversation_json=snapshot_for_history,
                    chat_id=chat_id,
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                log.warning(
                    "webhook.persist_transcript_failed conv=%s chat=%s err=%s",
                    _redact(conversation_id),
                    chat_id,
                    exc,
                )
        try:
            call_record = await db.get(CallRecord, conversation_id)
            if call_record:
                call_record.status = status
                call_record.call_duration_secs = total_seconds
                call_record.transcript = normalized_transcript or call_record.transcript
                if chat_id:
                    call_record.chat_id = chat_id
                if meta_map.get("influencer_id"):
                    call_record.influencer_id = meta_map.get("influencer_id")
                db.add(call_record)
                await db.commit()
        except Exception as exc:
            log.warning(
                "webhook.update_call_record_failed conv=%s err=%s",
                _redact(conversation_id),
                exc,
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
