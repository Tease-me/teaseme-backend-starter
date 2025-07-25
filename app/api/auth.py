import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import RegisterRequest, LoginRequest, Token
from app.core.config import settings
from app.api.deps import get_current_user

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_token(data: dict, secret: str, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=settings.ALGORITHM)

@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(select(User).where(User.email == data.email))
    if existing_user.scalar():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        email=data.email
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"ok": True, "user_id": user.id, "email": user.email}

@router.post("/login", response_model=Token)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar()
    if not user or not pwd_context.verify(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    access_token = create_token(
        {"sub": str(user.id)}, settings.SECRET_KEY, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_token(
        {"sub": str(user.id)}, settings.REFRESH_SECRET_KEY, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    return Token(
        access_token=access_token,
        refresh_token=refresh_token
    )

@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(refresh_token, settings.REFRESH_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_access_token = create_token(
        {"sub": str(user.id)}, settings.SECRET_KEY, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    new_refresh_token = create_token(
        {"sub": str(user.id)}, settings.REFRESH_SECRET_KEY, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token
    )

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }