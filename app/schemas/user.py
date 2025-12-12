from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime, timezone
class UserBase(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    email: Optional[str] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[datetime] = None

class UserRead(UserBase):
    id: int
    email: str
    username: Optional[str] = None
    profile_photo_url: Optional[str] = None
    is_verified: bool
    
    class Config:
        from_attributes = True

# Alias for backward compatibility or clarity
UserOut = UserRead