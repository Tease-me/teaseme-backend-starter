from fastapi import APIRouter, HTTPException, Depends
import httpx
import os
from app.db.session import get_db
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY

async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str):
    influencer = await db.get(Influencer, influencer_id)
    if influencer and getattr(influencer, "influencer_agent_id_third_part", None):
        return influencer.influencer_agent_id_third_part
    raise HTTPException(404, "Influencer or influencer_agent_id_third_part not found")

@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    db: AsyncSession = Depends(get_db)
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=headers,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get signed url")
        return {"signed_url": r.json()["signed_url"]}