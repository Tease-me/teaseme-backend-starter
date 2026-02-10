from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, JSON, Index, Float, UniqueConstraint
from typing import Optional, List
from sqlalchemy.dialects.postgresql import JSONB

from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
Integer, String, DateTime, ForeignKey, Boolean,
UniqueConstraint, Index, JSON, Text
)

class Base(DeclarativeBase):
    pass

class Influencer(Base):
    __tablename__ = "influencers"

    id:             Mapped[str]          = mapped_column(String, primary_key=True)
    display_name:   Mapped[str]          = mapped_column(String, nullable=False)
    owner_id:       Mapped[int | None]   = mapped_column(ForeignKey("users.id"), nullable=True)
    voice_id:       Mapped[str | None]   = mapped_column(String, nullable=True)        # ElevenLabs, etc.
    prompt_template:Mapped[str]          = mapped_column(Text, nullable=False)

    bio_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    profile_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    native_language: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    daily_scripts:  Mapped[List[str] | None] = mapped_column(JSON, nullable=True)
    samples: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    influencer_agent_id_third_part: Mapped[str | None] = mapped_column(String, nullable=True)
    
    fp_promoter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fp_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    custom_adult_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_audio_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferences_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at:     Mapped[datetime]     = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    chats:          Mapped[List["Chat"]] = relationship(back_populates="influencer")
    followers:      Mapped[List["InfluencerFollower"]] = relationship(
        back_populates="influencer",
        cascade="all, delete-orphan",
    )

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True,nullable=True)
    full_name: Mapped[str] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    gender: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_token: Mapped[str] = mapped_column(String, nullable=True)
    password_reset_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    password_reset_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    profile_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    custom_adult_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    moderation_status: Mapped[str] = mapped_column(String, default="CLEAN") 
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    first_violation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_violation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Identity Verification (Didit)
    is_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_age_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_level: Mapped[str | None] = mapped_column(String, nullable=True)  # basic, full, premium
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    chats = relationship("Chat", back_populates="user")
    following_influencers: Mapped[List["InfluencerFollower"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
class Chat(Base):
    __tablename__ = "chats"

    id:           Mapped[str]  = mapped_column(String, primary_key=True)  
    user_id:      Mapped[int]  = mapped_column(ForeignKey("users.id"))
    influencer_id:Mapped[str]  = mapped_column(ForeignKey("influencers.id"))
    started_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="chats")
    influencer:  Mapped["Influencer"] = relationship(back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sender: Mapped[str] = mapped_column(String) 
    channel: Mapped[str] = mapped_column(String, default="text")  
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    chat = relationship("Chat", back_populates="messages")
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("calls.conversation_id"), nullable=True)

class Chat18(Base):
    __tablename__ = "chats_18"

    id: Mapped[str] = mapped_column(String, primary_key=True) 
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

class Message18(Base):
    __tablename__ = "messages_18"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats_18.id"), index=True)
    sender: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="text_18")
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

class Memory(Base):
    __tablename__ = "memories"
    id = mapped_column(Integer, primary_key=True)
    chat_id = mapped_column(String, ForeignKey("chats.id"), index=True)
    content = mapped_column(Text)
    embedding = mapped_column(Vector(1536))
    sender = mapped_column(String)  # 'user', 'ai', 'fact', etc
    created_at = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = mapped_column(Integer, primary_key=True)
    user_id = mapped_column(Integer, ForeignKey("users.id"))
    subscription_json = mapped_column(JSON)
    created_at = mapped_column(DateTime, default=datetime.utcnow)

class Pricing(Base):
    """
    Current pricing table.
    Example: feature='text', unit='message', price_cents=5, free_allowance=100
    """
    __tablename__ = "pricing"
    id: Mapped[int]          = mapped_column(Integer, primary_key=True)
    feature: Mapped[str]     = mapped_column(String)     # text / voice / live_chat
    unit: Mapped[str]        = mapped_column(String)     # message / second
    price_cents: Mapped[int] = mapped_column(Integer)    # 5  ⇒  $0.05
    free_allowance: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool]  = mapped_column(Boolean, default=True)

