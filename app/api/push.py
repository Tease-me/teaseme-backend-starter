import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.db.models import User, Subscription
from passlib.context import CryptContext
from jose import jwt
from pydantic import BaseModel
from app.schemas.auth import LoginRequest, RegisterRequest

router = APIRouter()


@router.post("/push/subscribe")
async def push_subscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = await request.json()
    endpoint = data.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="No endpoint provided")
    exists = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.subscription_json['endpoint'].as_string() == endpoint
        )
    )
    if exists.scalar():
        return {"ok": True}
    sub = Subscription(
        user_id=user.id,
        subscription_json=data
    )
    db.add(sub)
    await db.commit()
    return {"ok": True}