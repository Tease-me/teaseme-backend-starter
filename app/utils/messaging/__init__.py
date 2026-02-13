"""Messaging utilities (chat, email, push notifications, TTS)."""

from .chat import (
    transcribe_audio,
    get_ai_reply_via_websocket,
    # synthesize_audio_with_elevenlabs,
    format_for_eleven_v3,
    synthesize_audio_with_elevenlabs_V3,
    pcm_bytes_to_wav_bytes,
)
from .email import (
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
from .push import send_push, send_push_rich
from .tts_sanitizer import sanitize_tts_text

__all__ = [
    # Chat
    "transcribe_audio",
    "get_ai_reply_via_websocket",
    # "synthesize_audio_with_elevenlabs",
    "format_for_eleven_v3",
    "synthesize_audio_with_elevenlabs_V3",
    "pcm_bytes_to_wav_bytes",
    # Email
    "send_verification_email",
    "send_profile_survey_email",
    "send_email_via_ses",
    "send_password_reset_email",
    "send_new_influencer_email",
    "send_new_influencer_email_with_picture",
    "send_influencer_survey_completed_email_to_promoter",
    "image_data_url",
    "compose_email_header_image_url",
    # Push
    "send_push",
    "send_push_rich",
    # TTS
    "sanitize_tts_text",
]
