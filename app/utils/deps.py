from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User
from app.db.session import get_db
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_value = token or request.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
    if not token_value:
        raise credentials_exception

    try:
        payload = jwt.decode(token_value, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await db.get(User, int(user_id))
    if user is None:
        raise credentials_exception

    return user
