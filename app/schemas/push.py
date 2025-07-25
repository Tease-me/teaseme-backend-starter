from pydantic import BaseModel

class SubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict

class SubscriptionResponse(BaseModel):
    status: str