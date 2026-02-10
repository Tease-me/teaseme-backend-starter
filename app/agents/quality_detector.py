"""
Quality detection and conversation analysis.
Detects bad patterns quickly and stores conversations for deeper LLM analysis.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationAnalysis
from app.db.session import SessionLocal

log = logging.getLogger("teaseme-quality")

# Quick pattern detection (no LLM needed)
BAD_PATTERNS = {
    "assistant_behavior": [
        r"how can i (?:help|assist)",
        r"is there anything (?:else )?i can (?:help|do)",
        r"(?:can|may) i (?:help|assist) you",
        r"what (?:can|would) you like",
        r"here'?s what i can do",
    ],
    "menu_options": [
        r"\d+\.\s+\w+",  # numbered lists
        r"(?:option|choice) \d+",
        r"select an option",
    ],
    "em_dashes": [
        r"—",  # em dash
    ],
    "repetitive_name_asking": [
        r"(?:what'?s|tell me) your name",
        r"i (?:don'?t|dont) (?:know|remember) your name",
    ],
}


def quick_detect_bad_patterns(text: str) -> list[str]:
    """
    Fast, regex-based detection of bad conversational patterns.
    Returns list of detected issue types.
    """
    detected = []
    text_lower = text.lower()
    
    for issue_type, patterns in BAD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                detected.append(issue_type)
                break  # One match per issue type is enough
    
    return detected


async def store_conversation_analysis(
    chat_id: str,
    influencer_id: str,
    user_id: int,
    user_message: str,
    ai_response: str,
    relationship_state: str,
    mood_at_turn: Optional[str] = None,
    memories_at_turn: Optional[str] = None,
    detected_issues: Optional[list[str]] = None,
) -> str:
    """
    Store a conversation turn for later LLM analysis.
    Returns the analysis ID.
    """
    async with SessionLocal() as db:
        analysis_id = str(uuid4())
        
        analysis = ConversationAnalysis(
            id=analysis_id,
            chat_id=chat_id,
            influencer_id=influencer_id,
            user_id=user_id,
            user_message=user_message,
            ai_response=ai_response,
            relationship_state=relationship_state,
            mood_at_turn=mood_at_turn,
            memories_at_turn=memories_at_turn,
            detected_issues=detected_issues or [],
            ai_response_timestamp=datetime.now(timezone.utc),
        )
        
        db.add(analysis)
        await db.commit()
        
        log.info(f"[QUALITY] Stored analysis {analysis_id} for chat {chat_id}")
        return analysis_id


async def update_with_user_response(
    db: AsyncSession,
    chat_id: str,
    ai_response_text: str,
    user_next_message: str,
) -> None:
    """
    Update the most recent analysis with the user's response.
    This helps us measure engagement.
    """
    try:
        result = await db.execute(
            select(ConversationAnalysis)
            .where(
                ConversationAnalysis.chat_id == chat_id,
                ConversationAnalysis.ai_response == ai_response_text,
                ConversationAnalysis.user_next_message == None,
            )
            .order_by(ConversationAnalysis.ai_response_timestamp.desc())
            .limit(1)
        )
        analysis = result.scalar_one_or_none()
        
        if analysis:
            analysis.user_next_message = user_next_message
            analysis.user_next_message_timestamp = datetime.now(timezone.utc)
            
            # Calculate response time
            if analysis.ai_response_timestamp:
                delta = analysis.user_next_message_timestamp - analysis.ai_response_timestamp
                analysis.seconds_to_reply = delta.total_seconds()
            
            await db.commit()
            log.info(f"[QUALITY] Updated analysis {analysis.id} with user response")
    except Exception as e:
        log.error(f"[QUALITY] Failed to update analysis: {e}")
