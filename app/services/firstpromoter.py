import httpx
from app.core.config import settings
import logging
log = logging.getLogger(__name__)

def _fp_unwrap(payload: dict | None) -> dict | None:
    if not payload or not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def fp_extract_email(payload: dict | None) -> str | None:
    data = _fp_unwrap(payload)
    if not data:
        return None
    email = data.get("email")
    return str(email) if email else None


def fp_extract_parent_promoter_id(payload: dict | None) -> int | None:
    data = _fp_unwrap(payload)
    if not data:
        return None
    for key in ("parent_promoter_id", "parent_id"):
        val = data.get(key)
        if val is not None and str(val).isdigit():
            return int(val)
    parent = data.get("parent_promoter") or data.get("parent")
    if isinstance(parent, dict):
        val = parent.get("id")
        if val is not None and str(val).isdigit():
            return int(val)
    return None


async def fp_get_promoter_v2(promoter_id: int | str) -> dict | None:
    token = settings.FIRSTPROMOTER_TOKEN
    account_id = settings.FIRSTPROMOTER_ACCOUNT_ID
    if not token or not account_id:
        return None

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://api.firstpromoter.com/api/v2/company/promoters/{promoter_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Account-ID": account_id,
            },
        )
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            log.error("FP get promoter failed: %s %s id=%s", r.status_code, r.text, promoter_id)
        r.raise_for_status()
        return r.json()

async def fp_track_sale_v2(*, email: str | None, uid: str | None, amount_cents: int, event_id: str, tid: str | None = None, ref_id: str | None = None, plan: str | None = None):
    """
    FirstPromoter v2 sale tracking:
    POST https://v2.firstpromoter.com/api/v2/track/sale
    Headers:
      Authorization: Bearer <token>
      Account-ID: <account_id>
    Body:
      email OR uid
      event_id
      amount (cents)
      optional tid/ref_id/plan
    """
    token = settings.FIRSTPROMOTER_TOKEN
    account_id = settings.FIRSTPROMOTER_ACCOUNT_ID

    if not token or not account_id:
        return None 

    payload: dict = {
        "event_id": event_id,
        "amount": int(amount_cents),
    }

    if email:
        payload["email"] = email
    if uid:
        payload["uid"] = uid
    if tid:
        payload["tid"] = tid
    if ref_id:
        payload["ref_id"] = ref_id
    if plan:
        payload["plan"] = plan

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://v2.firstpromoter.com/api/v2/track/sale",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Account-ID": account_id,
            },
        )
        r.raise_for_status()
        return r.json()
    
async def fp_track_signup(
    *,
    email: str | None,
    uid: str | None,
    tid: str | None,
):
    if not tid:
        return

    payload = {}
    if email:
        payload["email"] = email
    if uid:
        payload["uid"] = uid

    payload["tid"] = tid

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://v2.firstpromoter.com/api/v2/track/signup",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.FIRSTPROMOTER_TOKEN}",
                "Account-ID": settings.FIRSTPROMOTER_ACCOUNT_ID,
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()


async def fp_create_promoter(*, email: str, first_name: str, last_name: str, cust_id: str, parent_promoter_id: int | None = None):
    api_key = settings.FIRSTPROMOTER_API_KEY
    if not api_key:
        return None

    payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "cust_id": cust_id,
            "website": "https://teaseme.live/join"
    }
    if parent_promoter_id:
        payload["parent_promoter_id"] = int(parent_promoter_id) 

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://firstpromoter.com/api/v1/promoters/create",
            json=payload,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )

        if r.status_code >= 400:
            log.error("FP create promoter failed: %s %s payload=%s", r.status_code, r.text, payload)
        
        r.raise_for_status()
        return r.json()
    
async def fp_find_promoter_id_by_ref_token(ref_token: str) -> int | None:
    token = settings.FIRSTPROMOTER_TOKEN
    account_id = settings.FIRSTPROMOTER_ACCOUNT_ID
    if not token or not account_id:
        return None

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://api.firstpromoter.com/api/v2/company/promoters",
            params={"search": ref_token},
            headers={
                "Authorization": f"Bearer {token}",
                "Account-ID": account_id,
            },
        )
        r.raise_for_status()
        data = r.json().get("data", [])

    for p in data:
        for pc in p.get("promoter_campaigns", []):
            if pc.get("ref_token") == ref_token:
                return int(p["id"])

    return None
