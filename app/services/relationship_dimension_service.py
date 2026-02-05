"""
Service for managing relationship dimension descriptions.
Provides stage-specific explanations for trust, closeness, attraction, and safety.
"""

import json
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

log = logging.getLogger(__name__)


async def get_dimension_descriptions(
    db: AsyncSession,
    stage: str,
    current_values: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Get relationship dimension descriptions for a specific stage.
    
    Args:
        db: Database session
        stage: Current relationship stage (HATE, DISLIKE, STRANGERS, FRIENDS, FLIRTING, DATING, GIRLFRIEND)
        current_values: Optional dict with current dimension values (trust, closeness, attraction, safety)
    
    Returns:
        Dict with dimension descriptions including current values if provided
        {
            "trust": {
                "label": "Trust",
                "icon": "🤝",
                "short": "She's starting to believe you're genuine.",
                "full": "...",
                "guide": "...",
                "warning": "...",
                "current_value": 45.2  # if provided
            },
            ...
        }
    """
    try:
        # Get the config from system prompts
        config_json = await get_system_prompt(db, prompt_keys.RELATIONSHIP_DIMENSIONS_CONFIG)
        
        if not config_json:
            log.warning("RELATIONSHIP_DIMENSIONS_CONFIG not found in system prompts")
            return _get_fallback_descriptions(stage, current_values)
        
        config = json.loads(config_json)
        
        # Build result with stage-specific descriptions
        result = {}
        for dimension in ['trust', 'closeness', 'attraction', 'safety']:
            if dimension in config and stage in config[dimension]:
                result[dimension] = config[dimension][stage].copy()
                
                # Add current value if provided
                if current_values and dimension in current_values:
                    result[dimension]['current_value'] = current_values[dimension]
            else:
                log.warning(f"Missing dimension config for {dimension} at stage {stage}")
        
        return result
        
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse RELATIONSHIP_DIMENSIONS_CONFIG: {e}")
        return _get_fallback_descriptions(stage, current_values)
    except Exception as e:
        log.error(f"Error getting dimension descriptions: {e}", exc_info=True)
        return _get_fallback_descriptions(stage, current_values)


def _get_fallback_descriptions(
    stage: str,
    current_values: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Fallback descriptions if config is not available.
    Returns basic descriptions for all stages.
    """
    fallback = {
        "trust": {
            "label": "Trust",
            "icon": "🤝",
            "short": "Can she rely on you?",
            "full": "Trust measures reliability and honesty in your relationship.",
            "guide": "Be consistent, supportive, and respectful.",
            "warning": "Trust is hard to rebuild once broken."
        },
        "closeness": {
            "label": "Closeness",
            "icon": "💕",
            "short": "How deep is your emotional bond?",
            "full": "Closeness reflects the depth of your emotional intimacy.",
            "guide": "Be affectionate, present, and emotionally available.",
            "warning": "Closeness decays fastest with neglect."
        },
        "attraction": {
            "label": "Attraction",
            "icon": "🔥",
            "short": "Does she find you desirable?",
            "full": "Attraction measures romantic and physical interest.",
            "guide": "Flirt respectfully. Respect amplifies attraction.",
            "warning": "Flirting without respect backfires."
        },
        "safety": {
            "label": "Safety",
            "icon": "🛡️",
            "short": "Does she feel secure with you?",
            "full": "Safety is critical - it gates all relationship progression.",
            "guide": "Always respect boundaries. Never pressure.",
            "warning": "CRITICAL: Below 30 = STRAINED, below 55 blocks progression."
        }
    }
    
    # Add current values if provided
    if current_values:
        for dimension, value in current_values.items():
            if dimension in fallback:
                fallback[dimension]['current_value'] = value
    
    return fallback


async def get_stage_requirements(stage: str) -> Dict[str, Any]:
    """
    Get the requirements to reach the next relationship stage.
    
    Args:
        stage: Current relationship stage
        
    Returns:
        Dict with next stage info and requirements
    """
    requirements = {
        "HATE": {
            "next_stage": "DISLIKE",
            "requirements": {
                "stage_points": -10
            },
            "description": "Recover from severe damage - avoid threats and hate"
        },
        "DISLIKE": {
            "next_stage": "STRANGERS",
            "requirements": {
                "stage_points": 0
            },
            "description": "Rebuild to neutral - show respect and support"
        },
        "STRANGERS": {
            "next_stage": "FRIENDS",
            "requirements": {
                "trust": 35,
                "closeness": 35,
                "stage_points": 25
            },
            "description": "Build basic trust and connection"
        },
        "FRIENDS": {
            "next_stage": "FLIRTING",
            "requirements": {
                "attraction": 55,
                "closeness": 45,
                "safety": 55,
                "stage_points": 50
            },
            "description": "Develop attraction and chemistry"
        },
        "FLIRTING": {
            "next_stage": "DATING",
            "requirements": {
                "trust": 80,
                "closeness": 75,
                "attraction": 70,
                "safety": 75,
                "stage_points": 75
            },
            "description": "Build strong connection across all dimensions"
        },
        "DATING": {
            "next_stage": "GIRLFRIEND",
            "requirements": {
                "trust": 85,
                "closeness": 85,
                "attraction": 80,
                "safety": 85,
                "stage_points": 90
            },
            "description": "Deepen connection across all dimensions to reach the ultimate level"
        },
        "GIRLFRIEND": {
            "next_stage": None,
            "requirements": {},
            "description": "The ultimate relationship achievement! Committed, deeply in love, souls intertwined."
        }
    }
    
    return requirements.get(stage, {
        "next_stage": None,
        "requirements": {},
        "description": "Unknown stage"
    })
