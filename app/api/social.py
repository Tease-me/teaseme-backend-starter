
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import PreInfluencer

import httpx 

router = APIRouter(prefix="/social", tags=["social"])


class SocialValidateIn(BaseModel):
    platform: str
    handle: str


class SocialValidateOut(BaseModel):
    platform: str
    username: str
    followers_count: int

@router.post("/validate", response_model=SocialValidateOut)
async def validate_social_media(
    payload: SocialValidateIn,
    db: AsyncSession = Depends(get_db),
):
    platform = payload.platform.lower().strip()
    handle = payload.handle.strip()

    if not handle:
        raise HTTPException(status_code=400, detail="Handle is empty.")

    username = handle.lstrip("@").strip()

    if platform != "instagram":
        raise HTTPException(
            status_code=400,
            detail="Unsupported platform. Only 'instagram' is handled for now.",
        )

    normalized = username
    with_at = "@" + username

    result = await db.execute(
        select(PreInfluencer).where(
            (PreInfluencer.username == normalized) |
            (PreInfluencer.username == with_at)
        )
    )

    pre_inf = result.scalar_one_or_none()

    if pre_inf is None:
        raise HTTPException(status_code=404, detail="Pre-influencer not found.")

    if not pre_inf.ig_user_id or not pre_inf.ig_access_token:
        raise HTTPException(400, "Instagram not connected")

    url = f"https://graph.facebook.com/v19.0/{pre_inf.ig_user_id}"
    params = {
        "fields": "username,followers_count",
        "access_token": pre_inf.ig_access_token,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)

    data = r.json()

    return SocialValidateOut(
        platform="instagram",
        username=data.get("username", username),
        followers_count=data.get("followers_count", 0)
    )