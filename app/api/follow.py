import logging
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import InfluencerFollower, User
from app.db.session import get_db
from app.schemas.follow import FollowActionResponse, FollowListResponse, FollowStatus
from app.services.follow import create_follow_if_missing, get_follow
from app.services.influencer import ensure_influencer
from app.utils.deps import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/follow", tags=["follow"])

@router.post("/{influencer_id}", response_model=FollowActionResponse, status_code=201)
async def follow_influencer(
    influencer_id: str = Path(..., description="ID of the influencer to follow"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        await ensure_influencer(db, influencer_id)
        follow = await create_follow_if_missing(db, influencer_id, user.id)
        return FollowActionResponse(
            influencer_id=influencer_id,
            user_id=user.id,
            following=True,
            created_at=follow.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to follow influencer %s for user %s: %s", influencer_id, user.id, e)
        raise HTTPException(status_code=500, detail="Failed to follow influencer")


@router.delete("/{influencer_id}", response_model=FollowActionResponse)
async def unfollow_influencer(
    influencer_id: str = Path(..., description="ID of the influencer to unfollow"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        await ensure_influencer(db, influencer_id)
        existing = await get_follow(db, influencer_id, user.id)

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
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to unfollow influencer %s for user %s: %s", influencer_id, user.id, e)
        raise HTTPException(status_code=500, detail="Failed to unfollow influencer")


@router.get("", response_model=FollowListResponse)
async def list_follows(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500, description="Max follows to return"),
    offset: int = Query(0, ge=0, description="Number of follows to skip"),
):
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to list follows for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to list followed influencers")

