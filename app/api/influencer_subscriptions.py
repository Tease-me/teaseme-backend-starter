from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import uuid

from app.db.session import get_db
from app.utils.deps import get_current_user
from app.db.models import (
    InfluencerSubscription,
    InfluencerSubscriptionPayment,
    InfluencerSubscriptionPlan,
    InfluencerSubscriptionAddonPurchase,
    InfluencerWallet,
    User
)
from app.services.influencer_subscriptions import require_active_subscription
from app.utils.rate_limiter import rate_limit
from app.utils.idempotency import idempotent
from app.utils.concurrency import advisory_lock
from app.core.config import settings


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# Constants
SUBSCRIPTION_NOT_FOUND = "Subscription not found"


@router.post("/start")
@rate_limit(max_requests=settings.RATE_LIMIT_BILLING_MAX, window_seconds=settings.RATE_LIMIT_BILLING_WINDOW, key_prefix="sub:start")
@idempotent(ttl=settings.IDEMPOTENCY_TTL, key_prefix="sub-start")
async def start_subscription(
    request: Request,
    influencer_id: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Start a subscription for an influencer.
    
    Args:
        influencer_id: Influencer ID to subscribe to
        plan_id: Subscription plan ID (Basic=1, Plus=2, Premium=3)
    """
    # First, check if influencer exists
    from app.db.models import Influencer
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "influencer_not_found",
                "message": f"Influencer '{influencer_id}' not found.",
                "hint": "Please check the influencer ID and try again."
            }
        )
    
    # Get plan details (required)
    plan = await db.get(InfluencerSubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "plan_not_found",
                "message": f"Subscription plan with ID {plan_id} not found.",
            }
        )
    
    # Check if this is an add-on (one-time purchase)
    if plan.interval == "addon" or plan.plan_type == "addon":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_plan_type",
                "message": f"'{plan.plan_name}' is an add-on pack, not a subscription.",
                "hint": "Use POST /subscriptions/purchase-addon to purchase add-on packs.",
                "addon_plan": {
                    "id": plan.id,
                    "name": plan.plan_name,
                    "price": f"${plan.price_cents/100:.2f}",
                    "credits": f"${plan.features.get('credits_granted', 0)/100:.2f}" if plan.features else "N/A",
                }
            }
        )
    
    if not plan.is_active:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "plan_inactive",
                "message": f"Plan '{plan.plan_name}' is not currently available.",
            }
        )
    
    # Get price from plan
    price_cents = plan.price_cents
    
    # All subscriptions are for 18+ content
    is_18 = True
    
    res = await db.execute(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )
    sub = res.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    # If subscription already exists and is active, return error
    if sub and sub.status == "active":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "subscription_already_exists",
                "message": "You already have an active subscription for this influencer.",
                "subscription_id": sub.id,
                "current_plan": plan.plan_name if (plan and sub.plan_id == plan_id) else None,
                "hint": "Use /subscriptions/{influencer_id}/change-plan to upgrade or downgrade.",
            }
        )
    
    # If subscription exists but is cancelled/expired, reactivate it
    if sub:
        sub.status = "pending"  # Waiting for payment
        sub.price_cents = price_cents
        sub.plan_id = plan_id  # Update plan
        sub.is_18_selected = is_18
        sub.started_at = now
        sub.current_period_start = None  # Set after payment
        sub.current_period_end = None    # Set after payment
        sub.next_payment_at = None       # Set after payment
        await db.commit()
        return {
            "status": "pending",
            "message": "Subscription reactivated. Waiting for payment.",
            "subscription_id": sub.id,
            "plan": plan.plan_name if plan else None,
            "price": f"${price_cents/100:.0f}/month",
            "is_18": is_18,
        }

    sub = InfluencerSubscription(
        user_id=user.id,
        influencer_id=influencer_id,
        plan_id=plan_id,
        price_cents=price_cents,
        is_18_selected=is_18,
        status="pending",  # Waiting for payment
        started_at=now,
        current_period_start=None,  # Set after payment
        current_period_end=None,    # Set after payment
        next_payment_at=None,       # Set after payment
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "status": "pending",
        "message": "Subscription created. Waiting for payment.",
        "subscription_id": sub.id,
        "plan": plan.plan_name if plan else None,
        "price": f"${price_cents/100:.0f}/month",
        "is_18": is_18,
    }
    # Use advisory lock to prevent race conditions on subscription state
    async with advisory_lock(f"subscription:{user.id}:{influencer_id}", timeout=settings.LOCK_TIMEOUT):
        try:
            res = await db.execute(
                select(InfluencerSubscription).where(
                    InfluencerSubscription.user_id == user.id,
                    InfluencerSubscription.influencer_id == influencer_id,
                )
            )
            sub = res.scalar_one_or_none()

            now = datetime.now(timezone.utc)
            next_month = now + timedelta(days=30)

            if sub:
                sub.status = "active"
                sub.price_cents = price_cents
                sub.started_at = now
                sub.current_period_start = now
                sub.current_period_end = next_month
                sub.next_payment_at = next_month
                await db.commit()
                return {"status": "reactivated", "subscription_id": sub.id}

            sub = InfluencerSubscription(
                user_id=user.id,
                influencer_id=influencer_id,
                price_cents=price_cents,
                started_at=now,
                current_period_start=now,
                current_period_end=next_month,
                next_payment_at=next_month,
            )
            db.add(sub)
            await db.commit()
            await db.refresh(sub)

            return {"status": "created", "subscription_id": sub.id}
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            log.exception("Failed to start subscription for user %s: %s", user.id, e)
            raise HTTPException(status_code=500, detail="Failed to start subscription")

@router.post("/paypal/capture")
@rate_limit(max_requests=settings.RATE_LIMIT_BILLING_MAX, window_seconds=settings.RATE_LIMIT_BILLING_WINDOW, key_prefix="sub:paypal-capture")
async def paypal_capture_subscription(
    request: Request,
    subscription_id: int,
    order_id: str,
    amount_cents: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    sub = await db.get(InfluencerSubscription, subscription_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, SUBSCRIPTION_NOT_FOUND)

    existing_payment = await db.scalar(
        select(InfluencerSubscriptionPayment).where(
            InfluencerSubscriptionPayment.provider == "paypal",
            InfluencerSubscriptionPayment.provider_event_id == order_id,
        )
    )
    if existing_payment:
        return {"status": "already recorded"}

    now = datetime.now(timezone.utc)

    # Check if this is the first payment (subscription was pending)
    is_first_payment = sub.status == "pending" or sub.current_period_end is None

    if is_first_payment:
        # First payment - activate subscription
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=30)
        sub.next_payment_at = now + timedelta(days=30)
    else:
        # Renewal payment - extend subscription
        base = sub.current_period_end or now
        next_period = base + timedelta(days=30)
        sub.current_period_start = sub.current_period_end or now
        sub.current_period_end = next_period
        sub.next_payment_at = next_period

    sub.last_payment_at = now
    sub.status = "active"  # Activate subscription after payment

    payment = InfluencerSubscriptionPayment(
        subscription_id=sub.id,
        user_id=user.id,
        influencer_id=sub.influencer_id,
        amount_cents=amount_cents,
        status="succeeded",
        provider="paypal",
        provider_event_id=order_id,
        provider_payload=payload,
        occurred_at=now,
    )
    db.add(payment)

    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == sub.influencer_id,
            InfluencerWallet.is_18.is_(True),
        )
    )

    if not wallet:
        wallet = InfluencerWallet(
            user_id=user.id,
            influencer_id=sub.influencer_id,
            balance_cents=0,
            is_18=True,
        )
        db.add(wallet)
        await db.flush()

    # Add credits to balance
    wallet.balance_cents = (wallet.balance_cents or 0) + int(amount_cents)
    db.add(wallet)

    db.add(sub)
    await db.commit()

    return {
        "status": "payment recorded",
        "subscription_status": sub.status,  # "active"
        "is_first_payment": is_first_payment,
        "subscription_id": sub.id,
        "influencer_id": sub.influencer_id,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "next_payment_at": sub.next_payment_at.isoformat() if sub.next_payment_at else None,
        "wallet_balance_cents": wallet.balance_cents,
        "credits_added": amount_cents,
    }

def _now():
    return datetime.now(timezone.utc)

@router.post("/expire")
async def expire_subscriptions(db: AsyncSession = Depends(get_db)):
    """
    Marks subscriptions as expired if current_period_end is in the past.
    Call this from cron (or manually).
    """
    now = _now()

    await db.execute(
        update(InfluencerSubscription)
        .where(
            InfluencerSubscription.status == "active",
            InfluencerSubscription.current_period_end.isnot(None),
            InfluencerSubscription.current_period_end < now,
        )
        .values(status="expired")
    )
    await db.commit()
    return {"ok": True}


class CancelSubscriptionBody(BaseModel):
    influencer_id: str
    reason: str | None = None

@router.post("/cancel")
async def cancel_subscription(
    body: CancelSubscriptionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)

    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == body.influencer_id,
        )
    )

    if not sub:
        raise HTTPException(status_code=404, detail=SUBSCRIPTION_NOT_FOUND)

    if sub.status in ("cancelled", "expired"):
        return {
            "ok": True,
            "status": sub.status,
            "message": "Subscription already cancelled",
        }

    sub.status = "cancelled"
    sub.canceled_at = now
    sub.cancel_reason = body.reason

    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "ok": True,
        "user_id": user.id,
        "influencer_id": sub.influencer_id,
        "status": sub.status,
        "canceled_at": sub.canceled_at.isoformat(),
        "current_period_end": sub.current_period_end.isoformat()
        if sub.current_period_end
        else None,
    }

class Set18Req(BaseModel):
    is_18_selected: bool
    
@router.post("/{influencer_id}/18")
async def set_18_mode(
    influencer_id: str,
    req: Set18Req,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    sub = await require_active_subscription(
        db,
        user_id=user.id,
        influencer_id=influencer_id,
    )

    sub.is_18_selected = bool(req.is_18_selected)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "ok": True,
        "influencer_id": influencer_id,
        "is_18_selected": sub.is_18_selected,
    }

# ========================================
# SUBSCRIPTION PLANS
# ========================================

@router.get("/plans")
async def get_subscription_plans(db: AsyncSession = Depends(get_db)):
    """
    Get all available subscription plans and add-ons.
    Returns: Recurring plans and one-time add-on packs separately.
    """
    result = await db.execute(
        select(InfluencerSubscriptionPlan).where(
            InfluencerSubscriptionPlan.is_active.is_(True)
        ).order_by(InfluencerSubscriptionPlan.display_order)
    )
    all_plans = result.scalars().all()
    
    # Separate recurring plans from add-ons
    recurring_plans = [p for p in all_plans if p.interval == "monthly"]
    addon_packs = [p for p in all_plans if p.interval == "addon"]
    
    return {
        "recurring": [
            {
                "id": p.id,
                "name": p.plan_name,
                "price_cents": p.price_cents,
                "price_display": f"${p.price_cents/100:.0f}/month",
                "currency": p.currency,
                "description": p.description,
                "features": p.features,
                "is_featured": p.is_featured,
            }
            for p in recurring_plans
        ],
        "addons": [
            {
                "id": p.id,
                "name": p.plan_name,
                "price_cents": p.price_cents,
                "price_display": f"${p.price_cents/100:.0f}",
                "credits_granted": p.features.get("credits_granted", 0),
                "minutes_equivalent": p.features.get("total_minutes", 0),
                "currency": p.currency,
                "description": p.description,
                "is_featured": p.is_featured,
            }
            for p in addon_packs
        ]
    }


@router.get("/{influencer_id}")
async def get_subscription_for_influencer(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )

    if not sub:
        return {
            "has_subscription": False,
            "is_18_selected": False,
        }

    return {
        "has_subscription": True,
        "status": sub.status,
        "current_period_end": sub.current_period_end,
        "is_18_selected": sub.is_18_selected,
    }


class ChangePlanRequest(BaseModel):
    new_plan_id: int


@router.post("/{influencer_id}/change-plan")
async def change_subscription_plan(
    influencer_id: str,
    req: ChangePlanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Change subscription plan (upgrade or downgrade).
    The new plan will apply at the next billing period.
    """
    # Get current subscription
    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )
    
    if not sub:
        raise HTTPException(status_code=404, detail=SUBSCRIPTION_NOT_FOUND)
    
    if sub.status not in ("active", "paused"):
        raise HTTPException(
            status_code=400,
            detail="Cannot change plan for cancelled/expired subscription"
        )
    
    # Get new plan
    new_plan = await db.get(InfluencerSubscriptionPlan, req.new_plan_id)
    if not new_plan or not new_plan.is_active:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Get old plan (if exists)
    old_plan = None
    if sub.plan_id:
        old_plan = await db.get(InfluencerSubscriptionPlan, sub.plan_id)
    
    # Update subscription
    sub.plan_id = new_plan.id
    sub.price_cents = new_plan.price_cents
    sub.currency = new_plan.currency
    
    # Store change in meta
    if not sub.meta:
        sub.meta = {}
    sub.meta["previous_plan_id"] = old_plan.id if old_plan else None
    sub.meta["plan_changed_at"] = datetime.now(timezone.utc).isoformat()
    
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    
    return {
        "ok": True,
        "message": f"Plan changed from {old_plan.plan_name if old_plan else 'custom'} to {new_plan.plan_name}",
        "old_plan": old_plan.plan_name if old_plan else None,
        "new_plan": new_plan.plan_name,
        "new_price": f"${new_plan.price_cents/100:.0f}/month",
        "applies_at_next_billing": True,
        "next_billing_date": sub.next_payment_at.isoformat() if sub.next_payment_at else None,
    }


