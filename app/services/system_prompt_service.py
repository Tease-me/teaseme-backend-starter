from __future__ import annotations

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import logging

from app.db.models import SystemPrompt

from app.db.session import SessionLocal
from app.agents.prompts import get_fact_prompt, FACT_EXTRACTOR
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
) -> SystemPrompt:
    """
    Creates or updates a system prompt by key.
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
        row.updated_at = now
    else:
        row = SystemPrompt(
            key=key,
            prompt=new_prompt,
            description=description,
            created_at=now,
            updated_at=now,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return row


async def extract_and_store_facts_for_turn(
    message: str,
    recent_ctx: str,
    chat_id: str,
    cid: str,
) -> None:
    """
    Runs the fact extraction flow and stores new facts in the DB.
    Intended to be called from handle_turn (sync or background).
    """
    async with SessionLocal() as db:
        try:
            fact_prompt = await get_fact_prompt(db)

            facts_resp = await FACT_EXTRACTOR.ainvoke(
                fact_prompt.format(msg=message, ctx=recent_ctx)
            )

            facts_txt = facts_resp.content or ""
            lines = [ln.strip("- ").strip() for ln in facts_txt.split("\n") if ln.strip()]

            for line in lines[:5]:
                if line.lower() == "no new memories.":
                    continue
                await store_fact(db, chat_id, line)
        except Exception as ex:
            log.error("[%s] Fact extraction failed: %s", cid, ex, exc_info=True)