"""
Backward compatibility shim for app.utils.deps imports.
This file maintains compatibility with existing imports like:
    from app.utils.deps import get_current_user

New code should use:
    from app.utils.auth.dependencies import get_current_user
"""

from .auth.dependencies import *  # noqa: F401, F403
