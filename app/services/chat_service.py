import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.models import Chat, Chat18
from datetime import datetime, timezone


async def check_chat(db: AsyncSession, user_id: int, influencer_id: str):
    result = await db.execute(
        select(Chat).where(and_(Chat.user_id == user_id, Chat.influencer_id == influencer_id))
    )
    return result.scalars().first()


async def check_chat18(db: AsyncSession, user_id: int, influencer_id: str):
    result = await db.execute(
        select(Chat18).where(and_(Chat18.user_id == user_id, Chat18.influencer_id == influencer_id))
    )
    return result.scalars().first()


async def create_chat(db: AsyncSession, user_id: int, influencer_id: str, chat_id: str | None = None):
    chat_id = chat_id or str(uuid.uuid4())
    new_chat = Chat(
        id=chat_id,
        user_id=user_id,
        influencer_id=influencer_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(new_chat)
    await db.commit()
    return chat_id


async def create_chat18(db: AsyncSession, user_id: int, influencer_id: str, chat_id: str | None = None):
    chat_id = chat_id or str(uuid.uuid4())
    new_chat = Chat18(
        id=chat_id,
        user_id=user_id,
        influencer_id=influencer_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(new_chat)
    await db.commit()
    return chat_id


async def get_or_create_chat(db: AsyncSession, user_id: int, influencer_id: str, chat_id: str | None = None):
    # if client sent chat_id, ensure it exists
    if chat_id:
        existing = await db.get(Chat, chat_id)
        if existing:
            return existing.id
        # create with provided id
        return await create_chat(db, user_id, influencer_id, chat_id=chat_id)

    existing_chat = await check_chat(db, user_id, influencer_id)
    if existing_chat:
        return existing_chat.id
    return await create_chat(db, user_id, influencer_id)


async def get_or_create_chat18(db: AsyncSession, user_id: int, influencer_id: str, chat_id: str | None = None):
    # if client sent chat_id, ensure it exists
    if chat_id:
        existing = await db.get(Chat18, chat_id)
        if existing:
            return existing.id
        # create with provided id
        return await create_chat18(db, user_id, influencer_id, chat_id=chat_id)

    existing_chat = await check_chat18(db, user_id, influencer_id)
    if existing_chat:
        return existing_chat.id
    return await create_chat18(db, user_id, influencer_id)