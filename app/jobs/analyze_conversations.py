"""
Background job that analyzes stored conversations and extracts learnings.
"""
import asyncio
import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.db.models import ConversationAnalysis

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("teaseme-analyzer")


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
    
    # Mark as analyzed (simple version - you can add LLM analysis here later)
    for conv in conversations:
        conv.analyzed_at = datetime.now(timezone.utc)
        # TODO: Add LLM-based quality scoring here
        conv.overall_score = 5  # Placeholder
    
    await db.commit()
    log.info(f"[ANALYZER] Analyzed {len(conversations)} conversations")
    
    return len(conversations)


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
