from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.db.models import Influencer, InfluencerFollower, User
from app.db.session import get_db
from app.schemas.follow import FollowActionResponse, FollowListResponse, FollowStatus
from app.utils.deps import get_current_user

router = APIRouter(prefix="/follow", tags=["follow"])


async def _get_follow(
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


async def _ensure_influencer(db: AsyncSession, influencer_id: str) -> Influencer:
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return influencer


@router.post("/{influencer_id}", response_model=FollowActionResponse, status_code=201)
async def follow_influencer(
    influencer_id: str = Path(..., description="ID of the influencer to follow"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _ensure_influencer(db, influencer_id)

    existing = await _get_follow(db, influencer_id, user.id)
    if existing:
        return FollowActionResponse(
            influencer_id=influencer_id,
            user_id=user.id,
            following=True,
            created_at=existing.created_at,
        )

    follow = InfluencerFollower(influencer_id=influencer_id, user_id=user.id)
    db.add(follow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _get_follow(db, influencer_id, user.id)
        if existing:
            return FollowActionResponse(
                influencer_id=influencer_id,
                user_id=user.id,
                following=True,
                created_at=existing.created_at,
            )
        raise
    except Exception:
        await db.rollback()
        raise

    await db.refresh(follow)
    return FollowActionResponse(
        influencer_id=influencer_id,
        user_id=user.id,
        following=True,
        created_at=follow.created_at,
    )


@router.delete("/{influencer_id}", response_model=FollowActionResponse)
async def unfollow_influencer(
    influencer_id: str = Path(..., description="ID of the influencer to unfollow"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _ensure_influencer(db, influencer_id)
    existing = await _get_follow(db, influencer_id, user.id)

    if not existing:
        return FollowActionResponse(
            influencer_id=influencer_id,
            user_id=user.id,
            following=False,
        )

    await db.delete(existing)
    await db.commit()

    return FollowActionResponse(
        influencer_id=influencer_id,
        user_id=user.id,
        following=False,
        created_at=existing.created_at,
    )


@router.get("", response_model=FollowListResponse)
async def list_follows(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500, description="Max follows to return"),
    offset: int = Query(0, ge=0, description="Number of follows to skip"),
):
    result = await db.execute(
        select(InfluencerFollower)
        .where(InfluencerFollower.user_id == user.id)
        .offset(offset)
        .limit(limit)
    )
    follows = result.scalars().all()
    return FollowListResponse(
        count=len(follows),
        items=[FollowStatus.model_validate(f) for f in follows],
    )
