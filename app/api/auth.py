import secrets
import logging

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.db.session import get_db
from app.db.models import User
from pydantic import BaseModel
from app.schemas.auth import RegisterRequest, LoginRequest, Token, PasswordResetRequest
from app.core.config import settings
from app.utils.deps import get_current_user
from app.utils.email import send_verification_email, send_password_reset_email
from app.utils.auth import create_token
from app.api.notify_ws import notify_email_verified
from app.services.firstpromoter import fp_track_signup
from app.schemas.user import UserOut
from app.utils.s3 import generate_user_presigned_url, save_user_photo_to_s3, delete_file_from_s3
from app.services.follow import create_follow_if_missing
from app.services.influencer import ensure_influencer
from app.utils.rate_limiter import rate_limit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        max_age=access_max_age,
        httponly=settings.ACCESS_TOKEN_HTTPONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        max_age=refresh_max_age,
        httponly=settings.REFRESH_TOKEN_HTTPONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )

def _clear_auth_cookies(response: Response) -> None:
    for name, httponly in (
        (settings.ACCESS_TOKEN_COOKIE_NAME, settings.ACCESS_TOKEN_HTTPONLY),
        (settings.REFRESH_TOKEN_COOKIE_NAME, settings.REFRESH_TOKEN_HTTPONLY),
    ):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=httponly,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            domain=settings.COOKIE_DOMAIN,
            path="/",
        )

@router.get("/check_email")
async def check_email(email: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    return {
        "exists": user is not None,
        "email": email,
    }

@router.post("/register")
@rate_limit(max_requests=settings.RATE_LIMIT_AUTH_MAX, window_seconds=settings.RATE_LIMIT_AUTH_WINDOW, key_prefix="auth:register")
async def register(
    request: Request,
    data: RegisterRequest = Depends(RegisterRequest.as_form),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = File(default=None),
):
    existing_user = await db.execute(
        select(User).where((User.email == data.email))
    )
    if existing_user.scalar():
        raise HTTPException(status_code=200, detail="Username or email already registered")

    if data.influencer_id:
        await ensure_influencer(db, data.influencer_id)

    verify_token = secrets.token_urlsafe(32)           

    user = User(
        password_hash=pwd_context.hash(data.password),
        email=data.email,
        is_verified=False,
        email_token=verify_token,
        full_name=data.full_name,
        username=data.user_name,
        gender=data.gender,
        date_of_birth=data.date_of_birth,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if file:
        try:
            key = await save_user_photo_to_s3(
                file.file,
                file.filename or "profile.jpg",
                file.content_type or "image/jpeg",
                user.id
            )
            user.profile_photo_key = key
            db.add(user)
            try:
                await db.commit()
                await db.refresh(user)
            except Exception:
                await db.rollback()
                try:
                    await delete_file_from_s3(key)
                except Exception:
                    log.warning("Failed to rollback uploaded S3 photo %s", key, exc_info=True)
                raise
        except Exception as e:
            log.error(f"Failed to upload profile photo during registration: {e}", exc_info=True)
            raise HTTPException(500, "Failed to upload profile photo")

    if data.influencer_id:
        await create_follow_if_missing(db, data.influencer_id, user.id)

    try:
        tid = getattr(data, "fp_tid", None) or request.cookies.get("_fprom_tid")

        log.info(
            "FP signup: tid_body=%s tid_cookie=%s chosen=%s",
            getattr(data, "fp_tid", None),
            request.cookies.get("_fprom_tid"),
            tid,
        )

        if tid:
            await fp_track_signup(
                email=user.email,
                uid=str(user.id),
                tid=tid,
            )
    except Exception:
        log.exception("FirstPromoter track/signup failed")
    
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
@rate_limit(max_requests=settings.RATE_LIMIT_AUTH_MAX, window_seconds=settings.RATE_LIMIT_AUTH_WINDOW, key_prefix="auth:login")
async def login(
    request: Request,
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar()

    if not user or not pwd_context.verify(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify Email First")
    
    access_token = create_token(
        {"sub": str(user.id)}, settings.SECRET_KEY, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_token(
        {"sub": str(user.id)}, settings.REFRESH_SECRET_KEY, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    _set_auth_cookies(response, access_token, refresh_token)

    return Token(access_token=access_token, refresh_token=refresh_token)

@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    token_value = refresh_token or request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if not token_value:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(token_value, settings.REFRESH_SECRET_KEY, algorithms=[settings.ALGORITHM])
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

    _set_auth_cookies(response, new_access_token, new_refresh_token)

    return Token(access_token=new_access_token, refresh_token=new_refresh_token)

@router.post("/logout")
async def logout(response: Response) -> dict:
    _clear_auth_cookies(response)
    return {"ok": True, "message": "Logged out"}

@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    user_out = UserOut.model_validate(user)
    if user.profile_photo_key:
        user_out.profile_photo_url = generate_user_presigned_url(user.profile_photo_key)
    return user_out
    
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
@rate_limit(max_requests=3, window_seconds=300, key_prefix="auth:resend-verify")
async def resend_verification_email(request: Request, email: str, db: AsyncSession = Depends(get_db)):
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
@rate_limit(max_requests=3, window_seconds=300, key_prefix="auth:forgot-password")
async def forgot_password(request: Request, email: str, db: AsyncSession = Depends(get_db)):
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
