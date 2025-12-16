from app.services.airwallex import create_billing_checkout
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.billing import topup_wallet
from app.db.models import CreditWallet
from app.schemas.billing import TopUpRequest,BillingCheckoutRequest
from app.db.session import get_db
from app.utils.deps import get_current_user
from app.core.config import settings
import http.client, json
from uuid import uuid4
router = APIRouter(prefix="/billing", tags=["billing"])

@router.get("/balance")
async def get_balance(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    wallet = await db.get(CreditWallet, user.id)
    return {"balance_cents": wallet.balance_cents if wallet else 0}

@router.post("/topup")
async def topup(req: TopUpRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    new_balance = await topup_wallet(db, user.id, req.cents, source="manual_test")
    return {"ok": True, "new_balance_cents": new_balance}

@router.post("/billing-checkout")
async def billing_checkout(req: BillingCheckoutRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    paylod = {
        "request_id": str(uuid4()),
        "mode": req.mode,
        "currency": req.currency,
        "line_items": [{"price_id": req.price_id, "quantity": req.quantity}],
        "success_url": req.success_url,
        "back_url": req.cancel_url,
        "customer_data": {
            "email": user.email,
            "name": user.fullname or user.email,
            "type": "INDIVIDUAL",
        },
        
    }
    checkout = await create_billing_checkout(paylod)
    return {
        "checkout_id": checkout.get("id"),
        "status": checkout.get("status"),
        "next_action": checkout.get("next_action"),
    }
    pass