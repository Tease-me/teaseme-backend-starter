"""Database seeding script for system prompts."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from app.db.models import SystemPrompt
from app.db.session import SessionLocal
from app.data.prompts import get_all_prompts
from app.services.system_prompt_service import PROMPT_CACHE_PREFIX
from app.utils.infrastructure.redis_pool import get_redis


async def upsert_prompt(
    db, 
    key: str, 
    name: str, 
    prompt: str, 
    description: str | None, 
    type: str
) -> None:
    """Insert or skip existing prompt."""
    existing = await db.scalar(
        select(SystemPrompt).where(SystemPrompt.key == key)
    )

    if existing:
        print(f"✓ Skipped {key} (already exists)")
    else:
        now = datetime.now(timezone.utc)
        db.add(
            SystemPrompt(
                key=key,
                name=name,
                prompt=prompt,
                type=type,
                description=description,
                created_at=now,
                updated_at=now,
            )
        )
        print(f"✓ Inserted {key}")


async def sync_redis_cache(all_prompts: dict) -> None:
    print("\n🔄 Syncing Redis cache...")
    try:
        redis = await get_redis()
        for key in all_prompts:
            cache_key = f"{PROMPT_CACHE_PREFIX}:{key}"
            await redis.delete(cache_key)
            print(f"  ✓ Invalidated {key}")
        print("✅ Redis cache synced.")
    except Exception as e:
        print(f"⚠️  Redis sync failed (cache will self-heal via TTL): {e}")


async def main():
    """Seed all prompts from registry."""
    all_prompts = get_all_prompts()
    
    async with SessionLocal() as db:
        for key, data in all_prompts.items():
            await upsert_prompt(
                db, 
                key, 
                data["name"], 
                data["prompt"], 
                data.get("description"), 
                data["type"]
            )
        await db.commit()
    
    await sync_redis_cache(all_prompts)
    
    print(f"\n✅ Done! Processed {len(all_prompts)} prompts.")


if __name__ == "__main__":
    asyncio.run(main())
    # poetry run python -m app.scripts.seed_prompts
