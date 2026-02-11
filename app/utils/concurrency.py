"""
Backward compatibility shim for app.utils.concurrency imports.
This file maintains compatibility with existing imports like:
    from app.utils.concurrency import advisory_lock

New code should use:
    from app.utils.infrastructure.concurrency import advisory_lock
"""

from .infrastructure.concurrency import *  # noqa: F401, F403
