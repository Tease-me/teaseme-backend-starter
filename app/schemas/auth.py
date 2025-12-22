from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    password: str
    email: str
    fp_tid: str | None = None

class Token(BaseModel):
    access_token: str
    refresh_token: str

class PasswordResetRequest(BaseModel):
    token: str
    new_password: str
