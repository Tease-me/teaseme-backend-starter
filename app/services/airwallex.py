import httpx 
from datetime import datetime, timedelta
from app.core.config import settings

_token = {"value": None, "exp": datetime.min()}
async def _get_token() -> str:
    if _token["value"] and _token["exp"] > datetime.utcnow():
        return _token["value"]
    async with httpx.AysncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        r = await client.post(
            "/api/v1/auth/token",
            json={"client_id": settings.AIRWALLEX_CLIENT_ID, "api_key": settings.AIRWALLEX_API_KEY},
        )
        r.raise_for_status()
        data = r.json()
    _token.update(
        value=data["token"],
        exp=datetime.utcnow() + timedelta(seconds=data.get("expires_in", 900) - 60),
    )
    return _token["value"]

async def create_billing_checkout(payload: dict) -> dict:
    token = await _get_token()
    async with httpx.AysncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        r = await client.post(
            "/api/v1/billing_checkouts/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "content-type": "application/json"},
        )
        r.raise_for_status()
        return r.json()
    