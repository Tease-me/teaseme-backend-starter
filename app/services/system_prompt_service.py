from __future__ import annotations

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import logging

from app.db.models import SystemPrompt
from app.db.session import SessionLocal
from app.utils.redis_pool import get_redis

log = logging.getLogger(__name__)

# Cache configuration
PROMPT_CACHE_PREFIX = "sys_prompt"
PROMPT_CACHE_TTL = 600  # 10 minutes


async def get_system_prompt(db: AsyncSession, key: str) -> str:
    """
    Returns the prompt string for the given key.
    Uses Redis cache with 10-minute TTL to avoid repeated DB queries.
    
    Note: On cache miss, creates its own session to avoid concurrent access
    issues when this function is called in parallel via asyncio.gather.
    """
    cache_key = f"{PROMPT_CACHE_PREFIX}:{key}"
    
    # Try Redis cache first
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached
    except Exception as e:
        log.warning("Redis cache read failed for key=%s: %s", key, e)
    
    # Cache miss - query database with a FRESH session to avoid concurrency issues
    # This is necessary because asyncio.gather may call this function in parallel,
    # and SQLAlchemy AsyncSession doesn't allow concurrent operations on same session
    async with SessionLocal() as fresh_db:
        result = await fresh_db.execute(
            select(SystemPrompt).where(SystemPrompt.key == key)
        )
        row: Optional[SystemPrompt] = result.scalar_one_or_none()

    if not row:
        log.warning("SystemPrompt not found for key=%s", key)
        return ""

    # Store in cache
    try:
        redis = await get_redis()
        await redis.setex(cache_key, PROMPT_CACHE_TTL, row.prompt)
    except Exception as e:
        log.warning("Redis cache write failed for key=%s: %s", key, e)

    return row.prompt


async def invalidate_prompt_cache(key: str) -> bool:
    """
    Invalidates the cache for a specific prompt key.
    Call this after updating a system prompt.
    """
    cache_key = f"{PROMPT_CACHE_PREFIX}:{key}"
    try:
        redis = await get_redis()
        await redis.delete(cache_key)
        log.info("Invalidated cache for prompt key=%s", key)
        return True
    except Exception as e:
        log.error("Failed to invalidate cache for key=%s: %s", key, e)
        return False


async def list_system_prompts(db: AsyncSession) -> List[SystemPrompt]:
    """
    Returns all system prompts (useful for admin/debug).
    """
    result = await db.execute(select(SystemPrompt))
    return list(result.scalars().all())


async def update_system_prompt(
    db: AsyncSession,
    key: str,
    new_prompt: str,
    description: Optional[str] = None,
    name: Optional[str] = None,
    prompt_type: Optional[str] = None,
) -> SystemPrompt:
    """
    Creates or updates a system prompt by key.
    Automatically invalidates the Redis cache for this key.
    
    Args:
        prompt_type: One of "18+", "normal", or "adult". Defaults to "normal".
    """
    result = await db.execute(
        select(SystemPrompt).where(SystemPrompt.key == key)
    )
    row: Optional[SystemPrompt] = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row:
        row.prompt = new_prompt
        if description is not None:
            row.description = description
        if name is not None:
            row.name = name
        if prompt_type is not None:
            row.type = prompt_type
        row.updated_at = now
    else:
        row = SystemPrompt(
            key=key,
            name=name,
            prompt=new_prompt,
            description=description,
            type=prompt_type or "normal",
            created_at=now,
            updated_at=now,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    
    # Invalidate cache after successful update
    await invalidate_prompt_cache(key)
    
    return row