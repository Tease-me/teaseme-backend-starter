import subprocess
import tempfile
import os
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from fastapi import HTTPException
from app.db.models import InfluencerWallet, InfluencerCreditTransaction, DailyUsage, Pricing, User, Chat

async def charge_feature(
    db: AsyncSession,
    *,
    user_id: int,
    influencer_id: str,
    feature: str,
    units: int,
    is_18: bool = False,
    meta: dict | None = None,
) -> int:
    today = date.today()

    # DailyUsage stays global per user (free allowance per day)
    usage = await db.get(DailyUsage, (user_id, today, is_18))
    if not usage:
        usage = DailyUsage(user_id=user_id, date=today, is_18=is_18)

    for field in ["text_count", "voice_secs", "live_secs"]:
        if getattr(usage, field, None) is None:
            setattr(usage, field, 0)

    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        raise HTTPException(500, "Pricing not configured")

    used = {
        "text": usage.text_count or 0,
        "voice": usage.voice_secs or 0,
        "live_chat": usage.live_secs or 0,
        "text_18": usage.text_count or 0,
        "voice_18": usage.voice_secs or 0,
    }[feature]

    free_left = max((price.free_allowance or 0) - used, 0)
    billable = max(units - free_left, 0)
    cost = billable * (price.price_cents or 0)

    # Update usage counters
    if "text" in feature:
        usage.text_count += units
    elif "voice" in feature:
        usage.voice_secs += units
    else:
        usage.live_secs += units
    db.add(usage)

    # Debit influencer wallet (per user + influencer)
    if cost:
        wallet = await db.scalar(
            select(InfluencerWallet).where(
                and_(
                    InfluencerWallet.user_id == user_id,
                    InfluencerWallet.influencer_id == influencer_id,
                    InfluencerWallet.is_18 == is_18,
                )
            )
        )

        if not wallet:
            wallet = InfluencerWallet(
                user_id=user_id,
                influencer_id=influencer_id,
                is_18=is_18,
                balance_cents=0,
            )
            db.add(wallet)
            await db.flush()

        old_balance = wallet.balance_cents or 0
        if old_balance < cost:
            raise HTTPException(402, "Insufficient credits")

        wallet.balance_cents = old_balance - cost
        db.add(wallet)

        # Low balance notification (per influencer wallet)
        new_balance = wallet.balance_cents
        THRESHOLD = 1000
        if old_balance >= THRESHOLD and new_balance < THRESHOLD:
            user_obj = await db.get(User, user_id)
            if user_obj and user_obj.email:
                try:
                    from app.api.notify_ws import notify_low_balance
                    await notify_low_balance(user_obj.email, new_balance)
                except Exception as e:
                    print(f"Error sending low balance notification: {e}")

    # Ledger
    db.add(
        InfluencerCreditTransaction(
            user_id=user_id,
            influencer_id=influencer_id,
            feature=feature,
            units=-units,
            amount_cents=-cost,
            meta=meta,
        )
    )

    await db.commit()
    return cost

async def topup_wallet(db, user_id: int, cents: int, source: str):
    """Add credits to user's wallet and log the transaction."""
    wallet = await db.get(InfluencerWallet, user_id) or InfluencerWallet(user_id=user_id)
    if wallet.balance_cents is None:
        wallet.balance_cents = 0
    wallet.balance_cents += cents
    db.add_all([
        wallet,
        InfluencerCreditTransaction(
            user_id=user_id,
            feature="topup",
            units=cents,
            amount_cents=cents,
            meta={"source": source}
        )
    ])
    await db.commit()
    return wallet.balance_cents

def get_audio_duration_ffmpeg(file_bytes: bytes) -> float:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        duration = float(result.stdout.decode().strip())
        return duration
    except Exception as e:
        print(f"ffmpeg duration error: {e}")
        return 10.0  # fallback
    

import subprocess, tempfile, math

MIME_TO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/wav":  ".wav",
    "audio/x-wav": ".wav",
    "audio/mp3":  ".mp3",
    "audio/mpeg": ".mp3",
    "audio/ogg":  ".ogg",
    "audio/x-m4a": ".m4a",
}

def _duration_via_ffprobe(data: bytes, suffix: str) -> float:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                tmp_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = result.stdout.decode().strip()
        try:
            duration = float(output)
        except Exception:
            print(f"[WARN] ffprobe failed: {output!r}")
            duration = 0.0
        return duration
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

def get_duration_seconds(file_bytes: bytes, mime: str | None = None) -> int:
    """
    Returns duration in whole seconds (>=1), fallback 10s if ffprobe fails.
    """
    suffix = MIME_TO_SUFFIX.get(mime or "", ".wav")
    duration = _duration_via_ffprobe(file_bytes, suffix)
    if duration <= 0:
        duration = 10.0
    return max(1, math.ceil(duration))


def _used_units_for_feature(usage: DailyUsage | None, feature: str) -> int:
    if not usage:
        return 0

    if "text" in feature:
        return int(usage.text_count or 0)
    if "voice" in feature:
        return int(usage.voice_secs or 0)
    return int(usage.live_secs or 0)


async def can_afford(
    db: AsyncSession,
    *,
    user_id: int,
    influencer_id: str,
    feature: str,
    units: int,
    is_18: bool = False,
) -> tuple[bool, int, int]:
    """
    Returns (ok, cost_cents, free_left)

    - Uses DailyUsage for free allowance (shared)
    - Uses InfluencerWallet filtered by is_18
    """

    price: Pricing | None = await db.scalar(
        select(Pricing).where(
            Pricing.feature == feature,
            Pricing.is_active.is_(True),
        )
    )
    if not price:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "PRICING_NOT_CONFIGURED",
                "message": f"No pricing configured for feature '{feature}'.",
            },
        )

    today = date.today()
    usage = await db.get(DailyUsage, (user_id, today, is_18))

    used = _used_units_for_feature(usage, feature)

    free_left = max((price.free_allowance or 0) - used, 0)
    billable = max(int(units) - free_left, 0)
    cost_cents = billable * int(price.price_cents or 0)

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            and_(
                InfluencerWallet.user_id == user_id,
                InfluencerWallet.influencer_id == influencer_id,
                InfluencerWallet.is_18.is_(is_18),
            )
        )
    )

    balance = int(wallet.balance_cents) if wallet and wallet.balance_cents is not None else 0

    ok = balance >= cost_cents
    return (ok or cost_cents == 0), cost_cents, free_left

async def get_remaining_units(db: AsyncSession, user_id: int, influencer_id: str, feature: str) -> int:
    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        return 0

    unit_price_cents = price.price_cents or 0
    free_allowance = price.free_allowance or 0

    today = date.today()
    usage: DailyUsage | None = await db.get(DailyUsage, (user_id, today))

    if "text" in feature:
        used = getattr(usage, "text_count", 0) if usage else 0
    elif "voice" in feature:
        used = getattr(usage, "voice_secs", 0) if usage else 0
    else:
        used = getattr(usage, "live_secs", 0) if usage else 0
        

    free_left = max(free_allowance - (used or 0), 0)

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user_id,
            InfluencerWallet.influencer_id == influencer_id,
        )
    )
    balance_cents = wallet.balance_cents if wallet and wallet.balance_cents is not None else 0

    paid = (balance_cents // unit_price_cents) if unit_price_cents > 0 else 0
    return int(free_left + paid)


async def _get_influencer_id_from_chat(db: AsyncSession, chat_id: str) -> str:
    chat = await db.get(Chat, chat_id)
    if not chat or not chat.influencer_id:
        raise HTTPException(400, "Missing chat/influencer context")
    return chat.influencer_id