from pydantic import BaseModel

class TopUpRequest(BaseModel):
    cents: int
    
class BillingCheckoutRequest(BaseModel):
    price_id: str
    quantity:str 
    currency: str = "USD"
    mode: str = "SUBSCRIPTION"  # or "PAYMENT"
    success_url: HttpUrl
    cancel_url: HttpUrl
