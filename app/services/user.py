from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InfluencerWallet, DailyUsage, Pricing


from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InfluencerWallet, DailyUsage, Pricing

async def _get_usage_snapshot_simple(
    db: AsyncSession,
    *,
    user_id: int,
    influencer_id: str,
    is_18: bool,
) -> dict:
    today = date.today()

    # ---- pricing ----
    pricing_rows = (
        await db.execute(
            select(Pricing).where(Pricing.is_active.is_(True))
        )
    ).scalars().all()

    pricing = {p.feature: p for p in pricing_rows}

    def _price_and_free(feature: str) -> tuple[int, int]:
        p = pricing.get(feature)
        if not p:
            return 0, 0
        return int(p.price_cents or 0), int(p.free_allowance or 0)

    text_price, text_free = _price_and_free("text")
    text18_price, text18_free = _price_and_free("text_18")

    # ---- daily usage ----
    normal_usage = await db.get(DailyUsage, (user_id, today, False))
    adult_usage = await db.get(DailyUsage, (user_id, today, True))

    normal_used = int(getattr(normal_usage, "text_count", 0) or 0)
    adult_used = int(getattr(adult_usage, "text_count", 0) or 0)

    normal_free_left = max(text_free - normal_used, 0)
    adult_free_left = max(text18_free - adult_used, 0)

    # ---- wallets ----
    wallets = (
        await db.execute(
            select(InfluencerWallet).where(
                InfluencerWallet.user_id == user_id,
                InfluencerWallet.influencer_id == influencer_id,
            )
        )
    ).scalars().all()

    normal_balance = 0
    adult_balance = 0

    for w in wallets:
        bal = int(w.balance_cents or 0)
        if w.is_18:
            adult_balance = bal
        else:
            normal_balance = bal

    def _paid_units(balance: int, unit_price: int) -> int:
        if unit_price <= 0:
            return 0
        return balance // unit_price

    normal_remaining = normal_free_left + _paid_units(normal_balance, text_price)
    adult_remaining = adult_free_left + _paid_units(adult_balance, text18_price)

    # ✅ FINAL FILTER (this is the fix)
    if is_18:
        return {
            "influencer_id": influencer_id,
            "adult": {
                "balance_cents": adult_balance,
                "messages": {
                    "remaining": adult_remaining,
                },
            },
            "active_mode": "adult",
        }

    return {
        "influencer_id": influencer_id,
        "normal": {
            "balance_cents": normal_balance,
            "messages": {
                "remaining": normal_remaining,
            },
        },
        "active_mode": "normal",
    }