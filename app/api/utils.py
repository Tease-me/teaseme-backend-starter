from openai import OpenAI
from sqlalchemy import text
from dotenv import load_dotenv
load_dotenv()
client = OpenAI()

async def get_embedding(text: str) -> list[float]:
    response = client.embeddings.create(input=text,
    model="text-embedding-3-small")
    return response.data[0].embedding

async def search_similar_memories(db, user_id, persona_id, embedding, top_k=5):
    sql = text("""
        SELECT content
        FROM messages
        WHERE user_id = :user_id
          AND persona_id = :persona_id
          AND embedding IS NOT NULL
        ORDER BY embedding <-> :embedding
        LIMIT :top_k
    """)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params = {
        "user_id": user_id,
        "persona_id": persona_id,
        "embedding": embedding_str,
        "top_k": top_k
    }
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]


async def upsert_memory(db, user_id, persona_id, content, embedding, sender="user", similarity_threshold=0.1):
    sql_find_similar = text("""
        SELECT id, embedding <-> :embedding AS similarity
        FROM messages
        WHERE user_id = :user_id
          AND persona_id = :persona_id
          AND embedding IS NOT NULL
        ORDER BY similarity ASC
        LIMIT 1
    """)

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params_find = {
        "user_id": user_id,
        "persona_id": persona_id,
        "embedding": embedding_str
    }

    result = await db.execute(sql_find_similar, params_find)
    similar_memory = result.fetchone()

    if similar_memory and similar_memory[1] <= similarity_threshold:
        # Update existing memory
        sql_update = text("""
            UPDATE messages
            SET content = :content, embedding = :embedding, sender = :sender
            WHERE id = :id
        """)
        params_update = {
            "id": similar_memory[0],
            "content": content,
            "embedding": embedding_str,
            "sender": sender
        }
        await db.execute(sql_update, params_update)
    else:
        # Insert new memory
        sql_insert = text("""
            INSERT INTO messages (user_id, persona_id, content, embedding, sender)
            VALUES (:user_id, :persona_id, :content, :embedding, :sender)
        """)
        params_insert = {
            "user_id": user_id,
            "persona_id": persona_id,
            "content": content,
            "embedding": embedding_str,
            "sender": sender
        }
        await db.execute(sql_insert, params_insert)

    await db.commit()