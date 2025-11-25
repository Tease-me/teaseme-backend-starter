import subprocess
import tempfile
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from fastapi import HTTPException
from app.db.models import CreditWallet, CreditTransaction, DailyUsage, Pricing

async def charge_feature(db, *, user_id: int, feature: str, units: int, meta: dict | None = None):
    today = date.today()
    usage = await db.get(DailyUsage, (user_id, today)) or DailyUsage(user_id=user_id, date=today)

    # Ensure no field is None
    for field in ['text_count', 'voice_secs', 'live_secs']:
        if getattr(usage, field, None) is None:
            setattr(usage, field, 0)

    price: Pricing = await db.scalar(select(Pricing).where(
        Pricing.feature == feature, Pricing.is_active.is_(True)
    ))
    if not price:
        raise HTTPException(500, "Pricing not configured")

    free_left = {
        "text":  max((price.free_allowance or 0) - (usage.text_count or 0), 0),
        "voice": max((price.free_allowance or 0) - (usage.voice_secs or 0), 0),
        "live_chat": max((price.free_allowance or 0) - (usage.live_secs or 0), 0),
    }[feature]

    billable = max(units - free_left, 0)
    cost = billable * price.price_cents

    # Update usage counters
    if feature == "text":
        usage.text_count += units
    elif feature == "voice":
        usage.voice_secs += units
    else:
        usage.live_secs += units
    db.add(usage)

    # Debit wallet
    if cost:
        wallet = await db.get(CreditWallet, user_id) or CreditWallet(user_id=user_id)
        if (wallet.balance_cents or 0) < cost:
            raise HTTPException(402, "Insufficient credits")
        wallet.balance_cents = (wallet.balance_cents or 0) - cost
        db.add(wallet)

    db.add(CreditTransaction(
        user_id=user_id,
        feature=feature,
        units=-units,
        amount_cents=-cost,
        meta=meta,
    ))
    await db.commit()
    return cost

async def topup_wallet(db, user_id: int, cents: int, source: str):
    """Add credits to user's wallet and log the transaction."""
    wallet = await db.get(CreditWallet, user_id) or CreditWallet(user_id=user_id)
    if wallet.balance_cents is None:
        wallet.balance_cents = 0
    wallet.balance_cents += cents
    db.add_all([
        wallet,
        CreditTransaction(
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

# map feature -> which counter to read on DailyUsage
_USAGE_FIELD = {
    "text": "text_count",
    "voice": "voice_secs",
    "live_chat": "live_secs",
}

async def can_afford(
    db: AsyncSession,
    *,
    user_id: int,
    feature: str,
    units: int,
) -> tuple[bool, int, int]:
    """
    Returns (ok, cost_cents, free_left)
      - ok = True if user can afford 'units'
      - cost_cents = how much would be charged (after free allowance)
      - free_left = remaining free allowance for that feature today
    No DB mutations.
    """
    # pricing
    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        # no pricing? don't block
        return True, 0, 0

    # usage today
    today = date.today()
    usage: DailyUsage | None = await db.get(DailyUsage, (user_id, today))
    # base counters
    text_used = getattr(usage, "text_count", 0) if usage else 0
    voice_used = getattr(usage, "voice_secs", 0) if usage else 0
    live_used  = getattr(usage, "live_secs",  0) if usage else 0

    if feature == "text":
        used = text_used
    elif feature == "voice":
        used = voice_used
    else:
        used = live_used

    free_left = max((price.free_allowance or 0) - (used or 0), 0)
    billable = max(units - free_left, 0)
    cost_cents = billable * (price.price_cents or 0)

    # wallet
    wallet = await db.get(CreditWallet, user_id)
    balance = wallet.balance_cents if wallet and wallet.balance_cents is not None else 0

    ok = balance >= cost_cents
    return ok or (cost_cents == 0), cost_cents, free_left

async def get_remaining_units(db: AsyncSession, user_id: int, feature: str) -> int:
    """
    Compute how many units (messages, seconds, etc.) the user can still afford
    = free_allowance_left + wallet_balance / unit_price
    """
    from sqlalchemy import select
    from datetime import date
    from app.db.models import Pricing, DailyUsage, CreditWallet

    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        return 0

    unit_price_cents = price.price_cents
    free_allowance = price.free_allowance or 0

    # usage today
    today = date.today()
    usage: DailyUsage | None = await db.get(DailyUsage, (user_id, today))
    used = getattr(usage, f"{feature}_secs", 0) if usage else 0
    free_left = max(free_allowance - (used or 0), 0)

    # wallet
    wallet: CreditWallet | None = await db.get(CreditWallet, user_id)
    balance_cents = wallet.balance_cents if wallet else 0
    paid = balance_cents // unit_price_cents if unit_price_cents > 0 else 0

    return int(free_left + paid)