from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import PreInfluencer

import httpx
import urllib.parse
from app.core.config import settings


router = APIRouter(prefix="/auth/instagram", tags=["auth"])


@router.get("/login")
async def instagram_login(
    pre_inf_id: int = Query(...),
):

    if not settings.META_APP_ID or not settings.INSTAGRAM_REDIRECT_URI:
        raise HTTPException(500, "Meta config missing (META_APP_ID / INSTAGRAM_REDIRECT_URI)")

    base = "https://www.facebook.com/v19.0/dialog/oauth"

    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
        "scope": "public_profile,email",
        "response_type": "code",
        "state": str(pre_inf_id),
    }

    url = base + "?" + urllib.parse.urlencode(params)
    return {"url": url}


async def find_ig_user_id_from_token(access_token: str) -> str | None:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": access_token, "fields": "name,instagram_business_account"},
        )
        pages_data = resp.json()

    print("ME/ACCOUNTS RESPONSE:", pages_data)

    for page in pages_data.get("data", []):
        ig = page.get("instagram_business_account")
        if ig and ig.get("id"):
            return ig["id"]

    return None

@router.get("/callback")
async def instagram_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not settings.META_APP_ID or not settings.META_APP_SECRET or not settings.INSTAGRAM_REDIRECT_URI:
        raise HTTPException(500, "Meta app not configured properly.")

    try:
        pre_inf_id = int(state)
    except ValueError:
        raise HTTPException(400, "Invalid state (pre_inf_id)")

    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    params = {
        "client_id": settings.META_APP_ID,
        "client_secret":settings.META_APP_SECRET,
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(token_url, params=params)
        short_data = r.json()
    print("SHORT TOKEN RESPONSE:", short_data)

    if "access_token" not in short_data:
        raise HTTPException(400, f"Could not get short-lived token: {short_data}")

    short_token = short_data["access_token"]

    exchange_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    exchange_params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.META_APP_ID,
        "client_secret": settings.META_APP_SECRET,
        "fb_exchange_token": short_token,
    }

    async with httpx.AsyncClient() as client:
        long_r = await client.get(exchange_url, params=exchange_params)
        long_data = long_r.json()

    print("LONG TOKEN RESPONSE:", long_data)

    long_token = long_data.get("access_token")
    if not long_token:
        raise HTTPException(400, f"Could not exchange token: {long_data}")

    ig_user_id = await find_ig_user_id_from_token(long_token)
    if not ig_user_id:
        raise HTTPException(
            status_code=400,
            detail="No Instagram Business/Creator account linked. Make sure your Instagram is a professional account and is connected to a Facebook Page."
        )

    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_inf_id)
    )
    pre_inf = result.scalar_one_or_none()
    if not pre_inf:
        raise HTTPException(404, "PreInfluencer not found")

    pre_inf.ig_user_id = ig_user_id
    pre_inf.ig_access_token = long_token

    await db.commit()

    return {
        "status": "connected",
        "pre_inf_id": pre_inf_id,
        "ig_user_id": ig_user_id,
    }