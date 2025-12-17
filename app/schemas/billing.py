from pydantic import BaseModel, HttpUrl, model_validator

class TopUpRequest(BaseModel):
    cents: int
    
class BillingCheckoutRequest(BaseModel):
    price_id: str | None = None
    amount_cents: int | None = None  # custom amount path
    quantity: int = 1
    currency: str = "USD"
    mode: str = "PAYMENT"  
    billing_customer_id: str | None = None
    auto_topup_enabled: bool = False
    auto_topup_amount_cents: int | None = None
    low_balance_threshold_cents: int | None = None
    success_url: HttpUrl
    cancel_url: HttpUrl

    @model_validator(mode="after")
    def validate_amount_or_price(self):
        if not self.price_id and not self.amount_cents:
            raise ValueError("Either price_id or amount_cents is required.")
        if self.amount_cents is not None and self.amount_cents <= 0:
            raise ValueError("amount_cents must be positive.")
        if self.auto_topup_enabled:
            if not self.auto_topup_amount_cents or self.auto_topup_amount_cents <= 0:
                raise ValueError("auto_topup_amount_cents must be positive when auto_topup_enabled.")
            if self.low_balance_threshold_cents is None or self.low_balance_threshold_cents <= 0:
                raise ValueError("low_balance_threshold_cents must be positive when auto_topup_enabled.")
        return self
