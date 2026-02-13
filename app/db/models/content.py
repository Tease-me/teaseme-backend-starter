"""Content moderation and re-engagement models."""

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ContentViolation(Base):
    """Content moderation violation record."""
    
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
    
    # Review tracking
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
    """Re-engagement notification tracking."""
    
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
