from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Influencer


async def ensure_influencer(db: AsyncSession, influencer_id: str) -> Influencer:
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return influencer
