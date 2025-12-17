from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, JSON, Index, Float
from typing import Optional, List

from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector

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
    voice_prompt:   Mapped[str | None] = mapped_column(String, nullable=True)
    profile_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    native_language: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    daily_scripts:  Mapped[List[str] | None] = mapped_column(JSON, nullable=True)
    influencer_agent_id_third_part: Mapped[str | None] = mapped_column(String, nullable=True)
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
    billing_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_topup_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_topup_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    low_balance_threshold_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

class CreditWallet(Base):
    """User's prepaid balance (>= 0)."""
    __tablename__ = "credit_wallets"
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)

class CreditTransaction(Base):
    """Immutable ledger of debits and credits."""
    __tablename__ = "credit_transactions"
    id: Mapped[int]          = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"))
    feature: Mapped[str]     = mapped_column(String)      # text / voice / live_chat / topup / refund
    units: Mapped[int]       = mapped_column(Integer)     # -1 msg, -30 secs, +10000 topup
    amount_cents: Mapped[int] = mapped_column(Integer)    # -5, -60, +1000 …
    meta: Mapped[dict]       = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class DailyUsage(Base):
    """Daily counter that resets at midnight UTC (for free tier usage)."""
    __tablename__ = "daily_usage"
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"), primary_key=True)
    date:    Mapped[datetime]= mapped_column(DateTime, primary_key=True)  # YYYY-MM-DD 00:00 UTC
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

class InfluencerKnowledgeFile(Base):
    """Metadata for uploaded knowledge files (PDF, Word, etc.)"""
    __tablename__ = "influencer_knowledge_files"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)  # 'pdf', 'docx', 'txt'
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="processing")  # processing, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    chunks: Mapped[List["InfluencerKnowledgeChunk"]] = relationship(back_populates="file", cascade="all, delete-orphan")

class InfluencerKnowledgeChunk(Base):
    """Chunked and embedded content from knowledge files"""
    __tablename__ = "influencer_knowledge_chunks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("influencer_knowledge_files.id", ondelete="CASCADE"), index=True)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    chunk_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # page number, section, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    file: Mapped["InfluencerKnowledgeFile"] = relationship(back_populates="chunks")
    
    __table_args__ = (
        Index("idx_knowledge_chunks_influencer", "influencer_id"),
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

