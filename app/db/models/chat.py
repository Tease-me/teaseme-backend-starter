"""Chat and messaging database models."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, Text, ForeignKey, DateTime, JSON, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from .base import Base

if TYPE_CHECKING:
    from .user import User
    from .influencer import Influencer


class Chat(Base):
    """Regular chat session between user and influencer."""
    
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String, primary_key=True)  
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="chats")
    influencer: Mapped["Influencer"] = relationship(back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    """Individual message in a chat."""
    
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sender: Mapped[str] = mapped_column(String) 
    channel: Mapped[str] = mapped_column(String, default="text")  
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("calls.conversation_id"), nullable=True)
    
    # Relationships
    chat = relationship("Chat", back_populates="messages")


class Chat18(Base):
    """Adult (18+) chat session between user and influencer."""
    
    __tablename__ = "chats_18"

    id: Mapped[str] = mapped_column(String, primary_key=True) 
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Message18(Base):
    """Individual message in an adult (18+) chat."""
    
    __tablename__ = "messages_18"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats_18.id"), index=True)
    sender: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="text_18")
    content: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)


class Memory(Base):
    """Long-term memory/facts extracted from conversations."""
    
    __tablename__ = "memories"
    
    id = mapped_column(Integer, primary_key=True)
    chat_id = mapped_column(String, ForeignKey("chats.id"), index=True)
    content = mapped_column(Text)
    embedding = mapped_column(Vector(1536))
    sender = mapped_column(String)  # 'user', 'ai', 'fact', etc
    created_at = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )


class CallRecord(Base):
    """Voice call session record."""
    
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_calls_user_created", "user_id", "created_at"),
    )
