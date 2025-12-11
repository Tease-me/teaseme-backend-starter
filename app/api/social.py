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

    if platform != "instagram":
        raise HTTPException(400, "Only instagram supported for now.")

    # normaliza handle
    username = handle.lstrip("@").strip()
    normalized = username
    with_at = "@" + username

    result = await db.execute(
        select(PreInfluencer).where(
            (PreInfluencer.username == normalized) | (PreInfluencer.username == with_at)
        )
    )
    pre_inf = result.scalar_one_or_none()

    if not pre_inf:
        raise HTTPException(404, "Pre-influencer not found.")

    if not pre_inf.ig_user_id or not pre_inf.ig_access_token:
        raise HTTPException(400, "Instagram not connected.")

    url = f"https://graph.facebook.com/v19.0/{pre_inf.ig_user_id}"
    params = {
        "fields": "username,followers_count",
        "access_token": pre_inf.ig_access_token,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    print("IG USER RESPONSE:", data)

    if "error" in data:
        raise HTTPException(400, f"Instagram API error: {data['error']}")

    followers = data.get("followers_count", 0)
    ig_username = data.get("username", username)

    return SocialValidateOut(
        platform="instagram",
        username=ig_username,
        followers_count=followers,
    )