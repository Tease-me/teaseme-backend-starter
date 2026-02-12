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


async def require_age_verification(
    user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to ensure user has verified their age (18+) before accessing adult content.
    
    Age verification can be satisfied by:
    - Explicit age verification (is_age_verified=True)
    - Full identity verification with level "full" or "premium"
    
    Raises:
        HTTPException: 403 if user is not age-verified
    """
    # Check if user has age verification
    is_verified = user.is_age_verified or (
        user.is_identity_verified and user.verification_level in ["full", "premium"]
    )
    
    if not is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "AGE_VERIFICATION_REQUIRED",
                "message": "You must verify your age (18+) to access this content. Please complete identity verification.",
                "verification_status": {
                    "is_age_verified": user.is_age_verified,
                    "is_identity_verified": user.is_identity_verified,
                    "verification_level": user.verification_level,
                }
            }
        )
    
    return user
