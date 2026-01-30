"""
Identity Verification API endpoints using Didit

This module provides endpoints for:
- Creating verification sessions
- Checking verification status
- Retrieving verification results
- Managing user verification history
- Handling real-time webhook notifications
"""
import logging
import hmac
import hashlib
import json
from time import time
from datetime import datetime, timezone
from typing import List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
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


@router.post("/session/{session_id}/complete", response_model=VerificationStatusResponse)
async def complete_verification_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Complete a verification session after redirect from Didit.
    
    This endpoint should be called from your redirect page after Didit
    redirects the user back. It will:
    1. Fetch the verification decision from Didit
    2. Update the identity_verifications table
    3. Update the user's verification status
    4. Return the final verification result
    
    The session_id will be in the redirect URL query parameters.
    """
    try:
        # Find the verification record
        result = await db.execute(
            select(IdentityVerification).where(
                IdentityVerification.session_id == session_id,
                IdentityVerification.user_id == user.id,
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            raise HTTPException(
                status_code=404,
                detail="Verification session not found"
            )

        # Fetch decision from Didit
        log.info(f"Completing verification session {session_id} for user {user.id}")
        didit_response = await didit_service.get_session_status(session_id)
        
        # Parse the Didit response
        decision = didit_response.get("decision", {})
        status = decision.get("type", "").lower()  # "approved", "declined", etc.
        
        # Map Didit status to our status
        if status == "approved":
            verification.status = "completed"
            verification.completed_at = datetime.now(timezone.utc)
            
            # Extract verification details from Didit response
            extracted_data = didit_response.get("extracted_data", {})
            
            # Update verification record with details
            if "date_of_birth" in extracted_data:
                # Calculate age from date of birth
                try:
                    dob = datetime.fromisoformat(extracted_data["date_of_birth"].replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - dob).days // 365
                    verification.verified_age = age
                except Exception as e:
                    log.warning(f"Failed to parse date_of_birth: {e}")
            
            if "document_type" in extracted_data:
                verification.document_type = extracted_data["document_type"]
            
            if "document_country" in extracted_data:
                verification.document_country = extracted_data["document_country"]
            
            # Store the full result
            verification.verification_result = didit_response
            
            # Update user verification status
            user.is_identity_verified = True
            user.verified_at = datetime.now(timezone.utc)
            
            # Set age verification if age >= 18
            if verification.verified_age and verification.verified_age >= 18:
                user.is_age_verified = True
            
            # Set verification level based on workflow type
            if verification.workflow_type == "kyc":
                user.verification_level = "full"
            
            log.info(f"Verification completed successfully for user {user.id}")
            
        elif status in ["declined", "rejected"]:
            verification.status = "failed"
            verification.completed_at = datetime.now(timezone.utc)
            verification.failure_reason = decision.get("reasons", [{}])[0].get("message") if decision.get("reasons") else "Verification declined"
            log.warning(f"Verification declined for user {user.id}: {verification.failure_reason}")
            
        elif status in ["expired", "abandoned"]:
            verification.status = "expired"
            verification.completed_at = datetime.now(timezone.utc)
            verification.failure_reason = "Session expired or abandoned"
            log.warning(f"Verification expired for user {user.id}")
        else:
            # Still pending or in progress
            verification.status = "in_progress"
            log.info(f"Verification still in progress for user {user.id}")

        await db.commit()
        await db.refresh(verification)
        await db.refresh(user)

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

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to complete verification session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to complete verification: {str(e)}"
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


# ============================================================================
# Webhook Verification Helper Functions
# ============================================================================

def shorten_floats(data: Any) -> Any:
    """Process floats to match server-side behavior."""
    if isinstance(data, dict):
        return {key: shorten_floats(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [shorten_floats(item) for item in data]
    elif isinstance(data, float):
        if data.is_integer():
            return int(data)
    return data


def verify_webhook_signature_v2(
    request_body_json: dict,
    signature_header: str,
    timestamp_header: str,
    secret_key: str
) -> bool:
    """
    Verify X-Signature-V2 (Recommended).
    Works even if middleware re-encodes special characters.
    """
    # Check timestamp freshness (within 5 minutes)
    try:
        timestamp = int(timestamp_header)
        current_time = int(time())
        time_diff = abs(current_time - timestamp)
        log.debug(f"Timestamp check: webhook={timestamp}, server={current_time}, diff={time_diff}s")
        if time_diff > 300:
            log.warning(f"Timestamp too old/new: diff={time_diff}s (max 300s)")
            return False
    except (ValueError, TypeError) as e:
        log.error(f"Invalid timestamp format: {timestamp_header} - {e}")
        return False

    # Process floats and re-encode with unescaped Unicode
    processed_data = shorten_floats(request_body_json)
    encoded_data = json.dumps(
        processed_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False  # Keep Unicode as-is
    )

    # Calculate expected signature
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        encoded_data.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_signature)


def verify_webhook_signature_simple(
    request_body_json: dict,
    signature_header: str,
    timestamp_header: str,
    secret_key: str
) -> bool:
    """
    Verify X-Signature-Simple (Fallback).
    Independent of JSON encoding - verifies core fields only.
    """
    # Check timestamp freshness (within 5 minutes)
    try:
        timestamp = int(timestamp_header)
        current_time = int(time())
        if abs(current_time - timestamp) > 300:
            log.warning(f"Timestamp too old/new (simple): diff={abs(current_time - timestamp)}s")
            return False
    except (ValueError, TypeError) as e:
        log.error(f"Invalid timestamp format (simple): {timestamp_header} - {e}")
        return False

    # Build canonical string from core fields
    canonical_string = ":".join([
        str(request_body_json.get("timestamp", "")),
        str(request_body_json.get("session_id", "")),
        str(request_body_json.get("status", "")),
        str(request_body_json.get("webhook_type", "")),
    ])

    # Calculate expected signature
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_signature)


# ============================================================================
# Webhook Endpoint
# ============================================================================

@router.post("/webhook")
async def handle_didit_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook endpoint for receiving real-time verification status updates from Didit.
    
    Didit sends webhooks for:
    - status.updated: When verification status changes
    - data.updated: When KYC/POA data is manually updated
    
    The webhook is automatically verified using HMAC signatures (X-Signature-V2 or X-Signature-Simple).
    """
    # Get the raw request body and parse JSON
    try:
        body = await request.body()
        if not body:
            log.warning("Webhook received with empty body")
            raise HTTPException(status_code=400, detail="Request body is empty")
        
        json_body = json.loads(body.decode())
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in webhook: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get headers
    signature_v2 = request.headers.get("x-signature-v2")
    signature_simple = request.headers.get("x-signature-simple")
    timestamp = request.headers.get("x-timestamp")
    
    log.info(f"Webhook request received: has_v2_sig={bool(signature_v2)}, has_simple_sig={bool(signature_simple)}, has_timestamp={bool(timestamp)}")
    
    if not settings.DIDIT_WEBHOOK_SECRET:
        log.error("DIDIT_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    
    if not timestamp:
        log.warning("Missing X-Timestamp header")
        raise HTTPException(status_code=401, detail="Missing timestamp header")

    # Try X-Signature-V2 first (recommended)
    verified = False
    try:
        if signature_v2:
            verified = verify_webhook_signature_v2(
                json_body, signature_v2, timestamp, settings.DIDIT_WEBHOOK_SECRET
            )
            if verified:
                log.info("Webhook verified with X-Signature-V2")
        # Fall back to X-Signature-Simple
        elif signature_simple:
            verified = verify_webhook_signature_simple(
                json_body, signature_simple, timestamp, settings.DIDIT_WEBHOOK_SECRET
            )
            if verified:
                log.info("Webhook verified with X-Signature-Simple (fallback)")
    except Exception as e:
        log.error(f"Error during signature verification: {e}")
        raise HTTPException(status_code=500, detail=f"Signature verification error: {str(e)}")

    if not verified:
        log.warning(f"Webhook signature verification failed for session {json_body.get('session_id')}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Extract webhook data
    session_id = json_body.get("session_id")
    status = json_body.get("status")
    webhook_type = json_body.get("webhook_type")
    decision = json_body.get("decision", {})
    
    log.info(f"Webhook received: type={webhook_type}, session={session_id}, status={status}")

    try:
        # Find the verification record
        result = await db.execute(
            select(IdentityVerification).where(
                IdentityVerification.session_id == session_id
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            log.warning(f"Verification session not found: {session_id}")
            # Return 200 to acknowledge receipt even if session not found
            return {"message": "Session not found, but webhook acknowledged"}
        
        # Get the user
        user = await db.get(User, verification.user_id)
        if not user:
            log.error(f"User not found for verification session: {session_id}")
            return {"message": "User not found, but webhook acknowledged"}

        # Update verification based on status
        if status == "Approved":
            verification.status = "completed"
            verification.completed_at = datetime.now(timezone.utc)
            
            # Extract data from decision
            extracted_data = decision.get("extracted_data", {})
            
            # Update verification record with details
            if "date_of_birth" in extracted_data:
                try:
                    dob = datetime.fromisoformat(extracted_data["date_of_birth"].replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - dob).days // 365
                    verification.verified_age = age
                except Exception as e:
                    log.warning(f"Failed to parse date_of_birth: {e}")
            
            if "document_type" in extracted_data:
                verification.document_type = extracted_data["document_type"]
            
            if "document_country" in extracted_data:
                verification.document_country = extracted_data["document_country"]
            
            # Store the full webhook payload
            verification.verification_result = json_body
            
            # Update user verification status
            user.is_identity_verified = True
            user.verified_at = datetime.now(timezone.utc)
            
            # Set age verification if age >= 18
            if verification.verified_age and verification.verified_age >= 18:
                user.is_age_verified = True
            
            # Set verification level based on workflow type
            if verification.workflow_type == "kyc":
                user.verification_level = "full"
            
            log.info(f"Webhook: Verification completed for user {user.id}")
            
        elif status in ["Declined", "Rejected"]:
            verification.status = "failed"
            verification.completed_at = datetime.now(timezone.utc)
            reasons = decision.get("reasons", [])
            verification.failure_reason = reasons[0].get("message") if reasons else "Verification declined"
            log.info(f"Webhook: Verification declined for user {user.id}")
            
        elif status in ["Expired", "Abandoned"]:
            verification.status = "expired"
            verification.completed_at = datetime.now(timezone.utc)
            verification.failure_reason = f"Session {status.lower()}"
            log.info(f"Webhook: Verification {status.lower()} for user {user.id}")
            
        elif status == "In Progress":
            verification.status = "in_progress"
            log.info(f"Webhook: Verification in progress for user {user.id}")
        
        elif status == "In Review":
            verification.status = "in_review"
            log.info(f"Webhook: Verification in review for user {user.id}")

        await db.commit()
        
        log.info(f"Webhook processed successfully for session {session_id}")
        return {"message": "Webhook processed successfully"}

    except Exception as e:
        log.error(f"Failed to process webhook: {str(e)}")
        await db.rollback()
        # Return 200 to prevent Didit from retrying if it's our internal error
        return {"message": "Webhook received but processing failed"}
