#TODO: add file into UTILS folder
from openai import OpenAI
from sqlalchemy import text
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
client = OpenAI()

async def get_embedding(text: str) -> list[float]:
    response = client.embeddings.create(input=text,
    model="text-embedding-3-small")
    return response.data[0].embedding

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


async def search_influencer_knowledge(db, influencer_id: str, embedding: list[float], top_k: int = 5):
    """
    Search influencer's knowledge base chunks by semantic similarity.
    
    Args:
        db: Database session
        influencer_id: ID of the influencer
        embedding: Query embedding vector
        top_k: Number of results to return
    
    Returns:
        List of dicts with 'content' and 'metadata' keys
    """
    sql = text("""
        SELECT content, chunk_metadata
        FROM influencer_knowledge_chunks
        WHERE influencer_id = :influencer_id
          AND embedding IS NOT NULL
        ORDER BY embedding <-> :embedding
        LIMIT :top_k
    """)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params = {
        "influencer_id": influencer_id,
        "embedding": embedding_str,
        "top_k": top_k
    }
    result = await db.execute(sql, params)
    return [{"content": row[0], "metadata": row[1]} for row in result.fetchall()]

