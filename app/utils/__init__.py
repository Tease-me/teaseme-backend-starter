"""
Utility functions and helpers.

All utilities are organized by domain for better maintainability:
- auth: Authentication (tokens, dependencies)
- messaging: Communication (chat, email, push, TTS)
- storage: File storage (AWS S3)
- infrastructure: System utilities (concurrency, rate limiting, Redis, idempotency)
- logging: Logging utilities

For backward compatibility, all functions are re-exported at the top level.
You can import from either:
    from app.utils.auth import create_token  # Old way (still works)
    from app.utils import create_token       # Also works
"""

# Re-export everything for backward compatibility
# This ensures existing imports like "from app.utils.auth import X" still work

# Auth utilities
from .auth.tokens import create_token
from .auth.dependencies import get_current_user, require_age_verification, oauth2_scheme

# Messaging utilities
from .messaging.chat import (
    transcribe_audio,
    get_ai_reply_via_websocket,
    synthesize_audio_with_elevenlabs,
    format_for_eleven_v3,
    synthesize_audio_with_elevenlabs_V3,
    pcm_bytes_to_wav_bytes,
)
from .messaging.email import (
    send_verification_email,
    send_profile_survey_email,
    send_email_via_ses,
    send_password_reset_email,
    send_new_influencer_email,
    send_new_influencer_email_with_picture,
    send_influencer_survey_completed_email_to_promoter,
    image_data_url,
    compose_email_header_image_url,
)
from .messaging.push import send_push, send_push_rich
from .messaging.tts_sanitizer import sanitize_tts_text

# Storage utilities  
from .storage.s3 import (
    save_audio_to_s3,
    save_ia_audio_to_s3,
    generate_presigned_url,
    message_to_schema_with_presigned,
    message18_to_schema_with_presigned,
    save_knowledge_file_to_s3,
    delete_file_from_s3,
    save_influencer_audio_to_s3,
    save_influencer_ia_audio_to_s3,
    get_s3_object_bytes,
    save_sample_audio_to_s3,
    get_influencer_audio_download_url,
    list_influencer_audio_keys,
    generate_presigned_urls_for_keys,
    save_influencer_photo_to_s3,
    save_influencer_video_to_s3,
    save_influencer_profile_to_s3,
    get_influencer_profile_from_s3,
    save_user_photo_to_s3,
    generate_user_presigned_url,
)

# Infrastructure utilities
from .infrastructure.concurrency import AdvisoryLock, advisory_lock, with_lock
from .infrastructure.idempotency import IdempotencyLock, idempotent
from .infrastructure.rate_limiter import check_rate_limit, rate_limit, get_user_key
from .infrastructure.redis_pool import get_redis, close_redis

# Logging utilities
from .logging.prompt_logging import log_prompt

__all__ = [
    # Auth
    "create_token",
    "get_current_user",
    "require_age_verification",
    "oauth2_scheme",
    # Messaging - Chat
    "transcribe_audio",
    "get_ai_reply_via_websocket",
    "synthesize_audio_with_elevenlabs",
    "format_for_eleven_v3",
    "synthesize_audio_with_elevenlabs_V3",
    "pcm_bytes_to_wav_bytes",
    # Messaging - Email
    "send_verification_email",
    "send_profile_survey_email",
    "send_email_via_ses",
    "send_password_reset_email",
    "send_new_influencer_email",
    "send_new_influencer_email_with_picture",
    "send_influencer_survey_completed_email_to_promoter",
    "image_data_url",
    "compose_email_header_image_url",
    # Messaging - Push
    "send_push",
    "send_push_rich",
    # Messaging - TTS
    "sanitize_tts_text",
    # Storage
    "save_audio_to_s3",
    "save_ia_audio_to_s3",
    "generate_presigned_url",
    "message_to_schema_with_presigned",
    "message18_to_schema_with_presigned",
    "save_knowledge_file_to_s3",
    "delete_file_from_s3",
    "save_influencer_audio_to_s3",
    "save_influencer_ia_audio_to_s3",
    "get_s3_object_bytes",
    "save_sample_audio_to_s3",
    "get_influencer_audio_download_url",
    "list_influencer_audio_keys",
    "generate_presigned_urls_for_keys",
    "save_influencer_photo_to_s3",
    "save_influencer_video_to_s3",
    "save_influencer_profile_to_s3",
    "get_influencer_profile_from_s3",
    "save_user_photo_to_s3",
    "generate_user_presigned_url",
    # Infrastructure
    "AdvisoryLock",
    "advisory_lock",
    "with_lock",
    "IdempotencyLock",
    "idempotent",
    "check_rate_limit",
    "rate_limit",
    "get_user_key",
    "get_redis",
    "close_redis",
    # Logging
    "log_prompt",
]
