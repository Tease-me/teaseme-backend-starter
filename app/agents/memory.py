from app.services.embeddings import get_embedding, get_embeddings_batch, search_similar_memories, search_similar_messages, upsert_memory
from sqlalchemy import select
from sqlalchemy.sql import func
from app.db.models import Memory
import logging

log = logging.getLogger(__name__)


async def find_similar_messages(
    db,
    chat_id: str,
    message: str,
    influencer_id: str = None,
    top_k: int = 10,
    embedding: list[float] | None = None,
    max_distance: float | None = None,
):
    """
    Find similar messages from chat history using semantic search.
    
    Args:
        db: Database session
        chat_id: ID of the chat
        message: User message to find similar messages for
        influencer_id: ID of the influencer (optional, for knowledge base search)
        top_k: Number of messages to return (default: 10)
        embedding: Optional precomputed embedding for the message (reuse to avoid duplicate calls)
        max_distance: Optional maximum cosine distance for relevance (default: None = no filtering)
    
    Returns:
        List of similar message content strings
    """
    emb = embedding or await get_embedding(message)
    
    chat_memories = await search_similar_messages(db, chat_id, emb, top_k=top_k, max_distance=max_distance)
    
    return chat_memories


async def find_similar_memories(
    db,
    chat_id: str,
    message: str,
    influencer_id: str = None,
    top_k: int = 10,
    embedding: list[float] | None = None,
    max_distance: float | None = None,
):
    """
    Find similar memories using semantic search with improved accuracy.
    
    Args:
        db: Database session
        chat_id: ID of the chat
        message: User message to search memories for
        influencer_id: ID of the influencer (optional, for future use)
        top_k: Number of memories to return (default: 10)
        embedding: Optional precomputed embedding for the message (reuse to avoid duplicate calls)
        max_distance: Optional maximum cosine distance for relevance (default: None = no filtering)
                     Lower = stricter matching. Recommended: 0.3-0.7 if filtering
    
    Returns:
        List of similar memory content strings
    """
    emb = embedding or await get_embedding(message)
    
    chat_memories = await search_similar_memories(db, chat_id, emb, top_k=top_k, max_distance=max_distance)

    return chat_memories


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
    """Store a single fact (legacy function for backward compatibility)."""
    norm_fact = _norm(fact)
    if not norm_fact or norm_fact == "no new memories.":
        return

    if await _already_have(db, chat_id, norm_fact):
        return  

    try:
        emb = await get_embedding(norm_fact)
    except Exception as exc:
        log.error("get_embedding failed for fact=%r chat=%s err=%s", norm_fact, chat_id, exc, exc_info=True)
        return

    await upsert_memory(
        db=db,
        chat_id=chat_id,
        content=norm_fact,
        embedding=emb,
        sender=sender
    )


async def store_facts_batch(
    db,
    chat_id: str,
    facts: list[str],
    sender: str = "user",
) -> int:
    """
    Store multiple facts using batch embedding (70-80% faster than sequential).
    
    Args:
        db: Database session
        chat_id: Chat ID to associate facts with
        facts: List of fact strings to store
        sender: Sender identifier
        
    Returns:
        Number of facts successfully stored
    """
    if not facts:
        return 0
    
    # 1. Normalize and deduplicate
    normalized = []
    for fact in facts:
        norm = _norm(fact)
        if norm and norm != "no new memories." and norm not in normalized:
            normalized.append(norm)
    
    if not normalized:
        return 0
    
    # 2. Filter out already-existing facts
    new_facts = []
    for norm in normalized:
        if not await _already_have(db, chat_id, norm):
            new_facts.append(norm)
    
    if not new_facts:
        log.debug("All %d facts already exist for chat=%s", len(normalized), chat_id)
        return 0
    
    # 3. Batch embed all new facts in ONE API call
    try:
        embeddings = await get_embeddings_batch(new_facts)
    except Exception as exc:
        log.error("Batch embedding failed for chat=%s: %s", chat_id, exc, exc_info=True)
        return 0
    
    # 4. Store all facts
    stored = 0
    for fact, emb in zip(new_facts, embeddings):
        if not emb:  # Skip failed embeddings
            continue
        try:
            await upsert_memory(
                db=db,
                chat_id=chat_id,
                content=fact,
                embedding=emb,
                sender=sender
            )
            stored += 1
        except Exception as exc:
            log.error("Failed to store fact=%r chat=%s: %s", fact, chat_id, exc)
    
    log.info("Stored %d/%d facts for chat=%s", stored, len(new_facts), chat_id)
    return stored

