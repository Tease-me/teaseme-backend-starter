"""Relationship state tracking models."""

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Boolean, ForeignKey, DateTime, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RelationshipState(Base):
    """Tracks relationship progression between user and influencer."""
    
    __tablename__ = "relationship_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    influencer_id: Mapped[str] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), index=True)

    # Relationship dimensions
    trust: Mapped[float] = mapped_column(Float, default=10.0)
    closeness: Mapped[float] = mapped_column(Float, default=10.0)
    attraction: Mapped[float] = mapped_column(Float, default=5.0)
    safety: Mapped[float] = mapped_column(Float, default=95.0)

    state: Mapped[str] = mapped_column(String, default="STRANGERS")

    # Define The Relationship (DTR) tracking
    exclusive_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    girlfriend_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    dtr_stage: Mapped[int] = mapped_column(Integer, default=0)
    dtr_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Sentiment tracking
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
