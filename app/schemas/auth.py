from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    password: str
    email: str

class Token(BaseModel):
    access_token: str
    refresh_token: str     
