import io
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import Influencer
from app.db.session import get_db
from app.schemas.influencer import InfluencerCreate, InfluencerOut, InfluencerUpdate, InfluencerDetail
from app.utils.s3 import (
    generate_influencer_presigned_url,
    generate_presigned_url,
    get_influencer_audio_download_url,
    get_influencer_profile_from_s3,
    list_influencer_audio_keys,
    save_influencer_audio_to_s3,
    save_influencer_photo_to_s3,
    save_influencer_profile_to_s3,
    save_influencer_video_to_s3,
    delete_file_from_s3,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/influencer", tags=["influencer"])

def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


@router.get("", response_model=List[InfluencerOut])
async def list_influencers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Influencer))
    return result.scalars().all()

@router.get("/{id}", response_model=InfluencerDetail)
async def get_influencer(id: str, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    
    profile_json = await get_influencer_profile_from_s3(id)
    photo_url = generate_influencer_presigned_url(influencer.profile_photo_key) if influencer.profile_photo_key else None
    video_url = generate_influencer_presigned_url(influencer.profile_video_key) if influencer.profile_video_key else None
    
    about_text = profile_json.get("about") if isinstance(profile_json, dict) else None
    detail = InfluencerDetail.model_validate(influencer)
    detail.about = about_text
    detail.photo_url = photo_url
    detail.video_url = video_url
    
    return detail

@router.post("", response_model=InfluencerOut, status_code=201)
async def create_influencer(data: InfluencerCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Influencer, data.id):
        raise HTTPException(400, "Influencer with this id already exists")
    influencer = Influencer(**data.model_dump())
    db.add(influencer)
    await db.flush()
    await db.commit()
    await db.refresh(influencer)
    return influencer

@router.patch("/{id}", response_model=InfluencerOut)
async def update_influencer(id: str, data: InfluencerUpdate, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    update_payload = data.model_dump(exclude_unset=True)
    for key, value in update_payload.items():
        setattr(influencer, key, value)
    db.add(influencer)
    await db.commit()
    await db.refresh(influencer)
    return influencer

@router.delete("/{id}")
async def delete_influencer(id: str, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    await db.delete(influencer)
    await db.commit()
    return {"ok": True}


@router.post("/{influencer_id}/profile")
async def update_influencer_profile(
    influencer_id: str,
    about: Optional[str] = Form(None),
    native_language: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    photo: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    previous_photo_key = influencer.profile_photo_key
    previous_video_key = influencer.profile_video_key
    uploaded_photo_key: str | None = None
    uploaded_video_key: str | None = None

    try:
        # Upload media if provided
        if photo:
            uploaded_photo_key = await save_influencer_photo_to_s3(
                photo.file,
                photo.filename,
                photo.content_type or "image/jpeg",
                influencer_id,
            )
            influencer.profile_photo_key = uploaded_photo_key

        if video:
            uploaded_video_key = await save_influencer_video_to_s3(
                video.file,
                video.filename,
                video.content_type or "video/mp4",
                influencer_id,
            )
            influencer.profile_video_key = uploaded_video_key

        # Update metadata
        if native_language:
            influencer.native_language = native_language

        dt_val = _parse_iso_datetime(date_of_birth)
        if date_of_birth and not dt_val:
            raise HTTPException(status_code=400, detail="Invalid date_of_birth format; use ISO 8601")
        if dt_val:
            influencer.date_of_birth = dt_val

        # Save profile JSON (about + native language) to S3; keep extras minimal
        await save_influencer_profile_to_s3(
            influencer_id,
            about=about,
            native_language=native_language or influencer.native_language,
            extras={
                "has_photo": bool(influencer.profile_photo_key),
                "has_video": bool(influencer.profile_video_key),
            },
        )
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            log.warning("Failed to rollback DB session after profile update error", exc_info=True)

        for key, previous in (
            (uploaded_photo_key, previous_photo_key),
            (uploaded_video_key, previous_video_key),
        ):
            if key and key != previous:
                try:
                    await delete_file_from_s3(key)
                except Exception:
                    log.warning("Failed to rollback uploaded S3 object %s", key, exc_info=True)

        if isinstance(exc, HTTPException):
            raise

        if photo and not uploaded_photo_key:
            log.error("Failed to upload influencer photo: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to upload photo")
        if video and not uploaded_video_key:
            log.error("Failed to upload influencer video: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to upload video")

        log.error("Failed to update influencer profile: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save profile metadata")

    try:
        await db.commit()
        await db.refresh(influencer)
    except Exception as exc:
        await db.rollback()
        for key, previous in (
            (uploaded_photo_key, previous_photo_key),
            (uploaded_video_key, previous_video_key),
        ):
            if key and key != previous:
                try:
                    await delete_file_from_s3(key)
                except Exception:
                    log.warning("Failed to rollback uploaded S3 object %s", key, exc_info=True)
        log.error("Failed to persist influencer profile: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to persist influencer profile")

    # Best-effort cleanup: remove previous objects if the key changed (e.g., photo.jpg -> photo.png)
    for key, new_key in (
        (previous_photo_key, influencer.profile_photo_key),
        (previous_video_key, influencer.profile_video_key),
    ):
        if key and new_key and key != new_key:
            try:
                await delete_file_from_s3(key)
            except Exception:
                log.warning("Failed to delete previous S3 object %s", key, exc_info=True)

    return {
        "ok": True,
        "profile_photo_key": influencer.profile_photo_key,
        "profile_video_key": influencer.profile_video_key,
        "native_language": influencer.native_language,
        "date_of_birth": influencer.date_of_birth.isoformat() if influencer.date_of_birth else None,
        "photo_url": generate_influencer_presigned_url(influencer.profile_photo_key)
        if influencer.profile_photo_key
        else None,
        "video_url": generate_influencer_presigned_url(influencer.profile_video_key)
        if influencer.profile_video_key
        else None,
    }


@router.post("/influencer-audio/{influencer_id}")
async def upload_influencer_audio(
    influencer_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    key = await save_influencer_audio_to_s3(
        io.BytesIO(file_bytes),
        file.filename,
        file.content_type or "audio/webm",
        influencer_id,
    )

    url = get_influencer_audio_download_url(key)
    return {"key": key, "url": url}


@router.get("/influencer-audio/{influencer_id}")
async def list_influencer_audio(influencer_id: str):
    keys = await list_influencer_audio_keys(influencer_id)

    if not keys:
        raise HTTPException(status_code=404, detail="Influencer has no audio file stored")

    files = [
        {
            "key": key,
            "download_url": generate_presigned_url(key),
        }
        for key in keys
    ]

    return {
        "influencer_id": influencer_id,
        "count": len(files),
        "files": files,
    }
