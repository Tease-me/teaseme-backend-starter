from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, Dict, Any, List
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
    username: str
    survey_answers: Dict[str, Any] | None = None
    survey_step: int

class SurveySaveRequest(BaseModel):
    survey_answers: Dict[str, Any]
    survey_step: int

class InfluencerAudioDeleteRequest(BaseModel):
    key: str

class SurveyQuestionsResponse(BaseModel):
    sections: List[Dict[str, Any]]

class SurveyPromptRequest(BaseModel):
    additional_prompt: Optional[str] = None

class SurveyStages(BaseModel):
    hate: str
    dislike: str
    strangers: str
    talking: str
    flirting: str
    dating: str

class SurveyPromptResponse(BaseModel):
    likes: List[str]
    dislikes: List[str]
    mbti_rules: str
    personality_rules: str
    tone: str
    stages: SurveyStages
