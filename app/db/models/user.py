"""User-related database models."""

from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .chat import Chat
    from .influencer import InfluencerFollower


class User(Base):
    """User account model."""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    
    # Moderation fields
    moderation_status: Mapped[str] = mapped_column(String, default="CLEAN") 
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    first_violation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_violation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Identity Verification (Didit)
    is_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_age_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_level: Mapped[str | None] = mapped_column(String, nullable=True)  # basic, full, premium
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    chats = relationship("Chat", back_populates="user")
    following_influencers: Mapped[List["InfluencerFollower"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
