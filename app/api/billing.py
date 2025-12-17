from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import AirwallexBillingCheckout, CreditWallet, WalletTopup
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

    payload = {
        "request_id": str(uuid4()),
        "mode": "PAYMENT",
        "currency": req.currency,
        "line_items": [
            {
                "amount": req.amount_cents,
                "currency": req.currency,
                "quantity": 1,
            }
        ],
        "success_url": req.success_url,
        "back_url": req.cancel_url,
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

    checkout_row = AirwallexBillingCheckout(
        user_id=user.id,
        request_id=payload["request_id"],
        airwallex_checkout_id=checkout.get("id"),
        mode="PAYMENT",
        status=checkout.get("status"),
        currency=req.currency,
        billing_customer_id=new_cust_id,
        purpose="wallet_topup_manual",
        success_url=str(req.success_url),
        back_url=str(req.cancel_url),
        request_payload=payload,
        response_payload=checkout,
    )
    db.add(checkout_row)
    await db.flush()

    wallet_topup.airwallex_billing_checkout_row_id = checkout_row.id
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

    db.add(
        AirwallexBillingCheckout(
            user_id=user.id,
            request_id=payload["request_id"],
            airwallex_checkout_id=checkout.get("id"),
            mode=mode,
            status=checkout.get("status"),
            currency=req.currency,
            billing_customer_id=new_cust_id,
            purpose="billing_checkout",
            success_url=str(req.success_url),
            back_url=str(req.cancel_url),
            request_payload=payload,
            response_payload=checkout,
        )
    )
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
