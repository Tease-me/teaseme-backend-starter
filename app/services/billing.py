import subprocess
import tempfile
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from uuid import uuid4
from fastapi import HTTPException
from app.db.models import (
    AirwallexBillingCheckout,
    AirwallexPaymentIntent,
    CreditTransaction,
    CreditWallet,
    DailyUsage,
    Pricing,
    User,
    WalletTopup,
)
from app.services.airwallex import create_auto_topup_payment_intent, create_billing_checkout

async def charge_feature(db, *, user_id: int, feature: str, units: int, meta: dict | None = None):
    today = date.today()
    usage = await db.get(DailyUsage, (user_id, today)) or DailyUsage(
        user_id=user_id,
        date=today,
        text_count=0,
        voice_secs=0,
        live_secs=0,
    )

    price: Pricing = await db.scalar(select(Pricing).where(
        Pricing.feature == feature, Pricing.is_active.is_(True)
    ))
    if not price:
        raise HTTPException(500, "Pricing not configured")

    free_left = {
        "text":  max((price.free_allowance or 0) - (usage.text_count or 0), 0),
        "voice": max((price.free_allowance or 0) - (usage.voice_secs or 0), 0),
        "live_chat": max((price.free_allowance or 0) - (usage.live_secs or 0), 0),
    }[feature]

    billable = max(units - free_left, 0)
    cost = billable * price.price_cents

    # Debit wallet
    if cost:
        wallet = await db.get(CreditWallet, user_id) or CreditWallet(user_id=user_id)
        current_balance = wallet.balance_cents or 0
        user_obj = await db.get(User, user_id)

        if wallet.auto_topup_enabled:
            auto_amount = wallet.auto_topup_amount_cents or 0
            threshold = wallet.low_balance_threshold_cents
            post_balance_without_topup = current_balance - cost
            should_topup = threshold is not None and post_balance_without_topup < threshold
            if should_topup:
                if auto_amount <= 0:
                    raise HTTPException(402, "Auto top-up amount is not configured.")
                if not user_obj or not user_obj.billing_customer_id:
                    raise HTTPException(402, "Auto top-up requires a saved payment method.")
                topup_result = await _perform_auto_topup(
                    db,
                    user=user_obj,
                    wallet=wallet,
                    amount_cents=auto_amount,
                )
                if topup_result.get("requires_action"):
                    raise HTTPException(
                        status_code=402,
                        detail={
                            "error": "AUTO_TOPUP_ACTION_REQUIRED",
                            "message": "Auto top-up requires user action.",
                            **topup_result,
                        },
                    )
                wallet = await db.get(CreditWallet, user_id) or CreditWallet(user_id=user_id)
                current_balance = wallet.balance_cents or 0

        if current_balance < cost:
            raise HTTPException(402, "Insufficient credits")
        
        wallet.balance_cents = current_balance - cost
        db.add(wallet)

        # Trigger a low-balance notification when crossing below the configured threshold.
        new_balance = wallet.balance_cents
        notify_threshold = (
            wallet.low_balance_threshold_cents
            if wallet.low_balance_threshold_cents is not None
            else 1000
        )
        if current_balance >= notify_threshold and new_balance < notify_threshold:
            if user_obj and user_obj.email:
                try:
                    from app.api.notify_ws import notify_low_balance
                    await notify_low_balance(user_obj.email, new_balance)
                except Exception as e:
                    print(f"Error sending low balance notification: {e}")

    # Update usage counters (after any auto top-up side effects).
    if feature == "text":
        usage.text_count = (usage.text_count or 0) + units
    elif feature == "voice":
        usage.voice_secs = (usage.voice_secs or 0) + units
    else:
        usage.live_secs = (usage.live_secs or 0) + units
    db.add(usage)

    db.add(CreditTransaction(
        user_id=user_id,
        feature=feature,
        units=-units,
        amount_cents=-cost,
        meta=meta,
    ))
    await db.commit()
    return cost

async def topup_wallet(db, user_id: int, cents: int, source: str):
    """Add credits to user's wallet and log the transaction."""
    wallet = await db.get(CreditWallet, user_id) or CreditWallet(user_id=user_id)
    if wallet.balance_cents is None:
        wallet.balance_cents = 0
    wallet.balance_cents += cents
    db.add_all(
        [
            wallet,
            CreditTransaction(
                user_id=user_id,
                feature="topup",
                units=cents,
                amount_cents=cents,
                meta={"source": source},
            ),
        ]
    )
    await db.commit()
    return wallet.balance_cents


