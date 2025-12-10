from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, Dict, Any
from uuid import UUID

class PreInfluencerRegisterRequest(BaseModel):
    full_name: str
    location: Optional[str] = None
    username: str
    email: EmailStr
    password: str

class PreInfluencerRegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ok: bool
    user_id: int
    email: EmailStr
    message: str

class SurveyState(BaseModel):
    pre_influencer_id: int
    survey_answers: Dict[str, Any] | None = None
    survey_step: int

class SurveySaveRequest(BaseModel):
    survey_answers: Dict[str, Any]
    survey_step: int
