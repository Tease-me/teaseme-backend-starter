from uuid import uuid4
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CreditWallet
from app.db.session import get_db
from app.schemas.billing import AutoTopupCheckRequest, BillingCheckoutRequest, TopUpRequest
from app.services.airwallex import create_billing_checkout
from app.services.billing import auto_topup_if_below_threshold, topup_wallet
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
    mode = req.mode.upper()
    payload = {
        "request_id": str(uuid4()),
        "mode": mode,
        "currency": req.currency,
        "success_url": req.success_url,
        "back_url": req.cancel_url,
    }
    if mode == "PAYMENT":
        line_item = None
        if req.price_id:
            line_item = {"price_id": req.price_id, "quantity": req.quantity}
        elif req.amount_cents:
            line_item = {
                "amount": req.amount_cents,
                "currency": req.currency,
                "quantity": req.quantity,
            }
        if line_item:
            payload["line_items"] = [line_item]

    billing_customer_id = req.billing_customer_id or getattr(user, "billing_customer_id", None)
    if billing_customer_id:
        payload["billing_customer_id"] = billing_customer_id
    else:
        payload["customer_data"] = {
            "email": user.email,
            "name": user.full_name or user.email,
            "type": "INDIVIDUAL",
        }
    
    checkout = await create_billing_checkout(payload)
    new_cust_id = checkout.get("billing_customer_id") or billing_customer_id
    if new_cust_id and not getattr(user, "billing_customer_id", None):
        user.billing_customer_id = new_cust_id
        db.add(user)
        await db.commit()
    if (
        req.auto_topup_enabled is not None
        or req.auto_topup_amount_cents is not None
        or req.low_balance_threshold_cents is not None
    ):
        wallet = await db.get(CreditWallet, user.id) or CreditWallet(user_id=user.id)
        if req.auto_topup_enabled is not None:
            wallet.auto_topup_enabled = req.auto_topup_enabled
        if req.auto_topup_amount_cents is not None:
            wallet.auto_topup_amount_cents = req.auto_topup_amount_cents
        if req.low_balance_threshold_cents is not None:
            wallet.low_balance_threshold_cents = req.low_balance_threshold_cents
        db.add(wallet)
        await db.commit()
        
    return {
        "checkout_id": checkout.get("id"),
        "status": checkout.get("status"),
        "next_action": checkout.get("next_action"),
        "billing_customer_id": new_cust_id or billing_customer_id,
    }


@router.post("/auto-topup/check")
async def auto_topup_check(
    req: AutoTopupCheckRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await auto_topup_if_below_threshold(
        db,
        user_id=user.id,
        currency=req.currency if req else "USD",
        success_url=str(req.success_url) if req and req.success_url else None,
        cancel_url=str(req.cancel_url) if req and req.cancel_url else None,
    )
    return {"ok": True, **result}
