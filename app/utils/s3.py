"""
Backward compatibility shim for app.utils.s3 imports.
This file maintains compatibility with existing imports like:
    from app.utils.s3 import save_audio_to_s3

New code should use:
    from app.utils.storage.s3 import save_audio_to_s3
"""

from .storage.s3 import *  # noqa: F401, F403