class InfluencerWallet(Base):
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
    __tablename__ = "daily_usage"
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"), primary_key=True)
    date:    Mapped[datetime]= mapped_column(DateTime, primary_key=True)  # YYYY-MM-DD 00:00 UTC
    is_18: Mapped[bool] = mapped_column(
        Boolean,
        primary_key=True,
        nullable=False,
        default=False,
        server_default="false",
    )
    free_allowance: Mapped[int] = mapped_column(Integer, default=0)
    text_count: Mapped[int]  = mapped_column(Integer, default=0)
    voice_secs: Mapped[int]  = mapped_column(Integer, default=0)
    live_secs:  Mapped[int]  = mapped_column(Integer, default=0)

class CallRecord(Base):
    __tablename__ = "calls"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    influencer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chat_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("chats.id"), nullable=True, index=True
    )
    sid: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    call_duration_secs: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_calls_user_created", "user_id", "created_at"),
    )
    

class InfluencerFollower(Base):
    __tablename__ = "influencer_followers"

    influencer_id: Mapped[str] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    influencer: Mapped["Influencer"] = relationship(back_populates="followers")
    user: Mapped["User"] = relationship(back_populates="following_influencers")

    __table_args__ = (
        Index("ix_influencer_followers_user_id", "user_id"),
    )


class InfluencerSubscriptionPlan(Base):
    """
    Defines available subscription plans.
    Examples: Basic ($99), Plus ($149), Premium ($199)
    """
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

    subscription = relationship("InfluencerSubscription", back_populates="payments")

    __table_args__ = (
        Index("ix_inf_sub_pay_user_infl_time", "user_id", "influencer_id", "occurred_at"),
    )

class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class PreInfluencer(Base):

    __tablename__ = "pre_influencers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    full_name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    survey_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    survey_answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    survey_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    ig_user_id: Mapped[str] = mapped_column(String, nullable=True)
    ig_access_token: Mapped[str] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(
        String, default="pending", nullable=False
    ) 

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    terms_agreement: Mapped[bool] = mapped_column(Boolean, default=False)
    fp_promoter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fp_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)

class RelationshipState(Base):
    __tablename__ = "relationship_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), index=True)

    trust: Mapped[float] = mapped_column(Float, default=10.0)
    closeness: Mapped[float] = mapped_column(Float, default=10.0)
    attraction: Mapped[float] = mapped_column(Float, default=5.0)
    safety: Mapped[float] = mapped_column(Float, default=95.0)

    state: Mapped[str] = mapped_column(String, default="STRANGERS")

    exclusive_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    girlfriend_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    dtr_stage: Mapped[int] = mapped_column(Integer, default=0)
    dtr_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    stage_points: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_delta: Mapped[float] = mapped_column(Float, default=0.0)

    last_interaction_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_rel_user_influencer", "user_id", "influencer_id", unique=True),
    )

class PayPalTopUp(Base):
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


class ContentViolation(Base):
    __tablename__ = "content_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    chat_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    influencer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    message_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    category: Mapped[str] = mapped_column(String, nullable=False) 
    severity: Mapped[str] = mapped_column(String, nullable=False)  
    
    keyword_matched: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    detection_tier: Mapped[str] = mapped_column(String, nullable=False)  
    
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    review_action: Mapped[str | None] = mapped_column(String, nullable=True) 
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_violations_user_created", "user_id", "created_at"),
        Index("ix_violations_category", "category"),
        Index("ix_violations_reviewed", "reviewed"),
    )


class ReEngagementLog(Base):
    __tablename__ = "re_engagement_logs"

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

    notification_type: Mapped[str] = mapped_column(String, nullable=False)  # "text" | "image" | "video"
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    media_url: Mapped[str | None] = mapped_column(String, nullable=True)

    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscriptions_targeted: Mapped[int] = mapped_column(Integer, default=0)
    subscriptions_succeeded: Mapped[int] = mapped_column(Integer, default=0)

    wallet_balance_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    days_inactive: Mapped[int] = mapped_column(Integer, nullable=False)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_reeng_user_infl_triggered", "user_id", "influencer_id", "triggered_at"),
        Index("ix_reeng_triggered_at", "triggered_at"),
    )