async def _perform_auto_topup(
    db: AsyncSession,
    *,
    user: User | None,
    wallet: CreditWallet,
    amount_cents: int,
    currency: str = "USD",
) -> dict:
    """
    Charge the user's saved payment method and credit their wallet.
    """
    if amount_cents <= 0:
        return {"topped_up": False, "topped_up_cents": 0}
    if not user or not user.billing_customer_id:
        raise HTTPException(402, "Auto top-up requires a saved payment method.")

    request_id = str(uuid4())
    merchant_order_id = f"wallet-topup-{uuid4()}"
    request_payload = {
        "request_id": request_id,
        "merchant_order_id": merchant_order_id,
        "customer_id": user.billing_customer_id,
        "amount": amount_cents,
        "currency": currency,
        "description": "Wallet auto top-up",
    }
    payment_intent_row = AirwallexPaymentIntent(
        user_id=user.id,
        request_id=request_id,
        merchant_order_id=merchant_order_id,
        amount_cents=amount_cents,
        currency=currency,
        status="REQUESTED",
        purpose="wallet_auto_topup",
        billing_customer_id=user.billing_customer_id,
        request_payload=request_payload,
    )
    wallet_topup_row = WalletTopup(
        user_id=user.id,
        amount_cents=amount_cents,
        currency=currency,
        source="auto",
        status="pending",
        airwallex_payment_intent_row_id=None,
    )
    db.add_all([payment_intent_row, wallet_topup_row])
    await db.flush()
    wallet_topup_row.airwallex_payment_intent_row_id = payment_intent_row.id
    payment_intent_row_id = payment_intent_row.id
    wallet_topup_row_id = wallet_topup_row.id
    await db.commit()

    payment = await create_auto_topup_payment_intent(
        customer_id=user.billing_customer_id,
        amount_cents=amount_cents,
        currency=currency,
        description="Wallet auto top-up",
        request_id=request_id,
        merchant_order_id=merchant_order_id,
    )
    payment_intent_row = await db.get(AirwallexPaymentIntent, payment_intent_row_id)
    wallet_topup_row = await db.get(WalletTopup, wallet_topup_row_id)
    status = (payment.get("status") or "").upper()
    if status in {"SUCCEEDED", "CAPTURE_SUCCEEDED", "CAPTURED", "SUCCESS"}:
        payment_intent_row.airwallex_payment_intent_id = payment.get("id")
        payment_intent_row.status = status
        payment_intent_row.response_payload = payment
        db.add(payment_intent_row)

        wallet_credit = await db.get(CreditWallet, user.id) or CreditWallet(user_id=user.id)
        if wallet_credit.balance_cents is None:
            wallet_credit.balance_cents = 0
        wallet_credit.balance_cents += amount_cents
        tx = CreditTransaction(
            user_id=user.id,
            feature="topup",
            units=amount_cents,
            amount_cents=amount_cents,
            meta={
                "source": "auto_topup",
                "wallet_topup_id": wallet_topup_row_id,
                "airwallex_payment_intent_id": payment.get("id"),
            },
        )
        db.add_all([wallet_credit, tx])
        await db.flush()

        wallet_topup_row.status = "succeeded"
        wallet_topup_row.credit_transaction_id = tx.id
        db.add(wallet_topup_row)
        await db.commit()
        return {
            "topped_up": True,
            "topped_up_cents": amount_cents,
            "payment_intent_id": payment.get("id"),
            "payment_intent_status": status,
            "wallet_topup_id": wallet_topup_row_id,
            "credit_transaction_id": tx.id,
        }

    requires_action = bool(payment.get("next_action")) or status in {
        "REQUIRES_CUSTOMER_ACTION",
        "REQUIRES_ACTION",
        "ACTION_REQUIRED",
    }
    if not requires_action:
        payment_intent_row.airwallex_payment_intent_id = payment.get("id")
        payment_intent_row.status = status or "FAILED"
        payment_intent_row.response_payload = payment
        wallet_topup_row.status = "failed"
        wallet_topup_row.error_message = f"status={status or 'unknown'}"
        db.add_all([payment_intent_row, wallet_topup_row])
        await db.commit()
        raise HTTPException(402, f"Auto top-up failed (status={status or 'unknown'}).")

    payment_intent_row.airwallex_payment_intent_id = payment.get("id")
    payment_intent_row.status = status or "REQUIRES_ACTION"
    payment_intent_row.response_payload = payment
    wallet_topup_row.status = "requires_action"
    db.add_all([payment_intent_row, wallet_topup_row])
    await db.commit()

    return {
        "topped_up": False,
        "requires_action": True,
        "payment_intent_id": payment.get("id"),
        "payment_intent_status": status or "unknown",
        "wallet_topup_id": wallet_topup_row_id,
    }


