from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import RegisterRequest, LoginRequest, Token, PasswordResetRequest
from app.core.config import settings
from app.utils.deps import get_current_user
from app.utils.email import send_verification_email, send_password_reset_email
from app.utils.auth import create_token
from app.api.notify_ws import notify_email_verified

import secrets

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(
        select(User).where((User.email == data.email))
    )
    if existing_user.scalar():
        raise HTTPException(status_code=200, detail="Username or email already registered")

    verify_token = secrets.token_urlsafe(32)

    user = User(
        password_hash=pwd_context.hash(data.password),
        email=data.email,
        is_verified=False,
        email_token=verify_token,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    send_verification_email(user.email, verify_token)

    return {
        "ok": True,
        "user_id": user.id,
        "email": user.email,
        "message": "Check your email to verify your account before logging in."
    }

@router.get("/confirm-email")
async def confirm_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    user.is_verified = True
    user.email_token = None
    await db.commit()
   
    await notify_email_verified(user.email)

    return {
        "ok": True,
        "message": "Email verified successfully! You can now log in.",
    }


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
        "is_verified": user.is_verified,
    }
    
@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user.is_verified = True
    user.email_token = None
    await db.commit()
    return {"ok": True, "message": "Email verified! You can now login."}

@router.post("/resend-verification-email")
async def resend_verification_email(email: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    verify_token = secrets.token_urlsafe(32)
    user.email_token = verify_token
    await db.commit()

    send_verification_email(user.email, verify_token)

    return {
        "ok": True,
        "message": "A new verification email has been sent."
    }

@router.post("/forgot-password")
async def forgot_password(email: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        reset_token = secrets.token_urlsafe(32)
        user.password_reset_token = reset_token
        user.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=1)
        await db.commit()

        send_password_reset_email(user.email, reset_token)

    return {"ok": True, "message": "If an account exists, we've sent a reset link."}

@router.post("/reset-password")
async def reset_password(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.password_reset_token == data.token))
    user = result.scalar_one_or_none()

    if not user or user.password_reset_token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token inválido ou expirado.")

    user.password_hash = pwd_context.hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    await db.commit()

    return {"ok": True, "message": "Password updated successfully!"}