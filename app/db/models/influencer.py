"""Influencer-related database models."""

from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, Index, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .chat import Chat
    from .user import User


class Influencer(Base):
    """Influencer/AI persona model."""
    
    __tablename__ = "influencers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    voice_id: Mapped[str | None] = mapped_column(String, nullable=True)  # ElevenLabs, etc.
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)

    bio_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    profile_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    native_language: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    daily_scripts: Mapped[List[str] | None] = mapped_column(JSON, nullable=True)
    samples: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    influencer_agent_id_third_part: Mapped[str | None] = mapped_column(String, nullable=True)
    
    fp_promoter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fp_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    custom_adult_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_audio_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    
    # Relationships
    chats: Mapped[List["Chat"]] = relationship(back_populates="influencer")
    followers: Mapped[List["InfluencerFollower"]] = relationship(
        back_populates="influencer",
        cascade="all, delete-orphan",
    )


class InfluencerFollower(Base):
    """User-Influencer follower relationship."""
    
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

    # Relationships
    influencer: Mapped["Influencer"] = relationship(back_populates="followers")
    user: Mapped["User"] = relationship(back_populates="following_influencers")

    __table_args__ = (
        Index("ix_influencer_followers_user_id", "user_id"),
    )


class PreInfluencer(Base):
    """Pre-registration influencer onboarding."""
    
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
