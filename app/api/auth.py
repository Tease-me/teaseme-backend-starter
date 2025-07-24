import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.db.models import User
from passlib.context import CryptContext
from jose import jwt
from pydantic import BaseModel
from app.schemas.auth import LoginRequest, RegisterRequest

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = User(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        email=data.email
    )
    db.add(user)
    await db.commit()
    return {"ok": True}

@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    username = data.username
    password = data.password

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar()
    if not user or not pwd_context.verify(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = jwt.encode({"sub": str(user.id)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token,username: user.username, "user_id": str(user.id)}