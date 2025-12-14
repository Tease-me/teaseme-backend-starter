import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_db
from app.db.models import PreInfluencer
from app.schemas.pre_influencer import (
    PreInfluencerRegisterRequest,
    PreInfluencerRegisterResponse,
    SurveyState,
    SurveySaveRequest,
    InfluencerAudioDeleteRequest
)
from app.utils.email import send_profile_survey_email
from app.utils.s3 import save_influencer_photo_to_s3, generate_presigned_url, delete_file_from_s3


router = APIRouter(prefix="/pre-influencers", tags=["pre-influencers"])

@router.post("/register", response_model=PreInfluencerRegisterResponse)
async def register_pre_influencer(
    data: PreInfluencerRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(PreInfluencer).where(
            or_(
                PreInfluencer.email == data.email,
                PreInfluencer.username == data.username,
            )
        )
    )
    if existing.scalar():
        raise HTTPException(
            status_code=200,
            detail="Username or email already registered as pre-influencer",
        )

    verify_token = secrets.token_urlsafe(32)

    pre = PreInfluencer(
        full_name=data.full_name,
        location=data.location,
        username=data.username,
        email=data.email,
        password=data.password,
        survey_token=verify_token,
    )

    db.add(pre)
    await db.commit()
    await db.refresh(pre)

    send_profile_survey_email(
        pre.email,
        verify_token,
        data.password,
    )

    return PreInfluencerRegisterResponse(
        ok=True,
        user_id=pre.id,
        email=pre.email,
        message="Check your email.",
    )


@router.get("/survey", response_model=SurveyState)
async def open_survey(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.survey_token == token)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired survey link",
        )

    return SurveyState(
        pre_influencer_id=pre.id,
        username=pre.username,
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )

@router.put("/{pre_id}/survey", response_model=SurveyState)
async def save_survey_state(
    pre_id: int,
    data: SurveySaveRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    pre.survey_answers = data.survey_answers
    pre.survey_step = data.survey_step

    await db.commit()
    await db.refresh(pre)

    return SurveyState(
        pre_influencer_id=pre.id,
        username=pre.username,
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )

@router.post("/upload-picture")
async def upload_pre_influencer_picture(
    pre_influencer_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_influencer_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    if not pre.username:
        raise HTTPException(
            status_code=400,
            detail="Pre-influencer has no username to store picture under",
        )

    s3_key = await save_influencer_photo_to_s3(
        file.file,
        file.filename or "profile.jpg",
        file.content_type or "image/jpeg",
        influencer_id=pre.username,
    )

    answers = pre.survey_answers or {}
    answers["profile_picture_key"] = s3_key
    pre.survey_answers = answers

    await db.commit()
    await db.refresh(pre)

    return {"s3_key": s3_key}

@router.get("/{pre_id}/picture-url")
async def get_pre_influencer_picture_url(
    pre_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    answers = pre.survey_answers or {}
    key = answers.get("profile_picture_key")
    if not key:
        raise HTTPException(status_code=404, detail="No picture stored")

    url = generate_presigned_url(key, expires=3600)
    return {"url": url}

@router.delete("/influencer-audio/{influencer_id}")
async def delete_influencer_audio(
    influencer_id: str,
    payload: InfluencerAudioDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    key = payload.key

    expected_prefix = f"influencer-audio/{influencer_id}/"
    if not key.startswith(expected_prefix):
      raise HTTPException(status_code=400, detail="Invalid audio key for this influencer")

    await delete_file_from_s3(key)

    return {"ok": True}