from typing import Optional
from pydantic import BaseModel

class SignedUrlRequest(BaseModel):
    influencer_id: str
    first_message: str | None = None

class RegisterConversationBody(BaseModel):
    user_id: int
    influencer_id: Optional[str] = None
    sid: Optional[str] = None

class FinalizeConversationBody(BaseModel):
    user_id: int
    influencer_id: Optional[str] = None
    sid: Optional[str] = None
    timeout_secs: int = 180 