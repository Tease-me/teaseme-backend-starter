from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
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