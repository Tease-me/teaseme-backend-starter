from app.api.utils import get_embedding, search_similar_memories, upsert_memory

async def find_similar_memories(db, chat_id: str, message: str, top_k: int = 7):
    emb = await get_embedding(message)
    memories = await search_similar_memories(db, chat_id, emb, top_k=top_k)
    return list(dict.fromkeys([m for m in memories if m]))

async def store_fact(db, chat_id: str, fact: str, sender: str = "user"):
    emb = await get_embedding(fact)
    await upsert_memory(db=db, chat_id=chat_id, content=fact, embedding=emb, sender=sender)