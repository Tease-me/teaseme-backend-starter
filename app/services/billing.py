import subprocess
import tempfile

from sqlalchemy import select
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
        if wallet.balance_cents < cost:
            raise HTTPException(402, "Insufficient credits")
        wallet.balance_cents -= cost
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