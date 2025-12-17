from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CreditWallet, WalletTopup
from app.db.session import get_db
from app.schemas.billing import AutoTopupCheckRequest, BillingCheckoutRequest, TopUpCheckoutRequest, TopUpRequest
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

@router.post("/topup/checkout", status_code=201)
async def topup_checkout(
    req: TopUpCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    wallet_topup = WalletTopup(
        user_id=user.id,
        amount_cents=req.amount_cents,
        currency=req.currency,
        source="manual",
        status="pending",
        meta={"kind": "manual_wallet_topup"},
    )
    db.add(wallet_topup)
    await db.flush()

    line_item = {
        "amount": req.amount_cents,
        "currency": req.currency,
        "quantity": 1,
    }
    payload = {
        "request_id": str(uuid4()),
        "mode": "PAYMENT",
        "currency": req.currency,
        "line_items": [line_item],
        "invoice_data": {"line_items": [line_item]},
        "success_url": str(req.success_url),
        "back_url": str(req.cancel_url),
    }

    billing_customer_id = getattr(user, "billing_customer_id", None)
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

    # Consolidate into WalletTopup - no more AirwallexBillingCheckout
    wallet_topup.ext_transaction_id = checkout.get("id")
    wallet_topup.ext_request_id = payload["request_id"]
    wallet_topup.billing_customer_id = new_cust_id
    wallet_topup.request_payload = payload
    wallet_topup.response_payload = checkout
    # Update status immediately if we have it, though usually it's pending until webhook
    if checkout.get("status") in ("SUCCEEDED", "PAID"):
        wallet_topup.status = "succeeded"

    db.add(wallet_topup)
    await db.commit()

    return {
        "wallet_topup_id": wallet_topup.id,
        "checkout_id": checkout.get("id"),
        "status": checkout.get("status"),
        "next_action": checkout.get("next_action"),
        "billing_customer_id": new_cust_id,
    }


@router.get("/topup/{wallet_topup_id}")
async def get_topup(
    wallet_topup_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    topup = await db.scalar(
        select(WalletTopup).where(WalletTopup.id == wallet_topup_id, WalletTopup.user_id == user.id)
    )
    if not topup:
        raise HTTPException(status_code=404, detail="Top-up not found")
    return {
        "ok": True,
        "wallet_topup_id": topup.id,
        "status": topup.status,
        "amount_cents": topup.amount_cents,
        "currency": topup.currency,
        "ext_transaction_id": topup.ext_transaction_id,
        "credit_transaction_id": topup.credit_transaction_id,
        "error_message": topup.error_message,
    }


@router.post("/billing-checkout", status_code=201)
async def billing_checkout(
    req: BillingCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    mode = req.mode.upper()
    amount_cents = req.amount_cents or 0
    
    # Validation: Payment Link requires a positive amount.
    # If SETUP mode and no amount provided, default to $10.00 (1000 cents) to allow saving card.
    if mode == "SETUP" and amount_cents == 0:
        amount_cents = 1000 # Default $10 setup
    
    if amount_cents <= 0:
        raise HTTPException(400, "Amount must be positive.")

    billing_customer_id = req.billing_customer_id or getattr(user, "billing_customer_id", None)
    
    # Requirement: Payment Link needs a customer_id (cus_). 
    # If missing, create one (PA Customer).
    if not billing_customer_id:
        from app.services.airwallex import create_customer
        cust = await create_customer(
            email=user.email,
            name=user.full_name or user.email,
        )
        billing_customer_id = cust.get("id")
        user.billing_customer_id = billing_customer_id
        db.add(user)
        # We don't commit yet, wait for wallet topup

    request_id = str(uuid4())
    payload = {
        "request_id": request_id,
        "amount": amount_cents,
        "currency": req.currency,
        "title": "Wallet Top-up",
        "description": "Wallet Top-up",
        "reusable": False,
        "customer_id": billing_customer_id,
        "payment_intent_data": {
            "setup_future_usage": "off_session",
            "capture_method": "automatic",
            "metadata": {"request_id": request_id},
        },
        "success_url": str(req.success_url),
        # return_url is used for redirect after payment
        "return_url": str(req.success_url), 
    }
    
    from app.services.airwallex import create_payment_link
    payment_link = await create_payment_link(payload)
    
    # Consolidated logic: Create a WalletTopup record
    wallet_topup = WalletTopup(
        user_id=user.id,
        amount_cents=amount_cents,
        currency=req.currency,
        source="manual_checkout",
        status=payment_link.get("status") or "pending",
        # Store Payment Link ID? Or do we get intent ID?
        # Typically webhook comes with payment_intent_id.
        # Payment Link response might have intent_id?
        # We'll store Link ID for now, and handle lookup in webhook via metadata or loose search?
        # Actually, best to store ext_request_id and look up by that.
        ext_transaction_id=payment_link.get("id"), 
        ext_request_id=payload["request_id"],
        billing_customer_id=billing_customer_id,
        request_payload=payload,
        response_payload=payment_link,
        meta={"mode": mode, "link_type": "payment_link"}
    )
    db.add(wallet_topup)
    await db.commit()
    
    # Check for User-level auto-topup settings update
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
        "checkout_id": payment_link.get("id"),
        "checkout_url": payment_link.get("url"), # This is likely 'url' or 'short_url'
        "status": payment_link.get("status"),
        "next_action": None, 
        "billing_customer_id": billing_customer_id,
        "wallet_topup_id": wallet_topup.id
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
