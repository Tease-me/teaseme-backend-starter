import io
import logging
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.core.config import settings
from app.db.models import User, InfluencerWallet, DailyUsage, Pricing
from app.db.session import get_db
from app.schemas.user import UserOut, UserUpdate
from app.utils.deps import get_current_user
from app.utils.s3 import (
    generate_user_presigned_url,
    generate_presigned_url,
    delete_file_from_s3,
    save_user_photo_to_s3,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/{id}")
async def get_user_usage(
    id: int,
    influencer_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    today = date.today()

    normal_wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(False),
        )
    )
    adult_wallet = await db.scalar(
        select(InfluencerWallet).where(
            InfluencerWallet.user_id == id,
            InfluencerWallet.influencer_id == influencer_id,
            InfluencerWallet.is_18.is_(True),
        )
    )

    normal_usage = await db.get(DailyUsage, (id, today, False))
    adult_usage = await db.get(DailyUsage, (id, today, True))

    pricing_result = await db.execute(
        select(Pricing).where(Pricing.is_active.is_(True))
    )
    pricing_map = {p.feature: p for p in pricing_result.scalars().all()}

    def calc(wallet, usage, feature: str, usage_field: str) -> dict:
        price = pricing_map.get(feature)
        if not price:
            return {"remaining": 0, "free_left": 0, "balance_cents": 0}
        
        used = getattr(usage, usage_field, 0) or 0 if usage else 0
        free_allowance = price.free_allowance or 0
        free_left = max(free_allowance - used, 0)
        balance = wallet.balance_cents if wallet else 0
        unit_price = price.price_cents or 1
        paid_units = balance // unit_price if unit_price > 0 else 0
        
        return {
            "remaining": free_left + paid_units,
            "free_left": free_left,
            "used_today": used,
            "balance_cents": balance,
        }

    return {
        "influencer_id": influencer_id,
        "normal": {
            "balance_cents": normal_wallet.balance_cents if normal_wallet else 0,
            "messages": calc(normal_wallet, normal_usage, "text", "text_count"),
            "live_chat_minutes": {
                **calc(normal_wallet, normal_usage, "live_chat", "live_secs"),
                "remaining_minutes": round(calc(normal_wallet, normal_usage, "live_chat", "live_secs")["remaining"] / 60, 2),
            },
        },
        "adult": {
            "balance_cents": adult_wallet.balance_cents if adult_wallet else 0,
            "messages": calc(adult_wallet, adult_usage, "text_18", "text_count"),
            "voice_minutes": {
                **calc(adult_wallet, adult_usage, "voice_18", "voice_secs"),
                "remaining_minutes": round(calc(adult_wallet, adult_usage, "voice_18", "voice_secs")["remaining"] / 60, 2),
            },
        },
    }


@router.get("/{id}", response_model=UserOut)
async def get_user_by_id(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this profile")
        
    user_out = UserOut.model_validate(current_user)
    
    if current_user.profile_photo_key:
        user_out.profile_photo_url = generate_user_presigned_url(current_user.profile_photo_key)
        
    return user_out


@router.get("/{id}", response_model=UserOut)
async def get_user_by_id(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this profile")

    user_out = UserOut.model_validate(current_user)

    if current_user.profile_photo_key:
        user_out.profile_photo_url = generate_user_presigned_url(current_user.profile_photo_key)

    return user_out


@router.patch("/{id}/profile", response_model=UserOut)
async def update_user(
    id: int,
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile fields"""
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this profile")

    update_data = user_in.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(current_user, field, value)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    # Re-generate response
    user_out = UserOut.model_validate(current_user)
    if current_user.profile_photo_key:
        user_out.profile_photo_url = generate_user_presigned_url(current_user.profile_photo_key)
        
    return user_out


@router.post("/{id}/photo", response_model=UserOut)
async def upload_user_photo_endpoint(
    id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload functionality for user profile photo"""
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to upload photo for this profile")

    if not file:
        raise HTTPException(400, "No file uploaded")
        
    previous_key = current_user.profile_photo_key

    try:
        key = await save_user_photo_to_s3(
            file.file, 
            file.filename or "profile.jpg", 
            file.content_type or "image/jpeg", 
            current_user.id
        )
        current_user.profile_photo_key = key
        db.add(current_user)
        try:
            await db.commit()
            await db.refresh(current_user)
        except Exception:
            await db.rollback()
            if key and key != previous_key:
                try:
                    await delete_file_from_s3(key)
                except Exception:
                    log.warning("Failed to rollback uploaded S3 photo %s", key, exc_info=True)
            raise

        if previous_key and previous_key != key:
            try:
                await delete_file_from_s3(previous_key)
            except Exception:
                log.warning("Failed to delete previous S3 photo %s", previous_key, exc_info=True)
        
        user_out = UserOut.model_validate(current_user)
        user_out.profile_photo_url = generate_user_presigned_url(key)
        return user_out
        
    except Exception as e:
        log.error(f"Failed to upload user photo: {e}", exc_info=True)
        raise HTTPException(500, "Failed to upload photo")
