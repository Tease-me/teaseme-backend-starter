import httpx
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.core.config import settings

# Simple in-memory token cache to avoid re-authing on every request.
_token = {"value": None, "exp": datetime.min}


def _require_airwallex_settings() -> None:
    if not settings.AIRWALLEX_BASE_URL or not settings.AIRWALLEX_CLIENT_ID or not settings.AIRWALLEX_API_KEY:
        raise HTTPException(500, "Airwallex credentials are not configured")


async def _get_token() -> str:
    _require_airwallex_settings()

    if _token["value"] and _token["exp"] > datetime.utcnow():
        return _token["value"]

    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/authentication/login",
            json={"client_id": settings.AIRWALLEX_CLIENT_ID, "api_key": settings.AIRWALLEX_API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()

    _token.update(
        value=data["token"],
        exp=datetime.utcnow() + timedelta(seconds=data.get("expires_in", 900) - 60),
    )
    return _token["value"]


async def create_billing_checkout(payload: dict) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/billing_checkouts/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    
