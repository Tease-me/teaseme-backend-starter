from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.models import InfluencerFollower


async def get_follow(
    db: AsyncSession,
    influencer_id: str,
    user_id: int,
) -> InfluencerFollower | None:
    result = await db.execute(
        select(InfluencerFollower).where(
            InfluencerFollower.influencer_id == influencer_id,
            InfluencerFollower.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_follow_if_missing(
    db: AsyncSession,
    influencer_id: str,
    user_id: int,
) -> InfluencerFollower:
    existing = await get_follow(db, influencer_id, user_id)
    if existing:
        return existing

    follow = InfluencerFollower(influencer_id=influencer_id, user_id=user_id)
    db.add(follow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_follow(db, influencer_id, user_id)
        if existing:
            return existing
        raise
    except Exception:
        await db.rollback()
        raise

    await db.refresh(follow)
    return follow
