from __future__ import annotations

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import logging

from app.db.models import SystemPrompt

from app.db.session import SessionLocal
from app.agents.memory import store_fact 


log = logging.getLogger(__name__)


async def get_system_prompt(db: AsyncSession, key: str) -> str:
    """
    Returns the prompt string for the given key.
    If not found, logs a warning and returns empty string.
    """
    result = await db.execute(
        select(SystemPrompt).where(SystemPrompt.key == key)
    )
    row: Optional[SystemPrompt] = result.scalar_one_or_none()

    if not row:
        log.warning("SystemPrompt not found for key=%s", key)
        return ""

    return row.prompt


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
    return row