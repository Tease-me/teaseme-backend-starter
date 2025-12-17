from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CreditWallet, WalletTopup
from app.db.session import get_db
from app.schemas.billing import AutoTopupCheckRequest, BillingCheckoutRequest, CardTopUpRequest, TopUpCheckoutRequest, TopUpRequest
# Note: create_customer and create_payment_link are imported inline in functions
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
    """
    Create a checkout session for wallet top-up.
    Uses Payment Link API for consistent cus_ customer IDs.
    """
    # Ensure we have a PA customer ID (cus_), not a billing customer ID (bcus_)
    from app.services.airwallex import create_customer, create_payment_link
    
    billing_customer_id = getattr(user, "billing_customer_id", None)
    if not billing_customer_id or billing_customer_id.startswith("bcus_"):
        cust = await create_customer(
            email=user.email,
            name=user.full_name or user.email,
            reference_id=f"user_{user.id}",
        )
        billing_customer_id = cust.get("id")
        user.billing_customer_id = billing_customer_id
        db.add(user)
        await db.flush()

    request_id = str(uuid4())
    
    # Create WalletTopup record first
    wallet_topup = WalletTopup(
        user_id=user.id,
        amount_cents=req.amount_cents,
        currency=req.currency,
        source="manual",
        status="pending",
        ext_request_id=request_id,
        billing_customer_id=billing_customer_id,
        meta={"kind": "manual_wallet_topup"},
    )
    db.add(wallet_topup)
    await db.flush()

    # Create Payment Link payload
    payload = {
        "request_id": request_id,
        "amount": req.amount_cents,
        "currency": req.currency,
        "title": "Wallet Top-up",
        "description": f"Add ${req.amount_cents / 100:.2f} to your wallet",
        "reusable": False,
        "customer_id": billing_customer_id,
        "payment_intent_data": {
            "setup_future_usage": "off_session",
            "capture_method": "automatic",
            "metadata": {"request_id": request_id, "wallet_topup_id": str(wallet_topup.id)},
        },
        "success_url": str(req.success_url),
        "return_url": str(req.success_url),
    }

    checkout = await create_payment_link(payload)
    
    # Update WalletTopup with response
    wallet_topup.ext_transaction_id = checkout.get("id")
    wallet_topup.request_payload = payload
    wallet_topup.response_payload = checkout
    if checkout.get("status") in ("SUCCEEDED", "PAID"):
        wallet_topup.status = "succeeded"

    db.add(wallet_topup)
    await db.commit()

    return {
        "wallet_topup_id": wallet_topup.id,
        "transaction_id": checkout.get("id"),  # For UI display
        "checkout_url": checkout.get("url"),
        "status": checkout.get("status"),
        "amount_cents": req.amount_cents,
        "currency": req.currency,
        "billing_customer_id": billing_customer_id,
    }


