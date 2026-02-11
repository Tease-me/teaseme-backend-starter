"""
Backward compatibility shim for app.utils.redis_pool imports.
This file maintains compatibility with existing imports like:
    from app.utils.redis_pool import get_redis

New code should use:
    from app.utils.infrastructure.redis_pool import get_redis
"""

from .infrastructure.redis_pool import *  # noqa: F401, F403
