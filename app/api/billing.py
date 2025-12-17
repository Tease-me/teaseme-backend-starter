from uuid import uuid4
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CreditWallet
from app.db.session import get_db
from app.schemas.billing import BillingCheckoutRequest, TopUpRequest
from app.services.airwallex import create_billing_checkout
from app.services.billing import topup_wallet
from app.utils.deps import get_current_user

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
async def billing_checkout(
    req: BillingCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    payload = {
        "request_id": str(uuid4()),
        "mode": req.mode,
        "currency": req.currency,
        "line_items": [{"price_id": req.price_id}],
        "success_url": req.success_url,
        "back_url": req.cancel_url,
    }
    billing_customer_id = req.billing_customer_id or getattr(user, "billing_customer_id",None)
    if user.billing_customer_id:
        payload["billing_customer_id"] = user.billing_customer_id
    else:
        payload["customer_data"] = {
            "email": user.email,
            "name": user.full_name or user.email,
            "type": "INDIVIDUAL",
        }
    
    checkout = await create_billing_checkout(payload)
    new_cust_id = checkout.get("billing_customer_id")
    if new_cust_id and not getattr(user, "billing_customer_id", None):
        user.billing_customer_id = new_cust_id
        db.add(user)
        await db.commit()
    if req.auto_topup_enabled is not None:
        wallet = await db.get(CreditWallet, user.id)
        wallet.auto_topup_enabled = req.auto_topup_enabled
        wallet.auto_topup_amount_cents = req.auto_topup_amount_cents
        wallet.low_balance_threshold_cents = req.low_balance_threshold_cents
        db.add(wallet)
        await db.commit()
        
    return {
        "checkout_id": checkout.get("id"),
        "status": checkout.get("status"),
        "next_action": checkout.get("next_action"),
        "billing_customer_id": new_cust_id or billing_customer_id,
    }

