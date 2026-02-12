import io
import logging
from datetime import date
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.core.config import settings
from app.db.models import User, InfluencerWallet, DailyUsage, Pricing
from app.db.session import get_db
from app.schemas.user import UserOut, UserUpdate, UserAdultPromptUpdate, UserAdultPromptOut
from app.utils.auth.dependencies import get_current_user
from app.utils.storage.s3 import (
    generate_user_presigned_url,
    delete_file_from_s3,
    save_user_photo_to_s3,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/{id}/usage")
async def get_user_usage(
    id: int,
    influencer_id: str | None = Query(None, description="Filter by specific influencer ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    today = date.today()

    if influencer_id:
        wallets_result = await db.execute(
            select(InfluencerWallet).where(
                InfluencerWallet.user_id == id,
                InfluencerWallet.influencer_id == influencer_id,
            )
        )
    else:
        wallets_result = await db.execute(
            select(InfluencerWallet).where(InfluencerWallet.user_id == id)
        )
    wallets = wallets_result.scalars().all()

    normal_usage = await db.get(DailyUsage, (id, today, False))
    adult_usage = await db.get(DailyUsage, (id, today, True))

    pricing_result = await db.execute(
        select(Pricing).where(Pricing.is_active.is_(True))
    )
    pricing_map = {p.feature: p for p in pricing_result.scalars().all()}

    def get_price_info(feature: str) -> tuple[int, int]:
        price = pricing_map.get(feature)
        if not price:
            return (0, 0)
        return (price.price_cents or 0, price.free_allowance or 0)

    def get_used_today(usage, usage_field: str) -> int:
        if not usage:
            return 0
        return getattr(usage, usage_field, 0) or 0

    def calc_remaining(balance: int, unit_price: int, free_left: int) -> int:
        paid_units = balance // unit_price if unit_price > 0 else 0
        return free_left + paid_units

    text_price, text_free = get_price_info("text")
    live_price, live_free = get_price_info("live_chat")
    text_18_price, text_18_free = get_price_info("text_18")
    voice_18_price, voice_18_free = get_price_info("voice_18")

    normal_text_used = get_used_today(normal_usage, "text_count")
    normal_live_used = get_used_today(normal_usage, "live_secs")
    adult_text_used = get_used_today(adult_usage, "text_count")
    adult_voice_used = get_used_today(adult_usage, "voice_secs")

    normal_text_free_left = max(text_free - normal_text_used, 0)
    normal_live_free_left = max(live_free - normal_live_used, 0)
    adult_text_free_left = max(text_18_free - adult_text_used, 0)
    adult_voice_free_left = max(voice_18_free - adult_voice_used, 0)

    def build_normal_wallet(balance: int) -> dict:
        text_remaining = calc_remaining(balance, text_price, normal_text_free_left)
        live_remaining = calc_remaining(balance, live_price, normal_live_free_left)
        return {
            "balance_cents": balance,
            "messages": {
                "remaining": text_remaining,
                "free_left": normal_text_free_left,
                "used_today": normal_text_used,
                "unit_price_cents": text_price,
            },
            "live_chat": {
                "remaining": live_remaining,
                "remaining_minutes": round(live_remaining / 60, 2),
                "free_left": normal_live_free_left,
                "used_today": normal_live_used,
                "unit_price_cents": live_price,
            },
        }

    def build_adult_wallet(balance: int) -> dict:
        text_remaining = calc_remaining(balance, text_18_price, adult_text_free_left)
        voice_remaining = calc_remaining(balance, voice_18_price, adult_voice_free_left)
        return {
            "balance_cents": balance,
            "messages": {
                "remaining": text_remaining,
                "free_left": adult_text_free_left,
                "used_today": adult_text_used,
                "unit_price_cents": text_18_price,
            },
            "voice": {
                "remaining": voice_remaining,
                "remaining_minutes": round(voice_remaining / 60, 2),
                "free_left": adult_voice_free_left,
                "used_today": adult_voice_used,
                "unit_price_cents": voice_18_price,
            },
        }

    if influencer_id:
        normal_wallet = None
        adult_wallet = None

        for wallet in wallets:
            balance = wallet.balance_cents or 0
            if wallet.is_18:
                adult_wallet = build_adult_wallet(balance)
            else:
                normal_wallet = build_normal_wallet(balance)

        if normal_wallet is None:
            normal_wallet = build_normal_wallet(0)
        if adult_wallet is None:
            adult_wallet = build_adult_wallet(0)

        return {
            "influencer_id": influencer_id,
            "normal": normal_wallet,
            "adult": adult_wallet,
        }

    influencer_wallets: dict[str, dict] = {}
    for wallet in wallets:
        inf_id = wallet.influencer_id
        if inf_id not in influencer_wallets:
            influencer_wallets[inf_id] = {"normal": None, "adult": None}

        balance = wallet.balance_cents or 0
        if wallet.is_18:
            influencer_wallets[inf_id]["adult"] = build_adult_wallet(balance)
        else:
            influencer_wallets[inf_id]["normal"] = build_normal_wallet(balance)

    total_normal_balance = sum((w.balance_cents or 0) for w in wallets if not w.is_18)
    total_adult_balance = sum((w.balance_cents or 0) for w in wallets if w.is_18)

    return {
        "influencers": influencer_wallets,
        "totals": {
            "normal": build_normal_wallet(total_normal_balance),
            "adult": build_adult_wallet(total_adult_balance),
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



@router.patch("/{id}/profile", response_model=UserOut)
async def update_user(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_in: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
):
    if id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this profile")

    if user_in:
        user_data = UserUpdate.model_validate_json(user_in)
        update_data = user_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(current_user, field, value)

    if file:
        previous_key = current_user.profile_photo_key
        try:
            key = await save_user_photo_to_s3(
                file.file,
                file.filename or "profile.jpg",
                file.content_type or "image/jpeg",
                current_user.id
            )
            current_user.profile_photo_key = key
        except Exception as e:
            log.error(f"Failed to upload user photo: {e}", exc_info=True)
            raise HTTPException(500, "Failed to upload photo")

    db.add(current_user)
    try:
        await db.commit()
        await db.refresh(current_user)
    except Exception:
        await db.rollback()
        if file and current_user.profile_photo_key and current_user.profile_photo_key != previous_key:
            try:
                await delete_file_from_s3(current_user.profile_photo_key)
            except Exception:
                log.warning("Failed to rollback uploaded S3 photo", exc_info=True)
        raise

    if file and previous_key and previous_key != current_user.profile_photo_key:
        try:
            await delete_file_from_s3(previous_key)
        except Exception:
            log.warning("Failed to delete previous S3 photo %s", previous_key, exc_info=True)

    user_out = UserOut.model_validate(current_user)
    if current_user.profile_photo_key:
        user_out.profile_photo_url = generate_user_presigned_url(current_user.profile_photo_key)
        
    return user_out


@router.patch("/adult-prompt", response_model=UserAdultPromptOut)
async def update_user_adult_prompt(
    payload: UserAdultPromptUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.custom_adult_prompt = payload.custom_adult_prompt
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return UserAdultPromptOut(custom_adult_prompt=current_user.custom_adult_prompt)


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
