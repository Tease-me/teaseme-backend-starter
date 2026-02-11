"""
Backward compatibility shim for app.utils.email imports.
This file maintains compatibility with existing imports like:
    from app.utils.email import send_verification_email

New code should use:
    from app.utils.messaging.email import send_verification_email
"""

from .messaging.email import *  # noqa: F401, F403
