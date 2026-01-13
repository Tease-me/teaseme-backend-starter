import io
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.config import settings
from app.db.models import User
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


@router.patch("/{id}/usage", response_model=UserOut)
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
