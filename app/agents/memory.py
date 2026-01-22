from app.api.utils import get_embedding, search_similar_memories, search_influencer_knowledge, upsert_memory
from sqlalchemy import select
from sqlalchemy.sql import func
from app.db.models import Memory

async def find_similar_memories(
    db,
    chat_id: str,
    message: str,
    influencer_id: str = None,
    top_k: int = 7,
    embedding: list[float] | None = None,
):
    """
    Find similar memories from both chat-specific and influencer knowledge base.
    
    Args:
        db: Database session
        chat_id: ID of the chat
        message: User message to find similar memories for
        influencer_id: ID of the influencer (optional, for knowledge base search)
        top_k: Number of memories to return
        embedding: Optional precomputed embedding for the message (reuse to avoid duplicate calls)
    
    Returns:
        Tuple of (chat_memories, knowledge_base_content) - both are lists of strings
    """
    emb = embedding or await get_embedding(message)
    
    chat_memories = await search_similar_memories(db, chat_id, emb, top_k=top_k)
    
    knowledge_chunks = []
    if influencer_id:
        try:
            knowledge_results = await search_influencer_knowledge(db, influencer_id, emb, top_k=5)
            knowledge_chunks = [r["content"] for r in knowledge_results if r.get("content")]
            import logging
            log = logging.getLogger("memory")
            log.info(f"Knowledge search for {influencer_id}: found {len(knowledge_chunks)} chunks")
        except Exception as e:
            import logging
            log = logging.getLogger("memory")
            log.error(f"Failed to search influencer knowledge for {influencer_id}: {e}", exc_info=True)
    
    return chat_memories, knowledge_chunks

def _norm(s: str) -> str:
    return " ".join(s.lower().split())

async def _already_have(db, chat_id: str, fact: str) -> bool:
    """Check if the normalized fact already exists for this chat_id."""
    norm_fact = _norm(fact)
    result = await db.execute(
        select(Memory)
        .where(Memory.chat_id == chat_id)
        .where(func.lower(Memory.content) == norm_fact)
    )
    return result.scalar_one_or_none() is not None


async def store_fact(db, chat_id: str, fact: str, sender: str = "user"):
    norm_fact = _norm(fact)
    if not norm_fact or norm_fact == "no new memories.":
        return

    if await _already_have(db, chat_id, norm_fact):
        return  

    try:
        emb = await get_embedding(norm_fact)
    except Exception as exc:
        import logging
        logging.getLogger("memory").error("get_embedding failed for fact=%r chat=%s err=%s", norm_fact, chat_id, exc, exc_info=True)
        return

    await upsert_memory(
        db=db,
        chat_id=chat_id,
        content=norm_fact,
        embedding=emb,
        sender=sender
    )