async def auto_topup_if_below_threshold(
    db: AsyncSession,
    *,
    user_id: int,
    currency: str = "USD",
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict:
    """
    Scheduled/explicit check: if the user's wallet balance is below the configured threshold,
    charge the saved payment method and credit the wallet by the configured auto top-up amount.
    """
    wallet = await db.get(CreditWallet, user_id)
    if not wallet or not wallet.auto_topup_enabled:
        balance = wallet.balance_cents if wallet and wallet.balance_cents is not None else 0
        return {"topped_up": False, "balance_cents": balance, "reason": "disabled"}

    balance = wallet.balance_cents if wallet.balance_cents is not None else 0
    threshold = wallet.low_balance_threshold_cents
    auto_amount = wallet.auto_topup_amount_cents or 0

    if threshold is None or threshold <= 0 or auto_amount <= 0:
        raise HTTPException(400, "Auto top-up is not configured.")

    if balance >= threshold:
        return {
            "topped_up": False,
            "balance_cents": balance,
            "threshold_cents": threshold,
            "reason": "above_threshold",
        }

    user = await db.get(User, user_id)
    topup_result = await _perform_auto_topup(
        db,
        user=user,
        wallet=wallet,
        amount_cents=auto_amount,
        currency=currency,
    )
    if topup_result.get("requires_action"):
        wallet_topup_id = topup_result.get("wallet_topup_id")
        if not success_url or not cancel_url:
            return {
                "topped_up": False,
                "requires_action": True,
                "reason": "customer_action_required",
                "action": "SETUP_PAYMENT_METHOD",
                "wallet_topup_id": wallet_topup_id,
            }
        if not user or not user.billing_customer_id:
            raise HTTPException(402, "Auto top-up requires a saved payment method.")
        checkout_payload = {
            "request_id": str(uuid4()),
            "mode": "SETUP",
            "currency": currency,
            "success_url": success_url,
            "back_url": cancel_url,
            "billing_customer_id": user.billing_customer_id,
        }
        checkout = await create_billing_checkout(checkout_payload)
        checkout_row = AirwallexBillingCheckout(
            user_id=user.id,
            request_id=checkout_payload["request_id"],
            airwallex_checkout_id=checkout.get("id"),
            mode="SETUP",
            status=checkout.get("status"),
            currency=currency,
            billing_customer_id=user.billing_customer_id,
            purpose="auto_topup_setup_fallback",
            success_url=success_url,
            back_url=cancel_url,
            request_payload=checkout_payload,
            response_payload=checkout,
        )
        db.add(checkout_row)
        await db.flush()
        if wallet_topup_id:
            linked_wallet_topup = await db.get(WalletTopup, wallet_topup_id)
            if linked_wallet_topup:
                linked_wallet_topup.airwallex_billing_checkout_row_id = checkout_row.id
                db.add(linked_wallet_topup)
        await db.commit()
        return {
            "topped_up": False,
            "requires_action": True,
            "reason": "customer_action_required",
            "action": "SETUP_PAYMENT_METHOD",
            "checkout_id": checkout.get("id"),
            "checkout_status": checkout.get("status"),
            "next_action": checkout.get("next_action"),
            "billing_customer_id": user.billing_customer_id,
            "wallet_topup_id": wallet_topup_id,
        }

    refreshed = await db.get(CreditWallet, user_id)
    new_balance = refreshed.balance_cents if refreshed and refreshed.balance_cents is not None else balance
    return {
        "topped_up": True,
        "topped_up_cents": auto_amount,
        "balance_cents": new_balance,
        "threshold_cents": threshold,
    }

def get_audio_duration_ffmpeg(file_bytes: bytes) -> float:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        duration = float(result.stdout.decode().strip())
        return duration
    except Exception as e:
        print(f"ffmpeg duration error: {e}")
        return 10.0  # fallback
    

import subprocess, tempfile, math

MIME_TO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/wav":  ".wav",
    "audio/x-wav": ".wav",
    "audio/mp3":  ".mp3",
    "audio/mpeg": ".mp3",
    "audio/ogg":  ".ogg",
    "audio/x-m4a": ".m4a",
}

