from pydantic import BaseModel

class TopUpRequest(BaseModel):
    influencer_id: str
    cents: int