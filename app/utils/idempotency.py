"""
Backward compatibility shim for app.utils.idempotency imports.
This file maintains compatibility with existing imports like:
    from app.utils.idempotency import idempotent

New code should use:
    from app.utils.infrastructure.idempotency import idempotent
"""

from .infrastructure.idempotency import *  # noqa: F401, F403
