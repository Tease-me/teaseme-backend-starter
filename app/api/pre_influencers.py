import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_db
from app.db.models import PreInfluencer
from app.schemas.pre_influencer import (
    PreInfluencerRegisterRequest,
    PreInfluencerRegisterResponse,
    SurveyState,
    SurveySaveRequest
)
from app.utils.email import send_profile_survey_email

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
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )