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
    """Common base class – can host __repr__ or metadata config later."""
    pass

class Influencer(Base):
    """
    One row per persona/influencer.  The `id` column will be the new
    `influencer_id` referenced from Chat.
    """
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

    custom_adult_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_audio_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    chats = relationship("Chat", back_populates="user")
    following_influencers: Mapped[List["InfluencerFollower"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
class Chat(Base):
    __tablename__ = "chats"

    id:           Mapped[str]  = mapped_column(String, primary_key=True)  # UUID
    user_id:      Mapped[int]  = mapped_column(ForeignKey("users.id"))
    influencer_id:Mapped[str]  = mapped_column(ForeignKey("influencers.id"))
    started_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # relationships
    user = relationship("User", back_populates="chats")
    influencer:  Mapped["Influencer"] = relationship(back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sender: Mapped[str] = mapped_column(String)  # 'user' ou 'ai'
    channel: Mapped[str] = mapped_column(String, default="text")  # 'text' or 'call'
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    chat = relationship("Chat", back_populates="messages")
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("calls.conversation_id"), nullable=True)

class Chat18(Base):
    __tablename__ = "chats_18"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID
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
    """Daily counter that resets at midnight UTC (for free tier usage)."""
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
    """Join table capturing a follow between a user and an influencer."""
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



# -----------------------------
# InfluencerSubscription
# -----------------------------
class InfluencerSubscription(Base):
    """
    One paid subscription per (user_id, influencer_id).
    Holds the current state of the subscription.
    """
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

    # Money / Plan
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="AUD")

    interval: Mapped[str] = mapped_column(String, nullable=False, default="monthly")
    # interval: "weekly" | "monthly" | "yearly"

    # Status lifecycle
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # status: "active" | "paused" | "canceled" | "expired"

    # Dates
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

    # Provider refs (super important)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)  # "paypal" | "stripe"
    provider_customer_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Extra metadata / debugging
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

    # relationships
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


# -----------------------------
# SubscriptionPayment (ledger)
# -----------------------------
class InfluencerSubscriptionPayment(Base):
    """
    Immutable ledger of payment attempts/events for a subscription.
    Every capture / refund / failed payment becomes a row here.
    """
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

    # Amount
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="AUD")

    # Type + status
    kind: Mapped[str] = mapped_column(String, nullable=False, default="charge")
    # kind: "charge" | "refund" | "chargeback"

    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # status: "pending" | "succeeded" | "failed" | "refunded"

    # Provider refs
    provider: Mapped[str | None] = mapped_column(String, nullable=True)  # "paypal"
    provider_event_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    # ex: PayPal capture_id OR PayPal order_id OR webhook event id

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
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
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
    """
    Pre-onboarding record for someone who wants to be an influencer.
    This is created from the simple signup:
      full_name, location, username, email
    """
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
    )  # pending / approved / rejected / converted 

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
