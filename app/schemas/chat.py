from pydantic import BaseModel
from typing import List
from datetime import datetime


class ChatCreateRequest(BaseModel):
    user_id: int
    influencer_id: str

class MessageSchema(BaseModel):
    id: int
    chat_id: str
    sender: str
    content: str
    created_at: datetime  

    class Config:
        from_attributes = True

class PaginatedMessages(BaseModel):
    total: int
    page: int
    page_size: int
    messages: List[MessageSchema]