from pydantic import BaseModel

class SignedUrlRequest(BaseModel):
    influencer_id: str
    first_message: str | None = None 