@router.post("/topup/card", status_code=201)
async def topup_with_card(
    req: CardTopUpRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Process a card payment from custom UI.
    Step 1: Amount is in req.amount_cents
    Step 2: Card token is in req.payment_method_id (from Airwallex SDK)
    Step 3: Auto-topup settings in req
    """
    from app.services.airwallex import (
        create_customer, 
        create_payment_intent, 
        confirm_payment_intent
    )
    from app.db.models import CreditTransaction
    
    # Ensure customer ID exists
    billing_customer_id = getattr(user, "billing_customer_id", None)
    if not billing_customer_id or billing_customer_id.startswith("bcus_"):
        cust = await create_customer(
            email=user.email,
            name=user.full_name or user.email,
            reference_id=f"user_{user.id}",
        )
        billing_customer_id = cust.get("id")
        user.billing_customer_id = billing_customer_id
        db.add(user)
        await db.flush()

    request_id = str(uuid4())
    
    # Create WalletTopup record
    wallet_topup = WalletTopup(
        user_id=user.id,
        amount_cents=req.amount_cents,
        currency=req.currency,
        source="card_ui",
        status="pending",
        ext_request_id=request_id,
        billing_customer_id=billing_customer_id,
        meta={"kind": "card_ui_topup", "save_card": req.save_card},
    )
    db.add(wallet_topup)
    await db.flush()

    # Create Payment Intent
    payment_intent = await create_payment_intent(
        customer_id=billing_customer_id,
        amount_cents=req.amount_cents,
        currency=req.currency,
        save_payment_method=req.save_card,
        request_id=request_id,
        metadata={"wallet_topup_id": str(wallet_topup.id)},
    )
    
    payment_intent_id = payment_intent.get("id")
    wallet_topup.ext_transaction_id = payment_intent_id
    wallet_topup.response_payload = payment_intent
    db.add(wallet_topup)
    
    # If payment method provided, confirm immediately
    result_status = "pending"
    if req.payment_method_id:
        try:
            confirm_result = await confirm_payment_intent(
                payment_intent_id=payment_intent_id,
                payment_method_id=req.payment_method_id,
                customer_id=billing_customer_id,
                save_payment_method=req.save_card,
            )
            result_status = (confirm_result.get("status") or "").upper()
            wallet_topup.response_payload = confirm_result
            
            # Check if payment succeeded immediately
            if result_status in {"SUCCEEDED", "CAPTURED", "SUCCESS"}:
                wallet_topup.status = "succeeded"
                # Credit wallet immediately
                wallet = await db.get(CreditWallet, user.id) or CreditWallet(user_id=user.id)
                wallet.balance_cents = (wallet.balance_cents or 0) + req.amount_cents
                tx = CreditTransaction(
                    user_id=user.id,
                    feature="topup",
                    units=req.amount_cents,
                    amount_cents=req.amount_cents,
                    meta={"source": "card_ui_topup", "wallet_topup_id": wallet_topup.id},
                )
                db.add_all([wallet, tx])
                await db.flush()
                wallet_topup.credit_transaction_id = tx.id
            elif result_status in {"REQUIRES_CAPTURE", "REQUIRES_CUSTOMER_ACTION"}:
                wallet_topup.status = "requires_action"
            else:
                wallet_topup.status = "failed"
                wallet_topup.error_message = f"status={result_status}"
                
            db.add(wallet_topup)
        except Exception as e:
            wallet_topup.status = "failed"
            wallet_topup.error_message = str(e)
            db.add(wallet_topup)
            await db.commit()
            raise HTTPException(400, f"Payment failed: {e}")

    # Update wallet settings (Step 3)
    wallet = await db.get(CreditWallet, user.id) or CreditWallet(user_id=user.id)
    if req.low_balance_threshold_cents is not None:
        wallet.low_balance_threshold_cents = req.low_balance_threshold_cents
    if req.auto_topup_enabled is not None:
        wallet.auto_topup_enabled = req.auto_topup_enabled
    if req.auto_topup_amount_cents is not None:
        wallet.auto_topup_amount_cents = req.auto_topup_amount_cents
    # Note: notify_low_balance would need a new column if not exists
    db.add(wallet)
    
    await db.commit()
    
    # Refresh to get latest balance
    wallet = await db.get(CreditWallet, user.id)
    
    return {
        "transaction_id": payment_intent_id,
        "wallet_topup_id": wallet_topup.id,
        "status": wallet_topup.status,
        "amount_cents": req.amount_cents,
        "currency": req.currency,
        "balance_cents": wallet.balance_cents if wallet else 0,
        "billing_customer_id": billing_customer_id,
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
        "wallet_topup_id": wallet_topup.id,
        "transaction_id": payment_link.get("id"),  # For UI display
        "checkout_url": payment_link.get("url"),
        "status": payment_link.get("status"),
        "amount_cents": amount_cents,
        "currency": req.currency,
        "billing_customer_id": billing_customer_id,
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
