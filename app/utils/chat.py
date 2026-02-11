"""
Backward compatibility shim for app.utils.chat imports.
This file maintains compatibility with existing imports like:
    from app.utils.chat import transcribe_audio

New code should use:
    from app.utils.messaging.chat import transcribe_audio
"""

from .messaging.chat import *  # noqa: F401, F403
