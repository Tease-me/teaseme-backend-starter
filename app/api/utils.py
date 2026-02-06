#TODO: add file into UTILS folder
from openai import AsyncOpenAI
from sqlalchemy import text
from dotenv import load_dotenv
from datetime import datetime
import logging

log = logging.getLogger(__name__)

load_dotenv()

# Use AsyncOpenAI for non-blocking API calls
# This prevents blocking the event loop during embedding requests
client = AsyncOpenAI()


async def get_embedding(text: str) -> list[float]:
    """Get embedding for a single text (non-blocking)."""
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
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
        response = await client.embeddings.create(
            input=texts,
            model="text-embedding-3-small"
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


async def search_similar_memories(db, chat_id, embedding, top_k=5):
    sql = text("""
        SELECT content
        FROM memories
        WHERE chat_id = :chat_id
          AND embedding IS NOT NULL
        ORDER BY embedding <-> :embedding
        LIMIT :top_k
    """)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params = {
        "chat_id": chat_id,
        "embedding": embedding_str,
        "top_k": top_k
    }
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]

async def search_similar_messages(db, chat_id, embedding, top_k=5):
    sql = text("""
        SELECT content
        FROM messages
        WHERE chat_id = :chat_id
          AND embedding IS NOT NULL
        ORDER BY embedding <-> :embedding
        LIMIT :top_k
    """)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params = {
        "chat_id": chat_id,
        "embedding": embedding_str,
        "top_k": top_k
    }
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]



from sqlalchemy import text, func
from datetime import datetime, timezone

async def upsert_memory(
    db,
    chat_id: str,
    content: str,
    embedding: list[float],
    sender: str = "fact",
    similarity_threshold: float = 0.1,
):

    try:
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        # 1. Search for similar memory
        sql_find = text("""
            SELECT id, embedding <-> :embedding AS similarity
            FROM memories
            WHERE chat_id = :chat_id
              AND embedding IS NOT NULL
            ORDER BY similarity ASC
            LIMIT 1
        """)
        params_find = {
            "chat_id": chat_id,
            "embedding": embedding_str,
        }
        result = await db.execute(sql_find, params_find)
        similar = result.fetchone()

        if similar and similar[1] <= similarity_threshold:
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
            # 3. Insert as a new memory - use PostgreSQL's NOW() to avoid timezone issues
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
        import logging
        log = logging.getLogger(__name__)
        log.error(f"Failed to upsert memory for chat_id={chat_id}: {e}", exc_info=True)
        return None


