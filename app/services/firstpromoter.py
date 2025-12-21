import httpx
from app.core.config import settings

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
                "Authorization": f"Bearer {settings.FIRSTPROMOTER_API_KEY}",
                "Account-ID": settings.FIRSTPROMOTER_ACCOUNT_ID,
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()