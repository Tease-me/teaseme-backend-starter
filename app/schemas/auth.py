from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False

class RegisterRequest(BaseModel):
    password: str
    email: str

class Token(BaseModel):
    access_token: str
    refresh_token: str

class PasswordResetRequest(BaseModel):
    token: str
    new_password: str
