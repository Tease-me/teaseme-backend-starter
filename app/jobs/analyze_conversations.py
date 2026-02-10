"""
Background job that analyzes stored conversations and extracts learnings.
"""
import asyncio
import argparse
import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_openai import ChatOpenAI

from app.db.session import SessionLocal
from app.db.models import ConversationAnalysis, ConversationLearning
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("teaseme-analyzer")

# Initialize LLM for quality analysis
ANALYZER_LLM = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    api_key=settings.OPENAI_API_KEY,
)

QUALITY_ANALYSIS_PROMPT = """You are analyzing a conversation between an AI character and a user to assess quality and extract learnings.

**Conversation Context:**
Relationship Stage: {relationship_state}
Mood: {mood_at_turn}

**AI Response:**
"{ai_response}"

**User's Next Message (their reaction):**
"{user_next_message}"

**Reply Time:** {seconds_to_reply} seconds

**Pre-detected Issues:** {detected_issues}

Analyze this interaction and provide scores (1-10) and insights:

1. **Engagement Score** (1-10): Did the AI's response encourage continued conversation?
2. **Interest Score** (1-10): Did the user seem interested based on their reply?
3. **Initiative Score** (1-10): Did the AI show personality and initiative vs being passive?
4. **Appropriateness Score** (1-10): Was the response appropriate for the relationship stage?
5. **Overall Score** (1-10): Overall quality of this interaction

**What Worked:** (1-2 sentences on what the AI did well)
**What Failed:** (1-2 sentences on what could be improved, or "Nothing major" if good)
**Suggested Improvement:** (Specific actionable advice)
**User Reaction Type:** (Choose ONE: "highly_engaged", "engaged", "neutral", "short_reply", "negative")

**Response Format (JSON):**
{{
  "engagement_score": <1-10>,
  "interest_score": <1-10>,
  "initiative_score": <1-10>,
  "appropriateness_score": <1-10>,
  "overall_score": <1-10>,
  "what_worked": "<text>",
  "what_failed": "<text>",
  "suggested_improvement": "<text>",
  "user_reaction_type": "<type>"
}}"""


async def analyze_with_llm(conv: ConversationAnalysis) -> Optional[dict]:
    """
    Use LLM to analyze conversation quality and return scores + insights.
    """
    try:
        prompt = QUALITY_ANALYSIS_PROMPT.format(
            relationship_state=conv.relationship_state,
            mood_at_turn=conv.mood_at_turn or "N/A",
            ai_response=conv.ai_response,
            user_next_message=conv.user_next_message or "No reply yet",
            seconds_to_reply=round(conv.seconds_to_reply, 1) if conv.seconds_to_reply else "N/A",
            detected_issues=", ".join(conv.detected_issues) if conv.detected_issues else "None",
        )
        
        response = await ANALYZER_LLM.ainvoke(prompt)
        result_text = response.content.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group(1)
        
        result = json.loads(result_text)
        return result
        
    except Exception as e:
        log.error(f"[ANALYZER] LLM analysis failed for {conv.id}: {e}")
        return None


async def extract_learnings(
    db: AsyncSession,
    conv: ConversationAnalysis,
    analysis: dict,
) -> None:
    """
    Extract learnings from analyzed conversation and store them.
    """
    try:
        influencer_id = conv.influencer_id
        stage = conv.relationship_state
        
        # Extract "avoid" patterns from low-scoring conversations
        if analysis.get("overall_score", 5) < 4 and analysis.get("what_failed"):
            learning_id = str(uuid4())
            learning = ConversationLearning(
                id=learning_id,
                influencer_id=influencer_id,
                stage=stage,
                pattern_type="avoid",
                pattern_description=analysis["what_failed"],
                example_user_message=conv.user_message,
                example_ai_response=conv.ai_response,
                user_reaction=analysis.get("user_reaction_type"),
                confidence=max(0.3, (10 - analysis.get("overall_score", 5)) / 10),
                times_seen=1,
                success_rate=0.0,
            )
            db.add(learning)
            log.info(f"[ANALYZER] Added AVOID learning for {influencer_id} at {stage}")
        
        # Extract "repeat" patterns from high-scoring conversations
        if analysis.get("overall_score", 5) >= 7 and analysis.get("what_worked"):
            learning_id = str(uuid4())
            learning = ConversationLearning(
                id=learning_id,
                influencer_id=influencer_id,
                stage=stage,
                pattern_type="repeat",
                pattern_description=analysis["what_worked"],
                example_user_message=conv.user_message,
                example_ai_response=conv.ai_response,
                user_reaction=analysis.get("user_reaction_type"),
                confidence=min(0.9, analysis.get("overall_score", 5) / 10),
                times_seen=1,
                success_rate=1.0,
            )
            db.add(learning)
            log.info(f"[ANALYZER] Added REPEAT learning for {influencer_id} at {stage}")
        
    except Exception as e:
        log.error(f"[ANALYZER] Failed to extract learnings: {e}")


