import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from passlib.context import CryptContext

from app.db.models import User
from app.db.session import SessionLocal

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Default users to seed; adjust to your needs.
USERS = [
    {
        "email": "admin@example.com",
        "password": "admin123",
        "username": "admin",
        "is_verified": True,
    },
]


async def main():
    async with SessionLocal() as db:
        for entry in USERS:
            existing = await db.scalar(select(User).where(User.email == entry["email"]))
            if existing:
                # ensure fields stay in sync; do not overwrite password unless provided
                existing.username = entry.get("username") or existing.username
                existing.is_verified = entry.get("is_verified", existing.is_verified)
                if entry.get("password"):
                    existing.password_hash = pwd_context.hash(entry["password"])
                db.add(existing)
                print(f"Updated user {entry['email']}")
                continue

            user = User(
                email=entry["email"],
                username=entry.get("username"),
                password_hash=pwd_context.hash(entry["password"]),
                is_verified=entry.get("is_verified", False),
                created_at=datetime.now(timezone.utc),
            )
            db.add(user)
            print(f"Inserted user {entry['email']}")

        await db.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

    # to run:
    # poetry run python -m app.scripts.seed_users
