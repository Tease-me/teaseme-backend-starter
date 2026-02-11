"""
Backward compatibility shim for app.utils.rate_limiter imports.
This file maintains compatibility with existing imports like:
    from app.utils.rate_limiter import check_rate_limit

New code should use:
    from app.utils.infrastructure.rate_limiter import check_rate_limit
"""

from .infrastructure.rate_limiter import *  # noqa: F401, F403
