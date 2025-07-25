from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str

class Token(BaseModel):
    access_token: str
    refresh_token: str     
