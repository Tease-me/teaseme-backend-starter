"""
Backward compatibility shim for app.utils.tts_sanitizer imports.
This file maintains compatibility with existing imports like:
    from app.utils.tts_sanitizer import sanitize_tts_text

New code should use:
    from app.utils.messaging.tts_sanitizer import sanitize_tts_text
"""

from .messaging.tts_sanitizer import *  # noqa: F401, F403