def _duration_via_ffprobe(data: bytes, suffix: str) -> float:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                tmp_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = result.stdout.decode().strip()
        try:
            duration = float(output)
        except Exception:
            print(f"[WARN] ffprobe failed: {output!r}")
            duration = 0.0
        return duration
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

def get_duration_seconds(file_bytes: bytes, mime: str | None = None) -> int:
    """
    Returns duration in whole seconds (>=1), fallback 10s if ffprobe fails.
    """
    suffix = MIME_TO_SUFFIX.get(mime or "", ".wav")
    duration = _duration_via_ffprobe(file_bytes, suffix)
    if duration <= 0:
        duration = 10.0
    return max(1, math.ceil(duration))

# map feature -> which counter to read on DailyUsage
_USAGE_FIELD = {
    "text": "text_count",
    "voice": "voice_secs",
    "live_chat": "live_secs",
}

async def can_afford(
    db: AsyncSession,
    *,
    user_id: int,
    feature: str,
    units: int,
) -> tuple[bool, int, int]:
    """
    Returns (ok, cost_cents, free_left)
      - ok = True if user can afford 'units'
      - cost_cents = how much would be charged (after free allowance)
      - free_left = remaining free allowance for that feature today
    No DB mutations.
    """
    # pricing
    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        # no pricing? don't block
        return True, 0, 0

    # usage today
    today = date.today()
    usage: DailyUsage | None = await db.get(DailyUsage, (user_id, today))
    # base counters
    text_used = getattr(usage, "text_count", 0) if usage else 0
    voice_used = getattr(usage, "voice_secs", 0) if usage else 0
    live_used  = getattr(usage, "live_secs",  0) if usage else 0

    if feature == "text":
        used = text_used
    elif feature == "voice":
        used = voice_used
    else:
        used = live_used

    free_left = max((price.free_allowance or 0) - (used or 0), 0)
    billable = max(units - free_left, 0)
    cost_cents = billable * (price.price_cents or 0)

    # wallet
    wallet = await db.get(CreditWallet, user_id)
    balance = wallet.balance_cents if wallet and wallet.balance_cents is not None else 0

    if cost_cents == 0:
        return True, 0, free_left

    if balance >= cost_cents:
        return True, cost_cents, free_left

    # If auto top-up is enabled, estimate whether a single top-up would cover this charge.
    if wallet and wallet.auto_topup_enabled:
        auto_amount = wallet.auto_topup_amount_cents or 0
        threshold = wallet.low_balance_threshold_cents
        if auto_amount > 0 and threshold is not None:
            post_balance_without_topup = balance - cost_cents
            should_topup = post_balance_without_topup < threshold
            if should_topup:
                user = await db.get(User, user_id)
                if user and user.billing_customer_id and (balance + auto_amount) >= cost_cents:
                    return True, cost_cents, free_left

    return False, cost_cents, free_left

async def get_remaining_units(db: AsyncSession, user_id: int, feature: str) -> int:
    """
    Compute how many units (messages, seconds, etc.) the user can still afford
    = free_allowance_left + wallet_balance / unit_price
    """
    from sqlalchemy import select
    from datetime import date
    from app.db.models import Pricing, DailyUsage, CreditWallet

    price: Pricing | None = await db.scalar(
        select(Pricing).where(Pricing.feature == feature, Pricing.is_active.is_(True))
    )
    if not price:
        return 0

    unit_price_cents = price.price_cents
    free_allowance = price.free_allowance or 0

    # usage today
    today = date.today()
    usage: DailyUsage | None = await db.get(DailyUsage, (user_id, today))
    used = getattr(usage, f"{feature}_secs", 0) if usage else 0
    free_left = max(free_allowance - (used or 0), 0)

    # wallet
    wallet: CreditWallet | None = await db.get(CreditWallet, user_id)
    balance_cents = wallet.balance_cents if wallet else 0
    paid = balance_cents // unit_price_cents if unit_price_cents > 0 else 0

    return int(free_left + paid)
