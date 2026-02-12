"""
Embedding and vector search service for AI-powered memory and message retrieval.

This module provides:
- OpenAI text embeddings generation (single and batch)
- Vector similarity search for memories and messages
- Memory upsert with deduplication based on semantic similarity
"""

import logging
import time
from datetime import datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy import text, func

log = logging.getLogger(__name__)

# Use AsyncOpenAI for non-blocking API calls
# This prevents blocking the event loop during embedding requests
client = AsyncOpenAI()


async def get_embedding(text_input: str) -> list[float]:
    """
    Get embedding for a single text (non-blocking).
    
    Args:
        text_input: Text to embed
        
    Returns:
        Embedding vector as list of floats
    """
    from app.services.token_tracker import track_usage_bg

    t0 = time.perf_counter()
    response = await client.embeddings.create(
        input=text_input,
        model="text-embedding-3-small"
    )
    emb_ms = int((time.perf_counter() - t0) * 1000)

    usage = response.usage
    track_usage_bg(
        "system", "openai", "text-embedding-3-small", "embedding",
        input_tokens=getattr(usage, "total_tokens", None),
        latency_ms=emb_ms,
    )

    return response.data[0].embedding


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Get embeddings for multiple texts in a single API call.
    
    This is much more efficient than calling get_embedding() in a loop:
    - 1 API call instead of N
    - ~70-80% latency reduction for multiple texts
    - Non-blocking: doesn't block event loop during API call
    
    Args:
        texts: List of texts to embed (max ~2000 recommended per batch)
        
    Returns:
        List of embeddings in the same order as input texts
    """
    if not texts:
        return []
    
    if len(texts) == 1:
        # Single text - use regular function
        return [await get_embedding(texts[0])]
    
    try:
        t0 = time.perf_counter()
        response = await client.embeddings.create(
            input=texts,
            model="text-embedding-3-small"
        )
        emb_ms = int((time.perf_counter() - t0) * 1000)

        # Track batch embedding usage
        from app.services.token_tracker import track_usage_bg
        usage = response.usage
        track_usage_bg(
            "system", "openai", "text-embedding-3-small", "embedding_batch",
            input_tokens=getattr(usage, "total_tokens", None),
            latency_ms=emb_ms,
        )

        # API returns embeddings in order, but let's be safe
        # Sort by index to ensure order matches input
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
    except Exception as e:
        log.error("Batch embedding failed: %s", e, exc_info=True)
        # Fallback: try one at a time
        embeddings = []
        for text in texts:
            try:
                emb = await get_embedding(text)
                embeddings.append(emb)
            except Exception as inner_e:
                log.error("Single embedding fallback failed for text: %s", inner_e)
                embeddings.append([])  # Empty embedding on failure
        return embeddings


async def search_similar_memories(db, chat_id: str, embedding: list[float], top_k: int = 10, max_distance: float | None = None) -> list[str]:
    """
    Search for similar memories using vector similarity with cosine distance.
    
    Orders by similarity first (most relevant), then by recency (created_at DESC) as a tiebreaker.
    
    Args:
        db: Database session
        chat_id: Chat ID to search within
        embedding: Query embedding vector
        top_k: Number of results to return (default: 10)
        max_distance: Optional maximum cosine distance threshold (default: None = no filtering)
                     Lower = more similar (0=identical, 1=orthogonal)
                     Recommended: 0.3-0.7 for filtering
        
    Returns:
        List of memory content strings ordered by similarity, then recency
    """
    if max_distance is not None:
        sql = text("""
            SELECT content, embedding <=> :embedding AS distance
            FROM memories
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
              AND embedding <=> :embedding <= :max_distance
            ORDER BY distance ASC, created_at DESC
            LIMIT :top_k
        """)
        params = {
            "chat_id": chat_id,
            "embedding": "[" + ",".join(str(x) for x in embedding) + "]",
            "top_k": top_k,
            "max_distance": max_distance
        }
    else:
        sql = text("""
            SELECT content
            FROM memories
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding, created_at DESC
            LIMIT :top_k
        """)
        params = {
            "chat_id": chat_id,
            "embedding": "[" + ",".join(str(x) for x in embedding) + "]",
            "top_k": top_k
        }
    
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]


async def search_similar_messages(db, chat_id: str, embedding: list[float], top_k: int = 10, max_distance: float | None = None) -> list[str]:
    """
    Search for similar messages using vector similarity with cosine distance.
    
    Orders by similarity first (most relevant), then by recency (created_at DESC) as a tiebreaker.
    
    Args:
        db: Database session
        chat_id: Chat ID to search within
        embedding: Query embedding vector
        top_k: Number of results to return (default: 10)
        max_distance: Optional maximum cosine distance threshold (default: None = no filtering)
                     Lower = more similar (0=identical, 1=orthogonal)
                     Recommended: 0.3-0.7 for filtering
        
    Returns:
        List of message content strings ordered by similarity, then recency
    """
    if max_distance is not None:
        sql = text("""
            SELECT content, embedding <=> :embedding AS distance
            FROM messages
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
              AND embedding <=> :embedding <= :max_distance
            ORDER BY distance ASC, created_at DESC
            LIMIT :top_k
        """)
        params = {
            "chat_id": chat_id,
            "embedding": "[" + ",".join(str(x) for x in embedding) + "]",
            "top_k": top_k,
            "max_distance": max_distance
        }
    else:
        sql = text("""
            SELECT content
            FROM messages
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding, created_at DESC
            LIMIT :top_k
        """)
        params = {
            "chat_id": chat_id,
            "embedding": "[" + ",".join(str(x) for x in embedding) + "]",
            "top_k": top_k
        }
    
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]


async def upsert_memory(
    db,
    chat_id: str,
    content: str,
    embedding: list[float],
    sender: str = "fact",
    similarity_threshold: float = 0.15,
) -> str | None:
    """
    Insert or update a memory based on semantic similarity using cosine distance.
    
    If a similar memory already exists (within similarity_threshold), it will be updated.
    Otherwise, a new memory is inserted.
    
    Args:
        db: Database session
        chat_id: Chat ID
        content: Memory content
        embedding: Content embedding vector
        sender: Sender identifier (default: "fact")
        similarity_threshold: Maximum cosine distance for considering memories similar (default: 0.15)
                             Lower = stricter matching (0=identical, 1=orthogonal)
        
    Returns:
        "update" if existing memory was updated, "insert" if new memory created, None on error
    """
    try:
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        # 1. Search for similar memory (prefer most similar, then most recent)
        sql_find = text("""
            SELECT id, embedding <=> :embedding AS similarity
            FROM memories
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
            ORDER BY similarity ASC, created_at DESC
            LIMIT 1
        """)
        params_find = {
            "chat_id": chat_id,
            "embedding": embedding_str,
        }
        result = await db.execute(sql_find, params_find)
        similar = result.fetchone()

        if similar and similar[1] <= similarity_threshold:
            # Update existing similar memory
            sql_update = text("""
                UPDATE memories
                SET content = :content, embedding = :embedding, sender = :sender, created_at = NOW()
                WHERE id = :id
            """)
            params_update = {
                "id": similar[0],
                "content": content,
                "embedding": embedding_str,
                "sender": sender,
            }
            await db.execute(sql_update, params_update)
            result_action = "update"
        else:
            # Insert as a new memory
            sql_insert = text("""
                INSERT INTO memories (chat_id, content, embedding, sender, created_at)
                VALUES (:chat_id, :content, :embedding, :sender, NOW())
            """)
            params_insert = {
                "chat_id": chat_id,
                "content": content,
                "embedding": embedding_str,
                "sender": sender,
            }
            await db.execute(sql_insert, params_insert)
            result_action = "insert"

        await db.commit()
        return result_action
    except Exception as e:
        await db.rollback()
        log.error(f"Failed to upsert memory for chat_id={chat_id}: {e}", exc_info=True)
        return None
