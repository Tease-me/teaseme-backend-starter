
import asyncio, time, logging, json, hmac

from hashlib import sha256
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.services.billing import charge_feature
from app.api.elevenlabs import _extract_total_seconds
from sqlalchemy import select
from app.db.models import CallRecord, Chat
from app.agents.turn_handler import handle_turn
from app.agents.memory import find_similar_memories

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


def _verify_token(shared: str, token: str | None) -> None:
    """Simple shared-secret check (constant time if you prefer)."""
    if not shared:  # secret disabled
        return
    if not token:
        raise HTTPException(status_code=403, detail="Missing webhook token")
    # constant-time compare (avoid timing attacks)
    if not hmac.compare_digest(shared, token):
        raise HTTPException(status_code=403, detail="Invalid webhook token")


def _verify_airwallex_signature(
    *,
    secret: str | None,
    timestamp_ms: str | None,
    signature: str | None,
    body_bytes: bytes,
    tolerance_ms: int,
) -> None:
    """
    Airwallex webhook verification.
    expected_signature = HMAC_SHA256(secret, f"{timestamp}{raw_body}")
    """
    if not secret:
        return
    if not timestamp_ms or not signature:
        raise HTTPException(status_code=401, detail="Missing Airwallex webhook signature headers")

    try:
        received_ts = int(timestamp_ms)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid x-timestamp header")

    now_ms = int(time.time() * 1000)
    if abs(now_ms - received_ts) > int(tolerance_ms):
        raise HTTPException(status_code=401, detail="Stale Airwallex webhook timestamp")

    sig = signature.strip()
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()

    raw_body = body_bytes.decode("utf-8")
    value_to_digest = f"{timestamp_ms}{raw_body}"
    expected = hmac.new(secret.encode("utf-8"), value_to_digest.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(sig.lower(), expected.lower()):
        raise HTTPException(status_code=401, detail="Invalid Airwallex webhook signature")
    
@router.post("/memories")
async def eleven_webhook_get_memories(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    # 1) Auth
    _verify_token(ELEVENLABS_CONVAI_WEBHOOK_SECRET, x_webhook_token)

    # 2) Parse payload
    try:
        payload = await req.json()
    except Exception:
        return {"memories": []}

    try:
        log.info("[EL TOOL] payload(head)=%s", str(payload)[:800])
    except Exception:
        pass

    # 3) Extract user text
    args = payload.get("arguments") or {}
    raw_text = (
        payload.get("text")
        or payload.get("input")
        or (args.get("text") if isinstance(args, dict) else None)
        or ""
    )
    user_text = str(raw_text).strip()
    if not user_text:
        return {"memories": []}

    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        log.warning("[EL TOOL] missing conversation_id in payload=%s", str(payload)[:300])
        return {"memories": []}

    # 4) Look up CallRecord – must exist (set by /elevenlabs/conversations/{conversation_id}/register)
    try:
        res = await db.execute(
            select(CallRecord).where(CallRecord.conversation_id == conversation_id)
        )
        call = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] CallRecord lookup failed: %s", e)
        return {"memories": "I had an internal issue looking up this call. Please try again."}

    if not call:
        log.warning("[EL TOOL] No CallRecord found for conv=%s", conversation_id)
        return {
            "memories": []
        }

    user_id = call.user_id
    influencer_id = call.influencer_id
    chat_id = call.chat_id

    # 5) Validate context – no defaults
    if not user_id or not influencer_id or not chat_id:
        log.warning(
            "[EL TOOL] incomplete CallRecord context conv=%s user=%s infl=%s chat=%s",
            conversation_id, user_id, influencer_id, chat_id
        )
        return {
            "memories": []
        }

    # 6) Ensure Chat exists
    try:
        res = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] Chat lookup failed: %s", e)
        return {"text": "I hit an error accessing our chat. Please try again later."}

    if not chat:
        log.warning(
            "[EL TOOL] Chat not found for conv=%s chat=%s user=%s infl=%s",
            conversation_id, chat_id, user_id, influencer_id
        )
        return {
            "memories": []
        }

    # 7) Generate reply via handle_turn
    started = time.perf_counter()
    try:
        memories = await asyncio.wait_for(
            find_similar_memories(
                message=user_text,
                chat_id=chat_id,
                influencer_id=influencer_id,
                db=db,
            ),
            timeout=8.5,
        )
    except asyncio.TimeoutError:
        memories = []
    except Exception as e:
        log.exception("[EL TOOL] handle_turn failed: %s", e)
        memories = []
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "[EL TOOL] reply ms=%d conv=%s user=%s infl=%s chat=%s",
            ms, conversation_id, user_id, influencer_id, chat_id
        )

    return {"memories": memories}

