from pydantic import BaseModel, HttpUrl

class TopUpRequest(BaseModel):
    cents: int
    
class BillingCheckoutRequest(BaseModel):
    price_id: str
    quantity: int
    currency: str = "USD"
    mode: str = "SUBSCRIPTION"  # or "PAYMENT"
    success_url: HttpUrl
    cancel_url: HttpUrl
