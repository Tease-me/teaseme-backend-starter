"""
Relationship tracking system for managing user-influencer interactions.

This module provides a comprehensive relationship state machine that tracks:
- Trust, closeness, attraction, and safety dimensions
- Relationship stages (STRANGERS -> FRIENDS -> FLIRTING -> DATING -> GIRLFRIEND)
- Define-The-Relationship (DTR) progression
- Sentiment tracking and signal classification
- Inactivity decay and re-engagement triggers

Main entry point is `process_relationship_turn` in processor.py.
"""

from .processor import process_relationship_turn
from .repo import get_or_create_relationship, get_relationship_payload
from .engine import Signals, RelOut, update_relationship, compute_state
from .signals import classify_signals
from .dtr import plan_dtr_goal
from .inactivity import apply_inactivity_decay, check_and_trigger_reengagement

__all__ = [
    # Main functions
    "process_relationship_turn",
    "get_or_create_relationship",
    "get_relationship_payload",
    
    # Core engine
    "Signals",
    "RelOut",
    "update_relationship",
    "compute_state",
    
    # Supporting functions
    "classify_signals",
    "plan_dtr_goal",
    "apply_inactivity_decay",
    "check_and_trigger_reengagement",
]
