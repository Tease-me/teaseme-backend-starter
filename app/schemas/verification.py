"""
Pydantic schemas for identity verification via Didit
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class VerificationSessionCreateRequest(BaseModel):
    """Request to create a new verification session - all fields are optional and auto-configured from environment"""
    workflow_type: Optional[str] = Field(
        default="kyc",
        description="Type of verification (defaults to 'kyc', workflow_id is auto-selected from environment)"
    )
    redirect_url: Optional[str] = Field(
        default=None,
        description="URL to redirect user after verification completion (uses DIDIT_REDIRECT_URL from environment if not provided)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for the verification session"
    )


class VerificationSessionResponse(BaseModel):
    """Response containing verification session details"""
    session_id: str = Field(description="Unique session identifier from Didit")
    verification_url: str = Field(description="URL to redirect user for verification")
    status: str = Field(description="Current status of the session")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When the verification session expires"
    )
    workflow_type: str = Field(description="Type of verification workflow")


class VerificationStatusResponse(BaseModel):
    """Response for checking verification status"""
    session_id: str
    status: str = Field(
        description="Status: pending, in_progress, completed, failed, expired"
    )
    verified: bool = Field(default=False, description="Whether verification passed")
    verification_level: Optional[str] = Field(
        default=None,
        description="Verification level: basic, full, or premium"
    )
    verified_age: Optional[int] = Field(default=None, description="Verified age if applicable")
    document_type: Optional[str] = Field(default=None, description="Type of document verified")
    document_country: Optional[str] = Field(default=None, description="Country of document")
    risk_score: Optional[float] = Field(default=None, description="Risk assessment score")
    completed_at: Optional[datetime] = Field(default=None, description="Completion timestamp")
    failure_reason: Optional[str] = Field(default=None, description="Reason if verification failed")


class VerificationResultResponse(BaseModel):
    """Detailed verification result response"""
    session_id: str
    user_id: int
    verified: bool
    verification_level: Optional[str] = None
    verified_age: Optional[int] = None
    document_type: Optional[str] = None
    document_country: Optional[str] = None
    risk_score: Optional[float] = None
    aml_checked: bool = False
    biometric_passed: bool = False
    liveness_passed: bool = False
    completed_at: Optional[datetime] = None
    verification_data: Optional[Dict[str, Any]] = None


class UserVerificationStatus(BaseModel):
    """User's current verification status"""
    user_id: int
    is_identity_verified: bool
    is_age_verified: bool
    verification_level: Optional[str] = None
    verified_at: Optional[datetime] = None
    can_access_18_plus: bool = Field(
        description="Whether user can access 18+ content"
    )
    pending_verifications: int = Field(
        default=0,
        description="Number of pending verification sessions"
    )


class VerificationHistoryItem(BaseModel):
    """Single verification attempt in history"""
    id: int
    session_id: str
    workflow_type: str
    status: str
    verified: bool = False
    verification_level: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None


class VerificationHistoryResponse(BaseModel):
    """User's verification history"""
    user_id: int
    verifications: list[VerificationHistoryItem]
    total_attempts: int
    successful_attempts: int
    last_verification_at: Optional[datetime] = None
