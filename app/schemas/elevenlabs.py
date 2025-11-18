from typing import Optional
from pydantic import BaseModel, model_validator

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

class UpdatePromptBody(BaseModel):
    agent_id: Optional[str] = None
    influencer_id: Optional[str] = None
    voice_prompt: str
    first_message: Optional[str] = None
    
    @model_validator(mode='after')
    def validate_at_least_one_id(self):
        if not self.agent_id and not self.influencer_id:
            raise ValueError("Either 'agent_id' or 'influencer_id' must be provided")
        return self 