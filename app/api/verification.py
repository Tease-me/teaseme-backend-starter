"""
Identity Verification API endpoints using Didit

This module provides endpoints for:
- Creating verification sessions
- Checking verification status
- Retrieving verification results
- Managing user verification history
"""
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from app.db.session import get_db
from app.db.models import User, IdentityVerification
from app.utils.deps import get_current_user
from app.services.didit import didit_service
from app.schemas.verification import (
    VerificationSessionCreateRequest,
    VerificationSessionResponse,
    VerificationStatusResponse,
    VerificationResultResponse,
    UserVerificationStatus,
    VerificationHistoryResponse,
    VerificationHistoryItem,
)
from app.core.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/session", response_model=VerificationSessionResponse)
async def create_verification_session(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_data: VerificationSessionCreateRequest = VerificationSessionCreateRequest(),
):
    """
    Create a new identity verification session for the current user.
    
    All configuration is automatic from environment variables - no request body needed!
    Simply POST to this endpoint and get back a verification URL.
    
    Returns a verification URL where the user should be redirected to complete
    the verification process with Didit.
    """
    try:
        # Create session with Didit (workflow_id is automatically selected from environment)
        didit_response = await didit_service.create_verification_session(
            user_id=user.id,
            workflow_type=request_data.workflow_type,
            redirect_url=request_data.redirect_url,
            metadata=request_data.metadata,
        )

        session_id = didit_response.get("session_id") or didit_response.get("id")
        
        # Check if this session already exists in database
        existing = await db.execute(
            select(IdentityVerification).where(
                IdentityVerification.session_id == session_id
            )
        )
        verification = existing.scalar_one_or_none()
        
        if verification:
            # Session already exists - return it instead of creating duplicate
            log.info(f"Returning existing verification session {session_id} for user {user.id}")
        else:
            # Store new verification record in database
            verification = IdentityVerification(
                user_id=user.id,
                session_id=session_id,
                workflow_id=didit_response.get("workflow_id", ""),
                workflow_type=request_data.workflow_type,
                status="pending",
                started_at=datetime.now(timezone.utc),
            )
            
            # Set expiration if provided by Didit
            if "expires_at" in didit_response:
                verification.expires_at = datetime.fromisoformat(
                    didit_response["expires_at"].replace("Z", "+00:00")
                )

            db.add(verification)
            await db.commit()
            await db.refresh(verification)
            
            log.info(f"Created new verification session {verification.session_id} for user {user.id}")

        return VerificationSessionResponse(
            session_id=verification.session_id,
            verification_url=didit_response.get("verification_url") or didit_response.get("url", ""),
            status=verification.status,
            expires_at=verification.expires_at,
            workflow_type=verification.workflow_type,
        )

    except Exception as e:
        log.error(f"Failed to create verification session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create verification session: {str(e)}"
        )


@router.get("/session/{session_id}", response_model=VerificationStatusResponse)
async def get_verification_status(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current status of a verification session.
    
    This endpoint polls the Didit API for the latest status and updates
    the local database accordingly.
    """
    # Verify session belongs to current user
    result = await db.execute(
        select(IdentityVerification).where(
            IdentityVerification.session_id == session_id,
            IdentityVerification.user_id == user.id,
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(status_code=404, detail="Verification session not found")

    try:
        # Fetch latest status from Didit
        didit_status = await didit_service.get_session_status(session_id)
        
        # Update local record
        verification.status = didit_status.get("status", verification.status)
        verification.webhook_payload = didit_status
        
        if didit_status.get("status") in ["completed", "verified"]:
            # Fetch full verification result
            result_data = await didit_service.get_verification_result(session_id)
            parsed = didit_service.parse_verification_result(result_data)
            
            verification.verification_result = result_data
            verification.verified_age = parsed.get("age")
            verification.document_type = parsed.get("document_type")
            verification.document_country = parsed.get("document_country")
            verification.risk_score = parsed.get("risk_score")
            verification.aml_checked = parsed.get("aml_checked", False)
            verification.completed_at = datetime.now(timezone.utc)
            
            # Update user verification status
            if parsed.get("verified"):
                user.is_identity_verified = True
                user.verification_level = parsed.get("verification_level")
                user.verified_at = datetime.now(timezone.utc)
                
                # Set age verification if age was verified
                if parsed.get("age") and parsed.get("age") >= 18:
                    user.is_age_verified = True
        
        elif didit_status.get("status") in ["failed", "expired"]:
            verification.status = didit_status.get("status")
            verification.failure_reason = didit_status.get("failure_reason")
            verification.completed_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(verification)

        return VerificationStatusResponse(
            session_id=verification.session_id,
            status=verification.status,
            verified=user.is_identity_verified,
            verification_level=user.verification_level,
            verified_age=verification.verified_age,
            document_type=verification.document_type,
            document_country=verification.document_country,
            risk_score=verification.risk_score,
            completed_at=verification.completed_at,
            failure_reason=verification.failure_reason,
        )

    except Exception as e:
        log.error(f"Failed to fetch verification status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch verification status: {str(e)}"
        )


@router.get("/status", response_model=UserVerificationStatus)
async def get_user_verification_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current user's overall verification status.
    
    Returns information about whether they are verified and can access
    restricted content.
    """
    # Count pending verifications
    result = await db.execute(
        select(IdentityVerification).where(
            IdentityVerification.user_id == user.id,
            IdentityVerification.status.in_(["pending", "in_progress"]),
        )
    )
    pending_count = len(result.scalars().all())

    # Determine if user can access 18+ content
    can_access_18_plus = user.is_age_verified or (
        user.is_identity_verified and user.verification_level in ["full", "premium"]
    )

    return UserVerificationStatus(
        user_id=user.id,
        is_identity_verified=user.is_identity_verified,
        is_age_verified=user.is_age_verified,
        verification_level=user.verification_level,
        verified_at=user.verified_at,
        can_access_18_plus=can_access_18_plus,
        pending_verifications=pending_count,
    )


@router.get("/history", response_model=VerificationHistoryResponse)
async def get_verification_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current user's verification history.
    
    Returns a list of all verification attempts, both successful and failed.
    """
    result = await db.execute(
        select(IdentityVerification)
        .where(IdentityVerification.user_id == user.id)
        .order_by(desc(IdentityVerification.created_at))
    )
    verifications = result.scalars().all()

    history_items = [
        VerificationHistoryItem(
            id=v.id,
            session_id=v.session_id,
            workflow_type=v.workflow_type,
            status=v.status,
            verified=(v.status == "completed"),
            verification_level=user.verification_level if v.status == "completed" else None,
            started_at=v.started_at,
            completed_at=v.completed_at,
            failure_reason=v.failure_reason,
        )
        for v in verifications
    ]

    successful_count = sum(1 for v in verifications if v.status == "completed")
    last_verification = verifications[0].completed_at if verifications and verifications[0].completed_at else None

    return VerificationHistoryResponse(
        user_id=user.id,
        verifications=history_items,
        total_attempts=len(verifications),
        successful_attempts=successful_count,
        last_verification_at=last_verification,
    )