class IdentityVerification(Base):
    """
    Tracks identity verification sessions via Didit.
    Each verification attempt creates a new record.
    """
    __tablename__ = "identity_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Didit session information
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(String, nullable=False)
    workflow_type: Mapped[str] = mapped_column(String, nullable=False)  # "kyc", "age", "biometric"

    # Verification status
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # Status: "pending", "in_progress", "completed", "failed", "expired"

    # Verification results
    verification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_identity_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Document information (if applicable)
    document_type: Mapped[str | None] = mapped_column(String, nullable=True)  # "passport", "id_card", "driver_license"
    document_country: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Risk & compliance
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aml_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    aml_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Session metadata
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Webhook data from Didit
    webhook_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Failure information
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
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
        Index("ix_identity_ver_user_status", "user_id", "status"),
        Index("ix_identity_ver_session", "session_id"),
        Index("ix_identity_ver_created", "created_at"),
    )


class PreferenceCatalog(Base):
    """Master catalog of ~70 preference items for like/dislike system."""
    __tablename__ = "preference_catalog"

    key: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "food_sushi"
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)  # e.g. "food_and_drink"
    label: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Sushi"
    emoji: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "🍣"

    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserPreference(Base):
    """What a user likes or dislikes."""
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preference_key: Mapped[str] = mapped_column(
        ForeignKey("preference_catalog.key", ondelete="CASCADE"),
        nullable=False,
    )
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False)  # True = likes, False = dislikes

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "preference_key", name="uq_user_pref"),
        Index("ix_user_pref_user", "user_id"),
    )


# ============================================================================
# CONVERSATION LEARNING SYSTEM
# ============================================================================

class ConversationAnalysis(Base):
    """
    Stores detailed analysis of each AI turn for learning purposes.
    Records what the AI said, user's response, and quality metrics.
    """
    __tablename__ = "conversation_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), nullable=False)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    
    # The messages that were analyzed
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)
    user_next_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Context at the time of the AI response
    relationship_state: Mapped[str] = mapped_column(String, nullable=False)
    mood_at_turn: Mapped[str | None] = mapped_column(String, nullable=True)
    memories_at_turn: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # LLM-generated scores (1-10)
    engagement_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interest_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initiative_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appropriateness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # LLM-generated feedback
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_failed: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_improvement: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_reaction_type: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Quick pattern detection (before LLM analysis)
    detected_issues: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    
    # Timestamps
    ai_response_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    user_next_message_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seconds_to_reply: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    __table_args__ = (
        Index('ix_analyses_chat_influencer', 'chat_id', 'influencer_id'),
        Index('ix_analyses_overall_score', 'overall_score'),
        Index('ix_analyses_analyzed', 'analyzed_at'),
    )


class ConversationLearning(Base):
    """
    Stores learned patterns about what works or fails for each influencer/stage.
    Generated from ConversationAnalysis data.
    """
    __tablename__ = "conversation_learnings"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    
    # What pattern was observed
    pattern_type: Mapped[str] = mapped_column(String, nullable=False)  # "avoid" or "repeat"
    pattern_description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Example that triggered this learning
    example_user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_reaction: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Confidence metrics
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    success_rate: Mapped[float] = mapped_column(Float, default=0.5)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    
    __table_args__ = (
        Index('idx_learnings_influencer_stage', 'influencer_id', 'stage'),
        Index('ix_learnings_pattern_type', 'pattern_type'),
        Index('ix_learnings_confidence', 'confidence'),
    )


class ConversationPattern(Base):
    """
    Curated good conversation examples (manually added or promoted from learnings).
    """
    __tablename__ = "conversation_patterns"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    influencer_id: Mapped[str | None] = mapped_column(ForeignKey("influencers.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Example
    example_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # When to use
    suitable_topics: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    avoid_after: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    
    effectiveness_score: Mapped[float] = mapped_column(Float, default=1.0)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    
    __table_args__ = (
        Index('ix_patterns_influencer_stage', 'influencer_id', 'stage'),
        Index('ix_patterns_effectiveness', 'effectiveness_score'),
    )
