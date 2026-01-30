"""
Didit Identity Verification Service

This service handles all interactions with the Didit API for:
- KYC (Know Your Customer) verification
- Age verification
- Biometric authentication
- Document verification

Documentation: https://docs.didit.me/
"""
import logging
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.core.config import settings

log = logging.getLogger(__name__)


class DiditService:
    """
    Service for interacting with Didit Identity Verification API v3.
    Uses simple API key authentication via x-api-key header.
    """

    def __init__(self):
        # v3 API base URL
        self.base_url = "https://verification.didit.me/v3"
        self.api_key = settings.DIDIT_API_KEY
        self.timeout = 30.0

    def _get_headers(self) -> Dict[str, str]:
        """Generate authentication headers for Didit v3 API requests."""
        if not self.api_key:
            raise ValueError("DIDIT_API_KEY is not configured")
        
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_verification_session(
        self,
        user_id: int,
        workflow_type: str = "kyc",
        redirect_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new verification session with Didit v3 API.
        Both workflow_id and redirect_url are automatically pulled from environment if not provided.

        Args:
            user_id: Internal user ID (used as vendor_data)
            workflow_type: Type of verification (currently only "kyc" is supported)
            redirect_url: URL to redirect user after completion (uses DIDIT_REDIRECT_URL from env if not provided)
            metadata: Additional metadata to attach to the session

        Returns:
            Dict containing session_id, url, and other session data

        Raises:
            httpx.HTTPError: If the API request fails
            ValueError: If workflow_id is not configured
        """
        # Get workflow_id from environment
        if workflow_type == "kyc":
            workflow_id = settings.DIDIT_WORKFLOW_ID_KYC
        else:
            raise ValueError(f"Invalid workflow_type: {workflow_type}. Currently only 'kyc' is supported")

        if not workflow_id:
            raise ValueError("DIDIT_WORKFLOW_ID_KYC is not configured in environment variables")

        # Use redirect_url from environment if not provided
        callback_url = redirect_url or settings.DIDIT_REDIRECT_URL

        # v3 API payload format
        payload = {
            "workflow_id": workflow_id,
            "vendor_data": str(user_id),  # Unique identifier for the user
        }

        if callback_url:
            payload["callback"] = callback_url
            payload["callback_method"] = "both"  # Redirect on either device

        if metadata:
            payload["metadata"] = metadata

        log.info(f"Creating Didit v3 verification session for user {user_id}, type={workflow_type}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = self._get_headers()
                response = await client.post(
                    f"{self.base_url}/session/",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                
                log.info(f"Didit v3 session created: {data.get('session_id')} for user {user_id}")
                return data

            except httpx.HTTPStatusError as e:
                log.error(f"Didit v3 API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"Failed to create Didit v3 session: {str(e)}")
                raise

    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        Retrieve the current status of a verification session (v3 API).

        Args:
            session_id: The Didit session ID

        Returns:
            Dict containing session status and verification results
        """
        log.info(f"Fetching Didit v3 session status: {session_id}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = self._get_headers()
                response = await client.get(
                    f"{self.base_url}/session/{session_id}/decision/",
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                log.error(f"Didit v3 API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"Failed to get Didit v3 session status: {str(e)}")
                raise

    async def get_verification_result(self, session_id: str) -> Dict[str, Any]:
        """
        Get detailed verification results for a completed session (v3 API).
        This is the same as get_session_status in v3 API.

        Args:
            session_id: The Didit session ID

        Returns:
            Dict containing verification results, document data, risk scores, etc.
        """
        log.info(f"Fetching Didit v3 verification result: {session_id}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = self._get_headers()
                response = await client.get(
                    f"{self.base_url}/session/{session_id}/decision/",
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                log.error(f"Didit v3 API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"Failed to get Didit v3 verification result: {str(e)}")
                raise

    def parse_verification_result(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and extract relevant information from Didit verification results.

        Args:
            result_data: Raw result data from Didit API

        Returns:
            Parsed and normalized verification data
        """
        parsed = {
            "verified": False,
            "verification_level": None,
            "age": None,
            "document_type": None,
            "document_country": None,
            "risk_score": None,
            "aml_checked": False,
            "biometric_passed": False,
            "liveness_passed": False,
        }

        # Extract verification status
        status = result_data.get("status", "").lower()
        parsed["verified"] = status in ["verified", "approved", "completed"]

        # Extract document information
        if "document" in result_data:
            doc = result_data["document"]
            parsed["document_type"] = doc.get("type")
            parsed["document_country"] = doc.get("country")
            
            # Extract age if available
            if "date_of_birth" in doc:
                dob_str = doc["date_of_birth"]
                try:
                    dob = datetime.strptime(dob_str, "%Y-%m-%d")
                    age = (datetime.now() - dob).days // 365
                    parsed["age"] = age
                except Exception as e:
                    log.warning(f"Failed to parse date_of_birth: {e}")

        # Extract age estimation if available
        if "age_estimation" in result_data:
            parsed["age"] = result_data["age_estimation"].get("estimated_age")

        # Extract risk and compliance
        if "risk_assessment" in result_data:
            risk = result_data["risk_assessment"]
            parsed["risk_score"] = risk.get("score")

        if "aml_screening" in result_data:
            parsed["aml_checked"] = True
            parsed["aml_result"] = result_data["aml_screening"]

        # Extract biometric checks
        if "biometric" in result_data:
            bio = result_data["biometric"]
            parsed["biometric_passed"] = bio.get("face_match", {}).get("passed", False)
            parsed["liveness_passed"] = bio.get("liveness", {}).get("passed", False)

        # Determine verification level
        if parsed["verified"]:
            if parsed["aml_checked"] and parsed["biometric_passed"]:
                parsed["verification_level"] = "premium"
            elif parsed["document_type"]:
                parsed["verification_level"] = "full"
            else:
                parsed["verification_level"] = "basic"

        return parsed


# Singleton instance
didit_service = DiditService()
