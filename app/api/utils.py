from openai import OpenAI
from sqlalchemy import text

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