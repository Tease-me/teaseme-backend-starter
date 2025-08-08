from fastapi import APIRouter, HTTPException, Depends, Query
import httpx
from app.db.session import get_db
from app.db.models import Influencer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from typing import Dict, List, Optional
import random

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])

ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY

# --- TEMP in-memory greetings (no DB) ---
_GREETINGS: Dict[str, List[str]] = {
    "loli": [
        "Mmm… I’ve been waiting for you. Ready to tease me?",
        "Well, look who showed up. Think you can handle me today?",
        "Hey trouble… I missed you. What’s your excuse?",
    ],
    "anna": [
        "Nyaa~! You’re back! I was just thinking about you!",
        "Ooh! It’s you! Did you bring me something cute?",
        "UwU~ guess who’s my favorite human?",
    ],
    "bella": [
        "Hi love… you’ve been on my mind all day.",
        "Hey darling, I was hoping you’d call.",
        "Mmm… my day just got better.",
    ],
}
_rr_index: Dict[str, int] = {}

def _pick_greeting(influencer_id: str, mode: str) -> str:
    options = _GREETINGS.get(influencer_id)
    if not options:
        # flatten all as a fallback
        all_opts = sum(_GREETINGS.values(), [])
        return random.choice(all_opts) if all_opts else "Hey there."
    if mode == "rr":
        i = _rr_index.get(influencer_id, -1) + 1
        i %= len(options)
        _rr_index[influencer_id] = i
        return options[i]
    return random.choice(options)

async def get_agent_id_from_influencer(db: AsyncSession, influencer_id: str):
    influencer = await db.get(Influencer, influencer_id)
    if influencer and getattr(influencer, "influencer_agent_id_third_part", None):
        return influencer.influencer_agent_id_third_part
    raise HTTPException(404, "Influencer or influencer_agent_id_third_part not found")

@router.get("/signed-url")
async def get_signed_url(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    
    first_message: Optional[str] = Query(None),
    # random or rr (round-robin)
    greeting_mode: str = Query("random", regex="^(random|rr)$"),
):
    agent_id = await get_agent_id_from_influencer(db, influencer_id)
    headers = {"xi-api-key": ELEVENLABS_API_KEY}

    greeting = first_message or _pick_greeting(influencer_id, greeting_mode)

    async with httpx.AsyncClient() as client:
        patch = await client.patch(
            f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
            headers=headers,
            json={"first_message": greeting},
        )
        if patch.status_code >= 400:
            raise HTTPException(status_code=424, detail=f"Failed to update first message: {patch.text}")

        r = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=headers,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get signed url")
        return {"signed_url": r.json()["signed_url"]}