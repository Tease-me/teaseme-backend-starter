"""
Backward compatibility shim for app.utils.push imports.
This file maintains compatibility with existing imports like:
    from app.utils.push import send_push

New code should use:
    from app.utils.messaging.push import send_push
"""

from .messaging.push import *  # noqa: F401, F403
