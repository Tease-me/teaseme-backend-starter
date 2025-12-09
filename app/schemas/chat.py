from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class ChatCreateRequest(BaseModel):
    user_id: int
    influencer_id: str

class MessageSchema(BaseModel):
    id: int
    chat_id: str
    sender: str
    content: str
    audio_url: Optional[str] = None
    created_at: datetime  
    channel: Optional[str] = None
    class Config:
        from_attributes = True
        json_encoders = {
            type(None): lambda v: None
        }

class PaginatedMessages(BaseModel):
    total: int
    page: int
    page_size: int
    messages: List[MessageSchema]

class LoveTriadScore(BaseModel):
    intimacy: float
    passion: float
    commitment: float
    last_interaction: Optional[float] = None