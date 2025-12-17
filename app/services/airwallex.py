import httpx
from datetime import datetime, timedelta
from uuid import uuid4
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
            headers={
                "x-client-id": settings.AIRWALLEX_CLIENT_ID,
                "x-api-key": settings.AIRWALLEX_API_KEY,
            },
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
        if resp.status_code >= 400:
            print(f"[Airwallex ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        return resp.json()


async def create_auto_topup_payment_intent(
    *,
    customer_id: str,
    amount_cents: int,
    currency: str = "USD",
    description: str | None = None,
    request_id: str | None = None,
    merchant_order_id: str | None = None,
) -> dict:
    """
    Charge a saved payment method for the given customer to top up their wallet.
    Expects the customer to have an attached default payment method from a prior SETUP checkout.
    """
    if amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be positive.")

    token = await _get_token()
    payload = {
        "request_id": request_id or str(uuid4()),
        "merchant_order_id": merchant_order_id or f"wallet-topup-{uuid4()}",
        "customer_id": customer_id,
        "amount": amount_cents,
        "currency": currency,
    }
    if description:
        payload["description"] = description

    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/pa/payment_intents/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"[Airwallex AutoTopup ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        return resp.json()
    

async def create_customer(
    *,
    email: str,
    name: str,
    reference_id: str | None = None,
) -> dict:
    """
    Create a Customer in Airwallex.
    """
    token = await _get_token()
    payload = {
        "request_id": str(uuid4()),
        "merchant_customer_id": reference_id or str(uuid4()),
        "email": email,
        "first_name": name.split(" ")[0],
        "last_name": " ".join(name.split(" ")[1:]) if " " in name else "User",
        "additional_info": {"registered_via": "teaseme_backend"},
    }
    
    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/pa/customers/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"[Airwallex Customer ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        print(f"[Airwallex Customer SUCCESS] Body: {data}")
        return data


async def create_payment_link(payload: dict) -> dict:
    """
    Create a Payment Link (PA) in Airwallex.
    Use this to replace billing_checkouts for consistent cus_ ID usage.
    """
    token = await _get_token()
    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/pa/payment_links/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"[Airwallex PaymentLink ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        return resp.json()


async def create_payment_intent(
    *,
    customer_id: str,
    amount_cents: int,
    currency: str = "USD",
    payment_method_id: str | None = None,
    save_payment_method: bool = True,
    request_id: str | None = None,
    merchant_order_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Create a Payment Intent for custom UI card payments.
    If payment_method_id is provided, the intent can be confirmed immediately.
    """
    if amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be positive.")

    token = await _get_token()
    payload = {
        "request_id": request_id or str(uuid4()),
        "merchant_order_id": merchant_order_id or f"card-topup-{uuid4()}",
        "customer_id": customer_id,
        "amount": amount_cents,
        "currency": currency,
        "capture_method": "automatic",
    }
    
    if save_payment_method:
        payload["payment_method_options"] = {
            "card": {"auto_capture": True}
        }
    
    if metadata:
        payload["metadata"] = metadata

    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/pa/payment_intents/create",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"[Airwallex PaymentIntent CREATE ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        return resp.json()


async def confirm_payment_intent(
    *,
    payment_intent_id: str,
    payment_method_id: str,
    customer_id: str | None = None,
    save_payment_method: bool = True,
) -> dict:
    """
    Confirm a Payment Intent with a payment method from the frontend.
    This charges the card.
    """
    token = await _get_token()
    
    payload = {
        "request_id": str(uuid4()),
        "payment_method_id": payment_method_id,
    }
    
    if customer_id:
        payload["customer_id"] = customer_id
    
    if save_payment_method:
        payload["payment_method_options"] = {
            "card": {"auto_capture": True}
        }
        payload["save_payment_method"] = True

    async with httpx.AsyncClient(base_url=settings.AIRWALLEX_BASE_URL, timeout=15) as client:
        resp = await client.post(
            f"/api/v1/pa/payment_intents/{payment_intent_id}/confirm",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"[Airwallex PaymentIntent CONFIRM ERROR] Status: {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
        return resp.json()
