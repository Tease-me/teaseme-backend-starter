from datetime import date

from fastapi import Form
from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    password: str
    email: str
    influencer_id: str | None = None
    full_name: str | None = None
    gender: str | None = None
    user_name: str | None = None
    date_of_birth: date | None = None

    @classmethod
    def as_form(
        cls,
        password: str = Form(...),
        email: str = Form(...),
        influencer_id: str | None = Form(default=None),
        full_name: str | None = Form(default=None),
        gender: str | None = Form(default=None),
        user_name: str | None = Form(default=None),
        date_of_birth: date | None = Form(default=None),
    ) -> "RegisterRequest":
        return cls(
            password=password,
            email=email,
            influencer_id=influencer_id,
            full_name=full_name,
            gender=gender,
            user_name=user_name,
            date_of_birth=date_of_birth,
        )
    
class Token(BaseModel):
    access_token: str
    refresh_token: str

class PasswordResetRequest(BaseModel):
    token: str
    new_password: str
