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
    auto_topup_enabled: bool | None = None
    auto_topup_amount_cents: int | None = None
    low_balance_threshold_cents: int | None = None
    success_url: HttpUrl
    cancel_url: HttpUrl

    @model_validator(mode="after")
    def validate_amount_or_price(self):
        mode = (self.mode or "").upper()
        if mode not in {"PAYMENT", "SETUP"}:
            raise ValueError("mode must be PAYMENT or SETUP.")
        self.mode = mode

        if mode == "PAYMENT":
            if not self.price_id and not self.amount_cents:
                raise ValueError("Either price_id or amount_cents is required for PAYMENT mode.")
            if self.amount_cents is not None and self.amount_cents <= 0:
                raise ValueError("amount_cents must be positive.")
        elif self.amount_cents is not None and self.amount_cents <= 0:
            raise ValueError("amount_cents must be positive when provided.")
        if self.auto_topup_amount_cents is not None and self.auto_topup_amount_cents <= 0:
            raise ValueError("auto_topup_amount_cents must be positive when provided.")
        if self.low_balance_threshold_cents is not None and self.low_balance_threshold_cents <= 0:
            raise ValueError("low_balance_threshold_cents must be positive when provided.")
        if self.auto_topup_enabled is True:
            if self.auto_topup_amount_cents is None:
                raise ValueError("auto_topup_amount_cents is required when auto_topup_enabled.")
            if self.low_balance_threshold_cents is None:
                raise ValueError("low_balance_threshold_cents is required when auto_topup_enabled.")
        return self


class AutoTopupCheckRequest(BaseModel):
    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None
    currency: str = "USD"


class TopUpCheckoutRequest(BaseModel):
    amount_cents: int
    currency: str = "USD"
    success_url: HttpUrl
    cancel_url: HttpUrl

    @model_validator(mode="after")
    def validate_amount(self):
        if self.amount_cents <= 0:
            raise ValueError("amount_cents must be positive.")
        self.currency = (self.currency or "USD").upper()
        return self
