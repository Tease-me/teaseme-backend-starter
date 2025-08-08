from fastapi import APIRouter, HTTPException, Depends
import httpx

from app.db.session import get_db
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.schemas.elevenlabs import SignedUrlRequest

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY

async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str):
    influencer = await db.get(Influencer, influencer_id)
    if influencer and getattr(influencer, "influencer_agent_id_third_part", None):
        return influencer.influencer_agent_id_third_part
    raise HTTPException(404, "Influencer or influencer_agent_id_third_part not found")

@router.post("/signed-url")
async def get_signed_url(
    body: SignedUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    agent_id = await get_agent_id_from_influencer(db, body.influencer_id)
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    payload = {"agent_id": agent_id}

    # Pass a per-session custom greeting if provided
    if body.first_message:
        payload["conversation_config"] = {"first_message": body.first_message}

    async with httpx.AsyncClient(timeout=15) as client:
        # Prefer POST with JSON (supports conversation_config)
        resp = await client.post(
            f"{ELEVENLABS_BASE}/convai/conversation/get-signed-url",
            json=payload,
            headers=headers,
        )

        # Some accounts only allow GET; try fallback if needed
        if resp.status_code in (404, 405):
            resp = await client.get(
                f"{ELEVENLABS_BASE}/convai/conversation/get-signed-url",
                params={"agent_id": agent_id},
                headers=headers,
            )

        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Failed to get signed url: {resp.text}")

        data = resp.json()
        signed_url = data.get("signed_url")
        if not signed_url:
            raise HTTPException(502, "Signed URL missing in ElevenLabs response")
        return {"signed_url": signed_url}
    
@router.get("/signed-url_old")
async def get_signed_url_old(
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