@router.post("/reply")
async def eleven_webhook_reply(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    """
    ElevenLabs ConvAI tool webhook.
    Expects JSON payload with at least "text" and "conversation_id".

    This implementation:
    - DOES NOT use any defaults.
    - Relies on CallRecord created earlier (via /elevenlabs/conversations/{conversation_id}/register).
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

    # 3) Extract user text
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
    if not conversation_id:
        log.warning("[EL TOOL] missing conversation_id in payload=%s", str(payload)[:300])
        return {"text": "I’m missing the call ID. Please try again."}

    # 4) Look up CallRecord – must exist (set by /elevenlabs/conversations/{conversation_id}/register)
    try:
        res = await db.execute(
            select(CallRecord).where(CallRecord.conversation_id == conversation_id)
        )
        call = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] CallRecord lookup failed: %s", e)
        return {"text": "I had an internal issue looking up this call. Please try again."}

    if not call:
        log.warning("[EL TOOL] No CallRecord found for conv=%s", conversation_id)
        return {
            "text": (
                "I lost track of this call on my side. "
                "Please hang up and start a new one."
            )
        }

    user_id = call.user_id
    influencer_id = call.influencer_id
    chat_id = call.chat_id

    # 5) Validate context – no defaults
    if not user_id or not influencer_id or not chat_id:
        log.warning(
            "[EL TOOL] incomplete CallRecord context conv=%s user=%s infl=%s chat=%s",
            conversation_id, user_id, influencer_id, chat_id
        )
        return {
            "text": (
                "I’m having trouble with this call’s context. "
                "Let’s start fresh next time, okay?"
            )
        }

    # 6) Ensure Chat exists
    try:
        res = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] Chat lookup failed: %s", e)
        return {"text": "I hit an error accessing our chat. Please try again later."}

    if not chat:
        log.warning(
            "[EL TOOL] Chat not found for conv=%s chat=%s user=%s infl=%s",
            conversation_id, chat_id, user_id, influencer_id
        )
        return {
            "text": (
                "I can’t find our previous messages right now. "
                "Let’s start again next time?"
            )
        }

    # 7) Generate reply via handle_turn
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
            timeout=8.5,
        )
    except asyncio.TimeoutError:
        reply = "One sec… could you say that again?"
    except Exception as e:
        log.exception("[EL TOOL] handle_turn failed: %s", e)
        reply = "Sorry, something went wrong."
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "[EL TOOL] reply ms=%d conv=%s user=%s infl=%s chat=%s",
            ms, conversation_id, user_id, influencer_id, chat_id
        )

    # 8) Trim for TTS
    if isinstance(reply, str) and len(reply) > 320:
        reply = reply[:317] + "…"

    return {"text": reply}


@router.post("/airwallex")
async def airwallex_webhook(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_timestamp: str | None = Header(default=None, alias="x-timestamp"),
    x_signature: str | None = Header(default=None, alias="x-signature"),
):
    """
    Airwallex webhook handler (minimal).
    - Updates stored checkout/payment records
    - Finalizes wallet top-ups (credits) when a PAYMENT checkout succeeds
    - Attempts to reverse wallet credits on refund/chargeback events when possible
    """
    body_bytes = await req.body()
    _verify_airwallex_signature(
        secret=(settings.AIRWALLEX_WEBHOOK_SECRET or settings.AIRWALLEX_WEBHOOK_TOKEN),
        timestamp_ms=x_timestamp,
        signature=x_signature,
        body_bytes=body_bytes,
        tolerance_ms=settings.AIRWALLEX_WEBHOOK_TOLERANCE_MS,
    )
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = (
        payload.get("type")
        or payload.get("name")
        or payload.get("event_type")
        or payload.get("event")
        or ""
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    checkout_id = (
        data.get("id")
        or data.get("billing_checkout_id")
        or data.get("checkout_id")
        or data.get("object_id")
    )
    request_id = data.get("request_id")
    status = (data.get("status") or "").upper()

    from sqlalchemy import select
    from app.db.models import AirwallexBillingCheckout, CreditTransaction, CreditWallet, WalletTopup

    checkout_row = None
    if checkout_id:
        checkout_row = await db.scalar(
            select(AirwallexBillingCheckout).where(AirwallexBillingCheckout.airwallex_checkout_id == checkout_id)
        )
    if not checkout_row and request_id:
        checkout_row = await db.scalar(
            select(AirwallexBillingCheckout).where(AirwallexBillingCheckout.request_id == request_id)
        )

    if not checkout_row:
        return {"ok": True, "ignored": True}

    checkout_row.status = status or checkout_row.status
    checkout_row.response_payload = payload
    db.add(checkout_row)

    topup = await db.scalar(
        select(WalletTopup)
        .where(WalletTopup.airwallex_billing_checkout_row_id == checkout_row.id)
        .with_for_update()
    )
    if not topup:
        await db.commit()
        return {"ok": True, "updated_checkout": True}

    success_statuses = {"SUCCEEDED", "CAPTURE_SUCCEEDED", "CAPTURED", "SUCCESS", "COMPLETED", "PAID"}
    failure_statuses = {"FAILED", "CANCELLED", "CANCELED", "EXPIRED"}

    is_refundish = "refund" in str(event_type).lower() or "chargeback" in str(event_type).lower()

    if not is_refundish and status in success_statuses:
        if topup.credit_transaction_id is None and topup.status != "succeeded":
            wallet = await db.get(CreditWallet, topup.user_id) or CreditWallet(user_id=topup.user_id)
            wallet.balance_cents = (wallet.balance_cents or 0) + (topup.amount_cents or 0)
            tx = CreditTransaction(
                user_id=topup.user_id,
                feature="topup",
                units=topup.amount_cents,
                amount_cents=topup.amount_cents,
                meta={
                    "source": "manual_topup_airwallex",
                    "wallet_topup_id": topup.id,
                    "airwallex_checkout_id": checkout_row.airwallex_checkout_id,
                    "event_type": event_type,
                },
            )
            db.add_all([wallet, tx])
            await db.flush()
            topup.status = "succeeded"
            topup.credit_transaction_id = tx.id
            db.add(topup)

    elif not is_refundish and status in failure_statuses:
        if topup.status not in {"succeeded", "refunded"}:
            topup.status = "failed"
            topup.error_message = f"checkout_status={status}"
            db.add(topup)

    elif is_refundish:
        amount_cents = data.get("amount") or data.get("amount_cents") or topup.amount_cents
        try:
            amount_cents = int(amount_cents)
        except Exception:
            amount_cents = topup.amount_cents

        if topup.status == "succeeded" and amount_cents and amount_cents > 0:
            wallet = await db.get(CreditWallet, topup.user_id) or CreditWallet(user_id=topup.user_id)
            balance = wallet.balance_cents or 0
            if balance >= amount_cents:
                wallet.balance_cents = balance - amount_cents
                tx = CreditTransaction(
                    user_id=topup.user_id,
                    feature="refund",
                    units=-amount_cents,
                    amount_cents=-amount_cents,
                    meta={
                        "source": "airwallex_refund",
                        "wallet_topup_id": topup.id,
                        "airwallex_checkout_id": checkout_row.airwallex_checkout_id,
                        "event_type": event_type,
                    },
                )
                db.add_all([wallet, tx])
                topup.status = "refunded"
                db.add(topup)
            else:
                topup.status = "refund_failed_insufficient_balance"
                topup.error_message = f"refund_amount={amount_cents} balance={balance}"
                db.add(topup)

    await db.commit()
    return {"ok": True}