@router.get("/{influencer_id}/plan")
async def get_current_plan(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get current subscription plan details for an influencer.
    """
    # Get subscription
    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )
    
    if not sub:
        return {
            "has_subscription": False,
            "plan": None,
        }
    
    # Get plan if linked
    plan = None
    if sub.plan_id:
        plan = await db.get(InfluencerSubscriptionPlan, sub.plan_id)
    
    return {
        "has_subscription": True,
        "subscription": {
            "status": sub.status,
            "price_cents": sub.price_cents,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "next_payment_at": sub.next_payment_at.isoformat() if sub.next_payment_at else None,
            "is_18_selected": sub.is_18_selected,
        },
        "plan": {
            "id": plan.id,
            "name": plan.plan_name,
            "price": f"${plan.price_cents/100:.0f}/month",
            "description": plan.description,
            "features": plan.features,
        } if plan else None,
    }


# ========================================
# ADD-ONS & WALLET BALANCE
# ========================================

class PurchaseAddonRequest(BaseModel):
    addon_plan_id: int
    influencer_id: str


@router.post("/addons/purchase")
async def purchase_addon(
    req: PurchaseAddonRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Purchase an add-on pack (requires active subscription).
    Add-ons add credits to wallet immediately.
    """
    # Check if user has active subscription
    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == req.influencer_id,
            InfluencerSubscription.status == "active",
        )
    )
    
    if not sub:
        raise HTTPException(
            status_code=400,
            detail="Active subscription required to purchase add-ons"
        )
    
    # Get add-on plan
    addon_plan = await db.get(InfluencerSubscriptionPlan, req.addon_plan_id)
    if not addon_plan or addon_plan.interval != "addon" or not addon_plan.is_active:
        raise HTTPException(status_code=404, detail="Add-on plan not found")
    
    # Get or create wallet
    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == req.influencer_id,
            InfluencerWallet.is_18.is_(True),
        )
    )
    
    if not wallet:
        wallet = InfluencerWallet(
            user_id=user.id,
            influencer_id=req.influencer_id,
            balance_cents=0,
            is_18=True,
        )
        db.add(wallet)
        await db.flush()
    
    # Add credits to wallet
    credits_to_add = addon_plan.price_cents
    if addon_plan.features and "credits_granted" in addon_plan.features:
        credits_to_add = addon_plan.features["credits_granted"]
    
    old_balance = wallet.balance_cents or 0
    
    # Add add-on credits to balance
    wallet.balance_cents = old_balance + credits_to_add
    db.add(wallet)
    
    # Record add-on purchase
    # Generate unique transaction ID using UUID to prevent race conditions
    transaction_id = f"addon_{uuid.uuid4()}"
    addon_purchase = InfluencerSubscriptionAddonPurchase(
        subscription_id=sub.id,
        user_id=user.id,
        influencer_id=req.influencer_id,
        plan_id=addon_plan.id,
        amount_paid_cents=addon_plan.price_cents,
        credits_granted=credits_to_add,
        currency=addon_plan.currency,
        provider="simulated",  # Replace with actual provider (paypal/stripe)
        provider_transaction_id=transaction_id,
        purchased_at=datetime.now(timezone.utc),
    )
    db.add(addon_purchase)
    
    # Also record in payment ledger
    payment = InfluencerSubscriptionPayment(
        subscription_id=sub.id,
        user_id=user.id,
        influencer_id=req.influencer_id,
        amount_cents=addon_plan.price_cents,
        kind="addon_purchase",
        status="succeeded",
        provider="simulated",
        provider_event_id=transaction_id,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    
    await db.commit()
    await db.refresh(wallet)
    await db.refresh(addon_purchase)
    
    return {
        "ok": True,
        "message": f"Add-on purchased: {addon_plan.plan_name}",
        "purchase_id": addon_purchase.id,
        "addon_name": addon_plan.plan_name,
        "price_paid": addon_plan.price_cents,
        "credits_added": credits_to_add,
        "old_balance": old_balance,
        "new_balance": wallet.balance_cents,
        "purchased_at": addon_purchase.purchased_at.isoformat(),
    }


@router.get("/{influencer_id}/addon-history")
async def get_addon_purchase_history(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 20,
):
    """
    Get add-on purchase history for this user and influencer.
    """
    purchases = await db.scalars(
        select(InfluencerSubscriptionAddonPurchase)
        .where(
            InfluencerSubscriptionAddonPurchase.user_id == user.id,
            InfluencerSubscriptionAddonPurchase.influencer_id == influencer_id,
        )
        .order_by(InfluencerSubscriptionAddonPurchase.purchased_at.desc())
        .limit(limit)
    )
    
    purchases_list = purchases.all()
    
    # Get plan details for each purchase
    plan_ids = [p.plan_id for p in purchases_list]
    plans = {}
    if plan_ids:
        plan_results = await db.scalars(
            select(InfluencerSubscriptionPlan).where(
                InfluencerSubscriptionPlan.id.in_(plan_ids)
            )
        )
        plans = {p.id: p for p in plan_results.all()}
    
    # Calculate totals
    total_spent = sum(p.amount_paid_cents for p in purchases_list)
    total_credits = sum(p.credits_granted for p in purchases_list)
    
    return {
        "purchases": [
            {
                "id": p.id,
                "addon_name": plans.get(p.plan_id).plan_name if p.plan_id in plans else "Unknown",
                "amount_paid_cents": p.amount_paid_cents,
                "amount_paid_display": f"${p.amount_paid_cents/100:.2f}",
                "credits_granted": p.credits_granted,
                "credits_display": f"${p.credits_granted/100:.2f}",
                "purchased_at": p.purchased_at.isoformat(),
                "provider": p.provider,
            }
            for p in purchases_list
        ],
        "total_purchases": len(purchases_list),
        "total_spent_cents": total_spent,
        "total_spent_display": f"${total_spent/100:.2f}",
        "total_credits_granted": total_credits,
        "total_credits_display": f"${total_credits/100:.2f}",
    }


@router.get("/{influencer_id}/addon-stats")
async def get_addon_stats(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get add-on purchase statistics (lifetime totals, most purchased, etc.)
    """
    purchases = await db.scalars(
        select(InfluencerSubscriptionAddonPurchase)
        .where(
            InfluencerSubscriptionAddonPurchase.user_id == user.id,
            InfluencerSubscriptionAddonPurchase.influencer_id == influencer_id,
        )
    )
    
    purchases_list = purchases.all()
    
    if not purchases_list:
        return {
            "total_purchases": 0,
            "total_spent_cents": 0,
            "total_credits_granted": 0,
            "most_purchased_addon": None,
            "average_purchase_cents": 0,
            "last_purchase_at": None,
        }
    
    # Calculate stats
    total_spent = sum(p.amount_paid_cents for p in purchases_list)
    total_credits = sum(p.credits_granted for p in purchases_list)
    
    # Find most purchased addon
    from collections import Counter
    plan_counts = Counter(p.plan_id for p in purchases_list)
    most_common_plan_id = plan_counts.most_common(1)[0][0]
    most_common_plan = await db.get(InfluencerSubscriptionPlan, most_common_plan_id)
    
    last_purchase = max(purchases_list, key=lambda p: p.purchased_at)
    
    return {
        "total_purchases": len(purchases_list),
        "total_spent_cents": total_spent,
        "total_spent_display": f"${total_spent/100:.2f}",
        "total_credits_granted": total_credits,
        "total_credits_display": f"${total_credits/100:.2f}",
        "most_purchased_addon": {
            "plan_id": most_common_plan.id,
            "plan_name": most_common_plan.plan_name,
            "purchase_count": plan_counts[most_common_plan_id],
        } if most_common_plan else None,
        "average_purchase_cents": total_spent // len(purchases_list),
        "average_purchase_display": f"${(total_spent // len(purchases_list))/100:.2f}",
        "last_purchase_at": last_purchase.purchased_at.isoformat(),
    }


@router.get("/{influencer_id}/wallet-balance")
async def get_wallet_balance(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get wallet balance and check if add-ons should be offered.
    """
    # Get subscription
    sub = await db.scalar(
        select(InfluencerSubscription).where(
            InfluencerSubscription.user_id == user.id,
            InfluencerSubscription.influencer_id == influencer_id,
        )
    )
    
    # Get wallet
    wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == user.id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(True),
        )
    )
    
    balance_cents = wallet.balance_cents if wallet else 0
    
    # Determine if add-ons should be offered (balance < $30)
    should_offer_addons = balance_cents < 3000 and sub and sub.status == "active"
    
    return {
        "balance_cents": balance_cents,
        "balance_display": f"${balance_cents/100:.2f}",
        "has_subscription": sub is not None and sub.status == "active",
        "should_offer_addons": should_offer_addons,
        "low_balance_threshold": 3000,  # $30
    }