async def analyze_batch(db: AsyncSession, batch_size: int = 50) -> int:
    """
    Analyze a batch of unanalyzed conversations.
    Returns number of conversations analyzed.
    """
    # Get unanalyzed conversations
    result = await db.execute(
        select(ConversationAnalysis)
        .where(ConversationAnalysis.analyzed_at == None)
        .where(ConversationAnalysis.user_next_message != None)  # Need user response
        .order_by(ConversationAnalysis.ai_response_timestamp)
        .limit(batch_size)
    )
    conversations = result.scalars().all()
    
    if not conversations:
        return 0
    
    log.info(f"[ANALYZER] Found {len(conversations)} conversations to analyze")
    
    analyzed_count = 0
    for conv in conversations:
        try:
            # Use LLM to analyze conversation quality
            analysis = await analyze_with_llm(conv)
            
            if analysis:
                # Store scores from LLM analysis
                conv.engagement_score = analysis.get("engagement_score")
                conv.interest_score = analysis.get("interest_score")
                conv.initiative_score = analysis.get("initiative_score")
                conv.appropriateness_score = analysis.get("appropriateness_score")
                conv.overall_score = analysis.get("overall_score")
                conv.what_worked = analysis.get("what_worked")
                conv.what_failed = analysis.get("what_failed")
                conv.suggested_improvement = analysis.get("suggested_improvement")
                conv.user_reaction_type = analysis.get("user_reaction_type")
                conv.analyzed_at = datetime.now(timezone.utc)
                
                # Extract learnings from this conversation
                await extract_learnings(db, conv, analysis)
                
                analyzed_count += 1
                log.info(f"[ANALYZER] Analyzed {conv.id}: score={conv.overall_score}/10")
            else:
                # Mark as analyzed even if LLM failed (avoid retrying forever)
                conv.analyzed_at = datetime.now(timezone.utc)
                conv.overall_score = 5  # Neutral score for failed analysis
                
        except Exception as e:
            log.error(f"[ANALYZER] Error analyzing {conv.id}: {e}")
            # Mark as analyzed to avoid infinite retries
            conv.analyzed_at = datetime.now(timezone.utc)
    
    await db.commit()
    log.info(f"[ANALYZER] Successfully analyzed {analyzed_count}/{len(conversations)} conversations")
    
    return analyzed_count


async def run_continuous(batch_size: int, interval: int):
    """
    Run analyzer continuously with specified interval.
    """
    log.info(f"[ANALYZER] Starting continuous mode: batch_size={batch_size}, interval={interval}s")
    
    while True:
        try:
            async with SessionLocal() as db:
                count = await analyze_batch(db, batch_size)
                if count > 0:
                    log.info(f"[ANALYZER] Processed {count} conversations")
                else:
                    log.debug("[ANALYZER] No conversations to process")
        except Exception as e:
            log.error(f"[ANALYZER] Error in analysis loop: {e}", exc_info=True)
        
        await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Conversation analyzer")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds")
    
    args = parser.parse_args()
    
    if args.continuous:
        asyncio.run(run_continuous(args.batch_size, args.interval))
    else:
        async def run_once():
            async with SessionLocal() as db:
                await analyze_batch(db, args.batch_size)
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
