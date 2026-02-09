from app.api.utils import get_embedding, get_embeddings_batch, search_similar_memories, search_similar_messages, upsert_memory
from sqlalchemy import select
from sqlalchemy.sql import func
from app.db.models import Memory
import logging

log = logging.getLogger("memory")


async def find_similar_messages(
    db,
    chat_id: str,
    message: str,
    influencer_id: str = None,
    top_k: int = 7,
    embedding: list[float] | None = None,
):
    """
    Find similar messages from both chat-specific and influencer knowledge base.
    
    Args:
        db: Database session
        chat_id: ID of the chat
        message: User message to find similar messages for
        influencer_id: ID of the influencer (optional, for knowledge base search)
        top_k: Number of messages to return
        embedding: Optional precomputed embedding for the message (reuse to avoid duplicate calls)
    
    Returns:
        Tuple of (chat_memories, knowledge_base_content) - both are lists of strings
    """
    emb = embedding or await get_embedding(message)
    
    chat_memories = await search_similar_messages(db, chat_id, emb, top_k=top_k)
    
    return chat_memories

async def find_similar_memories(
    db,
    chat_id: str,
    message: str,
    influencer_id: str = None,
    top_k: int = 7,
    embedding: list[float] | None = None,
):
    emb = embedding or await get_embedding(message)
    
    chat_memories = await search_similar_memories(db, chat_id, emb, top_k=top_k)

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


async def get_recent_facts(db, chat_id: str, limit: int = 15) -> list[str]:
    """Return the most recent facts for a chat, newest first."""
    result = await db.execute(
        select(Memory.content)
        .where(Memory.chat_id == chat_id)
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    return [row[0] for row in result.fetchall()]


async def store_facts_batch(
    db, chat_id: str, facts: list[str], sender: str = "user"
) -> int:
    """
    Store multiple facts in batch using a single embedding API call.
    Returns the number of facts actually stored.
    """
    if not facts:
        return 0

    normalized = [_norm(f) for f in facts if _norm(f) and _norm(f) != "no new memories."]
    if not normalized:
        return 0

    new_facts = []
    for norm in normalized:
        if not await _already_have(db, chat_id, norm):
            new_facts.append(norm)
    
    if not new_facts:
        log.debug("All %d facts already exist for chat=%s", len(normalized), chat_id)
        return 0

    try:
        embeddings = await get_embeddings_batch(new_facts)
    except Exception as exc:
        log.error("Batch embedding failed for chat=%s: %s", chat_id, exc, exc_info=True)
        return 0

    stored = 0
    for fact, emb in zip(new_facts, embeddings):
        if not emb:
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
