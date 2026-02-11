"""Billing, subscription, and payment database models."""

from datetime import datetime, timezone

from sqlalchemy import (
    Integer, String, Boolean, Text, ForeignKey, DateTime, JSON, 
    Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Subscription(Base):
    """Legacy subscription model."""
    
    __tablename__ = "subscriptions"
    
    id = mapped_column(Integer, primary_key=True)
    user_id = mapped_column(Integer, ForeignKey("users.id"))
    subscription_json = mapped_column(JSON)
    created_at = mapped_column(DateTime, default=datetime.utcnow)


class Pricing(Base):
    """Current pricing table for features."""
    
    __tablename__ = "pricing"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature: Mapped[str] = mapped_column(String)     # text / voice / live_chat
    unit: Mapped[str] = mapped_column(String)        # message / second
    price_cents: Mapped[int] = mapped_column(Integer)    # 5 ⇒ $0.05
    free_allowance: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class InfluencerWallet(Base):
    """User's credit wallet for a specific influencer."""
    
    __tablename__ = "influencer_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    influencer_id: Mapped[str] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_18: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # Single balance for all credits (subscription + add-ons)
    balance_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "influencer_id", "is_18", name="uq_user_influencer_wallet_mode"),
        Index("ix_infl_wallet_user_infl_mode", "user_id", "influencer_id", "is_18"),
    )


class InfluencerCreditTransaction(Base):
    """Individual credit transaction for billing."""
    
    __tablename__ = "influencer_credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), index=True)

    feature: Mapped[str] = mapped_column(String)      # text/voice/topup/refund
    units: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_infl_tx_user_infl_ts", "user_id", "influencer_id", "created_at"),
    )


class DailyUsage(Base):
    """Daily usage tracking per user."""
    
    __tablename__ = "daily_usage"
    
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, primary_key=True)  # YYYY-MM-DD 00:00 UTC
    is_18: Mapped[bool] = mapped_column(
        Boolean,
        primary_key=True,
        nullable=False,
        default=False,
        server_default="false",
    )
    free_allowance: Mapped[int] = mapped_column(Integer, default=0)
    text_count: Mapped[int] = mapped_column(Integer, default=0)
    voice_secs: Mapped[int] = mapped_column(Integer, default=0)
    live_secs: Mapped[int] = mapped_column(Integer, default=0)


class InfluencerSubscriptionPlan(Base):
    """Available subscription plan definitions."""
    
    __tablename__ = "influencer_subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    plan_name: Mapped[str] = mapped_column(String, nullable=False)  # "Basic", "Plus", "Premium"
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    interval: Mapped[str] = mapped_column(String, nullable=False, default="monthly")  # "monthly", "yearly", "addon"
    plan_type: Mapped[str] = mapped_column(String, nullable=False, default="recurring")  # "recurring", "addon"
    
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Example: {"credits_per_month": 14900, "priority_support": true}
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_plan_active", "is_active"),
    )


class InfluencerSubscription(Base):
    """User's active subscription to an influencer."""
    
    __tablename__ = "influencer_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    influencer_id: Mapped[str] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencer_subscription_plans.id"),
        nullable=True,
        index=True,
    )

    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="AUD")

    interval: Mapped[str] = mapped_column(String, nullable=False, default="monthly")

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # status: "active" | "paused" | "cancelled" | "expired"

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    provider: Mapped[str | None] = mapped_column(String, nullable=True)  # "paypal" | "stripe"
    provider_customer_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_18_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    payments = relationship(
        "InfluencerSubscriptionPayment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "influencer_id", name="uq_user_influencer_subscription"),
        Index("ix_inf_sub_user_infl", "user_id", "influencer_id"),
        Index("ix_inf_sub_status_nextpay", "status", "next_payment_at"),
    )


class InfluencerSubscriptionAddonPurchase(Base):
    """One-time add-on credit purchase."""
    
    __tablename__ = "influencer_subscription_addon_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("influencer_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    influencer_id: Mapped[str] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("influencer_subscription_plans.id"),
        nullable=False,
        index=True,
    )

    amount_paid_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_granted: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")

    provider: Mapped[str | None] = mapped_column(String, nullable=True)  # "paypal" | "stripe"
    provider_transaction_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_addon_purchase_user_infl", "user_id", "influencer_id", "purchased_at"),
    )


class InfluencerSubscriptionPayment(Base):
    """Payment record for a subscription."""
    
    __tablename__ = "influencer_subscription_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("influencer_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    influencer_id: Mapped[str] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="AUD")

    kind: Mapped[str] = mapped_column(String, nullable=False, default="charge")

    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    provider: Mapped[str | None] = mapped_column(String, nullable=True)  # "paypal"
    provider_event_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)

    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    subscription = relationship("InfluencerSubscription", back_populates="payments")

    __table_args__ = (
        Index("ix_inf_sub_pay_user_infl_time", "user_id", "influencer_id", "occurred_at"),
    )


class PayPalTopUp(Base):
    """PayPal credit top-up transaction."""
    
    __tablename__ = "paypal_topups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    order_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    cents: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String, default="CREATED")  # CREATED | COMPLETED | FAILED
    credited: Mapped[bool] = mapped_column(Boolean, default=False)
    fp_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    influencer_id: Mapped[str | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
