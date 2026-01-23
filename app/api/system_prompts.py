import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.utils.deps import get_current_user
from app.services.system_prompt_service import (
    get_system_prompt,
    update_system_prompt,
    list_system_prompts,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/system-prompts", tags=["system-prompts"])


class SystemPromptUpdate(BaseModel):
    prompt: str
    description: Optional[str] = None


@router.get("/", response_model=List[dict])
async def list_prompts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await list_system_prompts(db)
        return [
            {
                "key": r.key,
                "description": r.description,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to list system prompts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list system prompts")


@router.get("/{key}")
async def get_prompt(
    key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        text = await get_system_prompt(db, key)
        if not text:
            raise HTTPException(404, f"Prompt not found for key={key}")
        return {"key": key, "prompt": text}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to get system prompt %s: %s", key, e)
        raise HTTPException(status_code=500, detail="Failed to get system prompt")


@router.post("/{key}")
async def upsert_prompt(
    key: str,
    body: SystemPromptUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await update_system_prompt(
            db,
            key=key,
            new_prompt=body.prompt,
            description=body.description,
        )
        return {
            "key": row.key,
            "description": row.description,
            "updated_at": row.updated_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to upsert system prompt %s: %s", key, e)
        raise HTTPException(status_code=500, detail="Failed to update system prompt")