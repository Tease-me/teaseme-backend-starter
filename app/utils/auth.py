"""
Backward compatibility shim for app.utils.auth imports.
This file maintains compatibility with existing imports like:
    from app.utils.auth import create_token

New code should use:
    from app.utils.auth.tokens import create_token
"""

from .auth.tokens import *  # noqa: F401, F403
