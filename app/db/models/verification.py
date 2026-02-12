"""Identity verification models."""

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, JSON, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IdentityVerification(Base):
    """Tracks identity verification sessions via Didit."""
    
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
