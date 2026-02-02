from datetime import date

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
    
class Token(BaseModel):
    access_token: str
    refresh_token: str

class PasswordResetRequest(BaseModel):
    token: str
    new_password: str
