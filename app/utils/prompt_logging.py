"""
Backward compatibility shim for app.utils.prompt_logging imports.
This file maintains compatibility with existing imports like:
    from app.utils.prompt_logging import log_prompt

New code should use:
    from app.utils.logging.prompt_logging import log_prompt
"""

from .logging.prompt_logging import *  # noqa: F401, F403
