from pydantic import BaseModel

class TopUpRequest(BaseModel):
    cents: int