"""
Learning manager - stores and retrieves conversation learnings.
"""
import logging
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationLearning

log = logging.getLogger("teaseme-learning")


async def get_learning_summary_for_prompt(
    db: AsyncSession,
    influencer_id: str,
    stage: str,
) -> str:
    """
    Get a summary of learnings to inject into the prompt.
    Returns formatted string with things to avoid and repeat.
    """
    try:
        # Get high-confidence learnings
        result = await db.execute(
            select(ConversationLearning)
            .where(
                and_(
                    ConversationLearning.influencer_id == influencer_id,
                    ConversationLearning.stage == stage,
                    ConversationLearning.confidence >= 0.6,
                )
            )
            .order_by(ConversationLearning.confidence.desc())
            .limit(10)
        )
        learnings = result.scalars().all()
        
        if not learnings:
            return ""
        
        avoid = []
        repeat = []
        
        for learning in learnings:
            if learning.pattern_type == "avoid":
                avoid.append(f"- {learning.pattern_description}")
            elif learning.pattern_type == "repeat":
                repeat.append(f"- {learning.pattern_description}")
        
        summary_parts = []
        
        if avoid:
            summary_parts.append("❌ AVOID:\n" + "\n".join(avoid[:5]))
        
        if repeat:
            summary_parts.append("✅ DO MORE:\n" + "\n".join(repeat[:5]))
        
        if summary_parts:
            return "\n\n🧠 LEARNINGS FOR THIS STAGE:\n" + "\n\n".join(summary_parts)
        
        return ""
        
    except Exception as e:
        log.error(f"[LEARNING] Failed to get learning summary: {e}")
        return ""
