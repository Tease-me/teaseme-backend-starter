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


from sqlalchemy import text
from datetime import datetime

async def upsert_memory(
    db,
    chat_id: str,
    content: str,
    embedding: list[float],
    sender: str = "fact",
    similarity_threshold: float = 0.1,
):
    """
    Save a new vector fact/memory in the `memories` table of this chat.
    If a very similar memory (by embedding) is found for the chat, it updates that memory;
    if not, it inserts a new row.
    :param db: Database session
    :param chat_id: ID of the chat
    :param content: Content of the memory
    :param embedding: Embedding vector of the memory
    :param sender: Who is sending the memory (default is "fact")
    :param similarity_threshold: Threshold for similarity (default is 0.1)
    :return: "update" if updated, "insert" if a new memory was added
    """
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
        # 2. Update if similar memory found
        sql_update = text("""
            UPDATE memories
            SET content = :content, embedding = :embedding, sender = :sender, created_at = :created_at
            WHERE id = :id
        """)
        params_update = {
            "id": similar[0],
            "content": content,
            "embedding": embedding_str,
            "sender": sender,
            "created_at": datetime.utcnow(),
        }
        await db.execute(sql_update, params_update)
        result_action = "update"
    else:
        # 3. Insert as a new memory
        sql_insert = text("""
            INSERT INTO memories (chat_id, content, embedding, sender, created_at)
            VALUES (:chat_id, :content, :embedding, :sender, :created_at)
        """)
        params_insert = {
            "chat_id": chat_id,
            "content": content,
            "embedding": embedding_str,
            "sender": sender,
            "created_at": datetime.utcnow(),
        }
        await db.execute(sql_insert, params_insert)
        result_action = "insert"

    await db.commit()
    return result_action


