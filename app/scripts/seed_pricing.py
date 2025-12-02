import asyncio
from sqlalchemy import select

from app.db.models import Pricing
from app.db.session import SessionLocal

# Default pricing; adjust as needed.
PRICING_ROWS = [
    {
        "feature": "text",
        "unit": "message",
        "price_cents": 5,   # $0.05 per message
        "free_allowance": 100,  # e.g., first 100 messages/day free
        "is_active": True,
    },
    {
        "feature": "voice",
        "unit": "second",
        "price_cents": 2,   # $0.02 per second of audio
        "free_allowance": 120,  # e.g., first 2 minutes/day free
        "is_active": True,
    },
    {
        "feature": "live_chat",
        "unit": "second",
        "price_cents": 3,   # $0.03 per second of live chat
        "free_allowance": 120,
        "is_active": True,
    },
]


async def main():
    async with SessionLocal() as db:
        for row in PRICING_ROWS:
            existing = await db.scalar(
                select(Pricing).where(Pricing.feature == row["feature"])
            )
            if existing:
                existing.unit = row["unit"]
                existing.price_cents = row["price_cents"]
                existing.free_allowance = row["free_allowance"]
                existing.is_active = row["is_active"]
                db.add(existing)
                print(f"Updated pricing for {row['feature']}")
            else:
                db.add(Pricing(**row))
                print(f"Inserted pricing for {row['feature']}")
        await db.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

    # to run:
    # poetry run python -m app.scripts.seed_pricing
