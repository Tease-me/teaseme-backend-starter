"""Central registry for all system prompts."""

from . import base, adult, relationship, moderation

# Combine all prompts from different modules
ALL_PROMPTS = {}
ALL_PROMPTS.update(base.PROMPTS)
ALL_PROMPTS.update(adult.PROMPTS)
ALL_PROMPTS.update(relationship.PROMPTS)
ALL_PROMPTS.update(moderation.PROMPTS)


def get_all_prompts():
    """Get all prompts for seeding database."""
    return ALL_PROMPTS


def get_prompt_by_key(key: str):
    """Get a specific prompt by key."""
    return ALL_PROMPTS.get(key)
