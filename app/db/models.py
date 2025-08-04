from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, JSON
from typing import Optional, List, Dict

from datetime import datetime
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    """Common base class – can host __repr__ or metadata config later."""
    pass

# ───────────────────────────────────────────────────────────────────────────────
#  Master persona table  (replaces hard‑coded dict)
# ───────────────────────────────────────────────────────────────────────────────
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
    daily_scripts:  Mapped[List[str] | None] = mapped_column(JSON, nullable=True)
    created_at:     Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)

    chats:          Mapped[List["Chat"]] = relationship(back_populates="influencer")

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chats = relationship("Chat", back_populates="user")

class Chat(Base):
    __tablename__ = "chats"

    id:           Mapped[str]  = mapped_column(String, primary_key=True)  # UUID
    user_id:      Mapped[int]  = mapped_column(ForeignKey("users.id"))
    influencer_id:Mapped[str]  = mapped_column(ForeignKey("influencers.id"))
    started_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # relationships
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user = relationship("User", back_populates="chats")
    influencer:  Mapped["Influencer"] = relationship(back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sender: Mapped[str] = mapped_column(String)  # 'user' ou 'ai'
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    chat = relationship("Chat", back_populates="messages")

class Memory(Base):
    __tablename__ = "memories"
    id = mapped_column(Integer, primary_key=True)
    chat_id = mapped_column(String, ForeignKey("chats.id"), index=True)
    content = mapped_column(Text)
    embedding = mapped_column(Vector(1536))
    sender = mapped_column(String)  # 'user', 'ai', 'fact', etc
    created_at = mapped_column(DateTime, default=datetime.utcnow)

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
    ts: Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)

class DailyUsage(Base):
    """Daily counter that resets at midnight UTC (for free tier usage)."""
    __tablename__ = "daily_usage"
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"), primary_key=True)
    date:    Mapped[datetime]= mapped_column(DateTime, primary_key=True)  # YYYY-MM-DD 00:00 UTC
    free_allowance: Mapped[int] = mapped_column(Integer, default=0)
    text_count: Mapped[int]  = mapped_column(Integer, default=0)
    voice_secs: Mapped[int]  = mapped_column(Integer, default=0)
    live_secs:  Mapped[int]  = mapped_column(Integer, default=0)