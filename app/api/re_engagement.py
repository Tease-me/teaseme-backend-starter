import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.utils.deps import get_current_user
from app.services.re_engagement import (
    run_reengagement_job,
    get_reengagement_stats,
    find_inactive_high_balance_users,
    DEFAULT_INACTIVE_DAYS,
    DEFAULT_MIN_BALANCE_CENTS,
)

log = logging.getLogger("re_engagement_api")

router = APIRouter(prefix="/re-engagement", tags=["re-engagement"])


@router.post("/run")
async def run_reengagement_manually(
    dry_run: bool = Query(False, description="If true, find users but don't send notifications"),
    inactive_days: int = Query(DEFAULT_INACTIVE_DAYS, description="Minimum days of inactivity"),
    min_balance_cents: int = Query(DEFAULT_MIN_BALANCE_CENTS, description="Minimum wallet balance in cents"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        log.info(f"[RE-ENGAGE] Manual trigger by user {current_user.id}")

        result = await run_reengagement_job(
            db=db,
            inactive_days=inactive_days,
            min_balance_cents=min_balance_cents,
            dry_run=dry_run,
        )

        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to run re-engagement job: %s", e)
        raise HTTPException(status_code=500, detail="Failed to run re-engagement job")


@router.get("/stats")
async def get_stats(
    days: int = Query(7, description="Number of days to look back"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        stats = await get_reengagement_stats(db, days=days)
        return stats
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to get re-engagement stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get re-engagement stats")


@router.get("/preview")
async def preview_eligible_users(
    inactive_days: int = Query(DEFAULT_INACTIVE_DAYS, description="Minimum days of inactivity"),
    min_balance_cents: int = Query(DEFAULT_MIN_BALANCE_CENTS, description="Minimum wallet balance in cents"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        eligible = await find_inactive_high_balance_users(
            db,
            inactive_days=inactive_days,
            min_balance_cents=min_balance_cents,
        )

        return {
            "inactive_days": inactive_days,
            "min_balance_cents": min_balance_cents,
            "min_balance_dollars": min_balance_cents / 100,
            "eligible_count": len(eligible),
            "eligible": [
                {
                    "user_id": e["user_id"],
                    "influencer_id": e["influencer_id"],
                    "influencer_name": e["influencer_name"],
                    "balance_cents": e["balance_cents"],
                    "balance_dollars": e["balance_cents"] / 100,
                    "days_inactive": e["days_inactive"],
                    "last_interaction": e["last_interaction_at"].isoformat() if e["last_interaction_at"] else None,
                }
                for e in eligible
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to preview eligible users: %s", e)
        raise HTTPException(status_code=500, detail="Failed to preview eligible users")

