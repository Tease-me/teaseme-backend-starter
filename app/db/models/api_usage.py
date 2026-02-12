"""API usage tracking database model for token and cost analytics."""

from datetime import datetime, timezone

from sqlalchemy import (
    Integer, BigInteger, String, Boolean, Text, Float, ForeignKey, DateTime,
    Index, Date,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ApiUsageLog(Base):
    """Individual API call log for token and cost tracking.
    
    Categories:
        - text: Regular chat text messages
        - call: Regular voice calls (ElevenLabs ConvAI)
        - 18_chat: Adult text chat messages
        - 18_voice: Adult voice messages
        - system: Background/shared tasks (embeddings, fact extraction, etc.)
    
    Retention: All individual logs are kept forever.
    """

    __tablename__ = "api_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Category & Provider ──────────────────────────────────────
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)

    # ── Token Metrics (nullable for non-LLM services) ───────────
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Cost & Performance ───────────────────────────────────────
    estimated_cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_secs: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Context ──────────────────────────────────────────────────
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    influencer_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # ── Status ───────────────────────────────────────────────────
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_api_usage_cat_created", "category", "created_at"),
        Index("ix_api_usage_model_created", "model", "created_at"),
        Index("ix_api_usage_provider_created", "provider", "created_at"),
        Index("ix_api_usage_user_created", "user_id", "created_at"),
    )


class ApiUsageMonthly(Base):
    """Pre-aggregated 30-day rollup of API usage — kept forever.
    
    Each row = one unique (period_start, category, provider, model, purpose)
    combination with summed/averaged metrics for the 30-day window.
    """

    __tablename__ = "api_usage_monthly"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # First day of the 30-day period (e.g. 2026-01-01, 2026-01-31, ...)
    period_start: Mapped[datetime] = mapped_column(Date, nullable=False)

    # ── Grouping keys ────────────────────────────────────────────
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)

    # ── Aggregated metrics ───────────────────────────────────────
    total_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_duration_secs: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_monthly_period_cat", "period_start", "category"),
        Index("ix_monthly_period_model", "period_start", "model"),
        # Unique constraint to allow upsert
        Index(
            "uq_monthly_period_keys",
            "period_start", "category", "provider", "model", "purpose",
            unique=True,
        ),
    )

