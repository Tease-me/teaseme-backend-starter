from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.billing import topup_wallet
from app.db.models import CreditWallet
from app.schemas.billing import TopUpRequest
from app.db.session import get_db
from app.utils.deps import get_current_user

import httpx
from decimal import Decimal
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from app.services.paypal import paypal_access_token
from app.services.firstpromoter import fp_track_sale_v2
from app.db.models import PayPalTopUp
from app.core.config import settings

router = APIRouter(prefix="/billing", tags=["billing"])

@router.get("/balance")
async def get_balance(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    wallet = await db.get(CreditWallet, user.id)
    return {"balance_cents": wallet.balance_cents if wallet else 0}

@router.post("/topup")
async def topup(req: TopUpRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    new_balance = await topup_wallet(db, user.id, req.cents, source="manual_test")
    return {"ok": True, "new_balance_cents": new_balance}

class PayPalCreateReq(BaseModel):
    cents: PositiveInt
    currency: str | None = None  # optional override

@router.post("/paypal/create-order")
async def paypal_create_order(req: PayPalCreateReq, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    token = await paypal_access_token()

    currency = req.currency or getattr(settings, "PAYPAL_CURRENCY", "AUD")
    value = f"{(Decimal(req.cents) / Decimal(100)):.2f}"

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{"amount": {"currency_code": currency, "value": value}}],
                "application_context": {
                    "user_action": "PAY_NOW",
                    "return_url": settings.PAYPAL_RETURN_URL,
                    "cancel_url": settings.PAYPAL_CANCEL_URL,
                },
            },
        )
        r.raise_for_status()
        data = r.json()

    order_id = data["id"]
    approve_url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
    if not approve_url:
        raise HTTPException(500, "PayPal approve url missing")

    db.add(PayPalTopUp(user_id=user.id, order_id=order_id, cents=req.cents, status="CREATED", credited=False))
    await db.commit()

    return {"order_id": order_id, "approve_url": approve_url}

class PayPalCaptureReq(BaseModel):
    order_id: str

@router.post("/paypal/capture")
async def paypal_capture(
    req: PayPalCaptureReq,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    row = await db.scalar(select(PayPalTopUp).where(PayPalTopUp.order_id == req.order_id))
    if not row:
        raise HTTPException(404, "Unknown order_id")

    if row.user_id != user.id:
        raise HTTPException(403, "Order does not belong to this user")

    # If already credited, don't double-credit or double-track
    if row.credited:
        wallet = await db.get(CreditWallet, user.id)
        return {"ok": True, "credited": True, "new_balance_cents": wallet.balance_cents if wallet else 0}

    token = await paypal_access_token()

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{req.order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        cap = r.json()

    status = cap.get("status", "UNKNOWN")

    if status != "COMPLETED":
        row.status = status
        db.add(row)
        await db.commit()
        return {"ok": False, "status": status, "credited": False}

    new_balance = await topup_wallet(db, user.id, row.cents, source=f"paypal:{req.order_id}")

    row.status = "COMPLETED"
    row.credited = True

    try:
        await fp_track_sale_v2(
            email=getattr(user, "email", None),
            uid=str(user.id),
            amount_cents=row.cents,
            event_id=req.order_id,
            ref_id=getattr(user, "fp_ref_id", None),
            plan="wallet_topup",
        )
    except Exception as e:
        print("FirstPromoter track sale failed:", e)

    db.add(row)
    await db.commit()

    return {"ok": True, "status": "COMPLETED", "credited": True, "new_balance_cents": new_balance}