
import asyncio, time, logging, json, hmac

from hashlib import sha256
from typing import Optional, Any
from app.agents.prompts import CONVO_ANALYZER

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.services.billing import charge_feature, _get_influencer_id_from_chat
from app.api.elevenlabs import _extract_total_seconds
from sqlalchemy import select
from app.db.models import CallRecord, Chat, Influencer
from app.agents.turn_handler import  handle_turn, redis_history
from app.agents.memory import find_similar_memories, find_similar_messages

from app.relationship.processor import process_relationship_turn


log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ELEVENLABS_CONVAI_WEBHOOK_SECRET = settings.ELEVENLABS_CONVAI_WEBHOOK_SECRET
ELEVEN_BASE_URL = settings.ELEVEN_BASE_URL

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
    client_ip = request.client.host if request.client else "-"
    te = (request.headers.get("transfer-encoding") or "").lower()
    log.info("webhook.receive start ip=%s transfer_encoding=%s", client_ip, te)

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
    transcript_entries = data.get("transcript") or []
    full_transcript = " ".join(
        entry.get("message", "")
        for entry in transcript_entries
        if isinstance(entry, dict) and entry.get("message")
    )

    log.info(
        "webhook.parsed type=%s conv_id=%s status=%s seconds=%s ip=%s",
        event_type, _redact(conversation_id), status, total_seconds, client_ip
    )

    if not conversation_id:
        log.warning("webhook.no_conversation_id ip=%s", client_ip)
        return {"ok": False, "reason": "no-conversation-id"}

    meta_map = await _resolve_user_for_conversation(db, conversation_id)
    user_id = meta_map.get("user_id") or data.get("user_id") 
    sid = meta_map.get("sid") or conversation_id

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
            chat_id = meta.get("chat_id") if isinstance(meta, dict) else None
            if not chat_id:
                raise HTTPException(400, "Missing chat_id in meta for billing")

            influencer_id = await _get_influencer_id_from_chat(db, chat_id)

            await charge_feature(
                db,
                user_id=user_id,
                influencer_id=influencer_id,
                feature="live_chat",
                units=int(total_seconds),
                meta=meta,
            )
            log.info(
                "webhook.billing.success user=%s conv_id=%s seconds=%s",
                _redact(user_id), _redact(conversation_id), total_seconds
            )
        except Exception as e:
            log.exception(
                "webhook.billing.error user=%s conv_id=%s err=%s",
                _redact(user_id), _redact(conversation_id), repr(e)
            )
            raise

    else:
        reason = "not_done" if status != "done" else "no_user"
        log.info(
            "webhook.billing.skipped reason=%s conv_id=%s status=%s user=%s",
            reason, _redact(conversation_id), status, _redact(user_id)
        )

    log.info(
        "webhook.response ok=True conv_id=%s status=%s seconds=%s",
        _redact(conversation_id), status, total_seconds
    )
    return {"ok": True, "conversation_id": conversation_id, "status": status, "total_seconds": int(total_seconds)}

@router.post("/update_relationship")
async def update_relationship_api(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    _verify_token(ELEVENLABS_CONVAI_WEBHOOK_SECRET, x_webhook_token)

    try:
        payload = await req.json()
    except Exception:
        return {"error": "Sorry, I didn’t catch that. Could you repeat?"}

    try:
        log.info("[EL TOOL] payload(head)=%s", str(payload)[:800])
    except Exception:
        pass

    args = payload.get("arguments") or {}
    raw_text = (
        payload.get("text")
        or payload.get("input")
        or (args.get("text") if isinstance(args, dict) else None)
        or ""
    )
    user_text = str(raw_text).strip()
    if not user_text:
        return {"error": "I didn’t catch that. Could you repeat?"}

    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        log.warning("[EL TOOL] missing conversation_id in payload=%s", str(payload)[:300])
        return {"error": "I’m missing the call ID. Please try again."}

    try:
        res = await db.execute(select(CallRecord).where(CallRecord.conversation_id == conversation_id))
        call = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] CallRecord lookup failed: %s", e)
        return {"error": "I had an internal issue looking up this call. Please try again."}

    if not call:
        log.warning("[EL TOOL] No CallRecord found for conv=%s", conversation_id)
        return {"error": "Conversation ID Not Found"}

    user_id = call.user_id
    influencer_id = call.influencer_id
    chat_id = call.chat_id

    if not user_id or not influencer_id or not chat_id:
        log.warning(
            "[EL TOOL] incomplete CallRecord context conv=%s user=%s infl=%s chat=%s",
            conversation_id, user_id, influencer_id, chat_id
        )
        return {"error": "I’m having trouble with this call’s context."}

    history = redis_history(chat_id)

    if len(history.messages) > settings.MAX_HISTORY_WINDOW:
        trimmed = history.messages[-settings.MAX_HISTORY_WINDOW:]
        history.clear()
        history.add_messages(trimmed)

    recent_ctx = "\n".join(f"{m.type}: {m.content}" for m in history.messages[-6:])

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        log.warning("[EL TOOL] Influencer not found infl=%s conv=%s", influencer_id, conversation_id)
        return {"error": "Influencer not found"}

    rel_pack = await process_relationship_turn(
        db=db,
        user_id=int(user_id),
        influencer_id=influencer_id,
        message=user_text,
        recent_ctx=recent_ctx,
        cid=f"el_{conversation_id}"[:16],
        convo_analyzer=CONVO_ANALYZER,
        influencer=influencer,
    )

    rel = rel_pack["rel"]
    days_idle = rel_pack["days_idle"]
    dtr_goal = rel_pack["dtr_goal"]

    relationship = (
        "# Relationship Metrics:\n"
        f"- phase: {rel.state}\n"
        f"- trust: {rel.trust}/100\n"
        f"- closeness: {rel.closeness}/100\n"
        f"- attraction: {rel.attraction}/100\n"
        f"- safety: {rel.safety}/100\n"
        f"- exclusive_agreed: {rel.exclusive_agreed}\n"
        f"- girlfriend_confirmed: {rel.girlfriend_confirmed}\n"
        f"- days_idle_before_message: {days_idle}\n"
        f"- dtr_goal: {dtr_goal}\n"
    )

    log.info("[EL TOOL] relationship_metrics conv=%s\n%s", conversation_id, relationship)
    return relationship

