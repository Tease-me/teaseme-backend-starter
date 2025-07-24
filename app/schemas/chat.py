from pydantic import BaseModel

class ChatCreateRequest(BaseModel):
    user_id: int
    persona_id: str