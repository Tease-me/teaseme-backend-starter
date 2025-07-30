from datetime import datetime, timedelta, timezone
from jose import jwt
from app.core.config import settings

def create_token(data: dict, secret: str, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=settings.ALGORITHM)