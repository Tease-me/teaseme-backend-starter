# app/api/auth_instagram.py

from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import PreInfluencer
import httpx
import urllib.parse
from app.core.config import settings

router = APIRouter(prefix="/auth/instagram", tags=["auth"])


# ------------------------------------------------------------
# 1) Create URL for Instagram Login
# ------------------------------------------------------------
@router.get("/login")
def instagram_login():
    base = "https://www.facebook.com/v19.0/dialog/oauth"
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
        "scope": "public_profile,email",
        "response_type": "code",
    }
    url = base + "?" + urllib.parse.urlencode(params)
    return {"url": url}


# ------------------------------------------------------------
# 2) Callback - exchange code for access token
# ------------------------------------------------------------
@router.get("/callback")
async def instagram_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    code = request.query_params.get("code")
    pre_inf_id = request.query_params.get("pre_inf_id")

    if not code:
        raise HTTPException(400, "Missing code")
    if not pre_inf_id:
        raise HTTPException(400, "Missing pre_inf_id")

    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    params = {
        "client_id":  settings.META_APP_ID,
        "client_secret":  settings.META_APP_SECRET,
        "redirect_uri":  settings.INSTAGRAM_REDIRECT_URI,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(token_url, params=params)
        data = r.json()

    if "access_token" not in data:
        raise HTTPException(400, "Could not get access token")

    short_token = data["access_token"]

    exchange_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    exchange_params = {
        "grant_type": "fb_exchange_token",
        "client_id":  settings.META_APP_ID,
        "client_secret":  settings.META_APP_SECRET,
        "fb_exchange_token": short_token,
    }

    async with httpx.AsyncClient() as client:
        long_r = await client.get(exchange_url, params=exchange_params)
        long_data = long_r.json()

    long_token = long_data.get("access_token")
    if not long_token:
        raise HTTPException(400, "Could not exchange token")

    async with httpx.AsyncClient() as client:
        pages_r = await client.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": long_token}
        )
        pages_data = pages_r.json()

    ig_user_id = None
    for p in pages_data.get("data", []):
        if "instagram_business_account" in p:
            ig_user_id = p["instagram_business_account"]["id"]
            break

    if not ig_user_id:
        raise HTTPException(400, "This user has no IG Business/Creator account linked.")

    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == int(pre_inf_id))
    )
    pre_inf = result.scalar_one_or_none()

    if not pre_inf:
        raise HTTPException(404, "PreInfluencer not found")

    pre_inf.ig_user_id = ig_user_id
    pre_inf.ig_access_token = long_token

    await db.commit()

    return {"status": "connected", "ig_user_id": ig_user_id}