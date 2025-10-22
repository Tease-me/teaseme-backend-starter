from app.api.utils import get_embedding, search_similar_memories, upsert_memory
from sqlalchemy import select
from sqlalchemy.sql import func
from app.db.models import Memory

async def find_similar_memories(db, chat_id: str, message: str, top_k: int = 7):
    emb = await get_embedding(message)
    memories = await search_similar_memories(db, chat_id, emb, top_k=top_k)
    return list(dict.fromkeys([m for m in memories if m]))

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
    # normalize
    norm_fact = _norm(fact)
    if not norm_fact or norm_fact == "no new memories.":
        return

    # avoid duplicates
    if await _already_have(db, chat_id, norm_fact):
        return  # skip saving

    # get embedding
    emb = await get_embedding(norm_fact)

    # save or update
    await upsert_memory(
        db=db,
        chat_id=chat_id,
        content=norm_fact,
        embedding=emb,
        sender=sender
    )