def _verify_token(shared: str, token: str | None) -> None:
    if not shared: 
        return
    if not token:
        raise HTTPException(status_code=403, detail="Missing webhook token")
    if not hmac.compare_digest(shared, token):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

@router.post("/memories")
async def eleven_webhook_get_memories(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    _verify_token(ELEVENLABS_CONVAI_WEBHOOK_SECRET, x_webhook_token)

    try:
        payload = await req.json()
    except Exception:
        return {"memories": []}

    try:
        log.info("[EL TOOL] payload(head)=%s", str(payload)[:800])
    except Exception:
        pass

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

    try:
        res = await db.execute(
            select(CallRecord).where(CallRecord.conversation_id == conversation_id)
        )
        call = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] CallRecord lookup failed: %s", e)
        return {"memories": []}

    if not call:
        log.warning("[EL TOOL] No CallRecord found for conv=%s", conversation_id)
        return {
            "memories": []
        }

    user_id = call.user_id
    influencer_id = call.influencer_id
    chat_id = call.chat_id

    if not user_id or not influencer_id or not chat_id:
        log.warning(
            "[EL TOOL] incomplete CallRecord context conv=%s user=%s infl=%s chat=%s",
            conversation_id, user_id, influencer_id, chat_id
        )
        return {
            "memories": []}

    try:
        res = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = res.scalar_one_or_none()
    except Exception as e:
        log.exception("[EL TOOL] Chat lookup failed: %s", e)
        return {"memories": []}

    if not chat:
        log.warning(
            "[EL TOOL] Chat not found for conv=%s chat=%s user=%s infl=%s",
            conversation_id, chat_id, user_id, influencer_id
        )
        return {
            "memories": []
        }

    started = time.perf_counter()
    memories = []
    
    try:
        # Compute embedding ONCE, then query memories and messages in PARALLEL
        # Embedding typically completes in 50-100ms, reduced timeout for faster failover
        from app.services.embeddings import get_embedding
        embedding = await asyncio.wait_for(
            get_embedding(user_text),
            timeout=1.5,  # Reduced from 3.0s - embeddings are fast
        )
        
        # Run both queries in parallel with shared embedding
        memories_result, messages_result = await asyncio.wait_for(
            asyncio.gather(
                find_similar_memories(
                    message=user_text,
                    chat_id=chat_id,
                    influencer_id=influencer_id,
                    db=db,
                    embedding=embedding,
                ),
                find_similar_messages(
                    message=user_text,
                    chat_id=chat_id,
                    influencer_id=influencer_id,
                    db=db,
                    embedding=embedding,
                ),
                return_exceptions=True,
            ),
            timeout=6.0,
        )
        
        # Combine results, filtering out exceptions
        if isinstance(memories_result, list) and memories_result:
            memories = memories_result
        elif isinstance(messages_result, list) and messages_result:
            memories = messages_result
            
    except asyncio.TimeoutError:
        log.warning("[EL TOOL] memory query timeout conv=%s", conversation_id)
    except Exception as e:
        log.exception("[EL TOOL] memory query failed: %s", e)
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "[EL TOOL] memories ms=%d count=%d conv=%s user=%s infl=%s chat=%s",
            ms, len(memories) if memories else 0, conversation_id, user_id, influencer_id, chat_id
        )

    return {"memories": memories}

@router.post("/reply")
async def eleven_webhook_reply(
    req: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_token: str | None = Header(default=None),
):
    _verify_token(ELEVENLABS_CONVAI_WEBHOOK_SECRET, x_webhook_token)

    try:
        payload = await req.json()
    except Exception:
        return {"text": "Sorry, I didn’t catch that. Could you repeat?"}

    try:
        log.info("[EL TOOL] payload(head)=%s", str(payload)[:800])
    except Exception:
        pass

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

    if isinstance(reply, str) and len(reply) > 320:
        reply = reply[:317] + "…"

    return {"text": reply}
