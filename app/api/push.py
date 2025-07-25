import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.db.models import User, Subscription

router = APIRouter()



#TODO# WRONG PLACE
from pywebpush import webpush, WebPushException
from app.core.config import settings
from app.db.models import Subscription
import json

async def send_push(subscription: Subscription, message="Tô morrendo de saudades! 🥰"):
    try:
        webpush(
            subscription_info=subscription.subscription_json,
            data=json.dumps({"message": message}),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": "mailto:seuemail@example.com"},
        )
    except WebPushException as ex:
        print(f"Erro ao enviar push: {ex}")

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

@router.post("/push/send-test")
async def push_send_test(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    await send_push(subscription, "Oi lindão, vem conversar comigo! 😘")
    return {"status": "Notificação enviada com sucesso!"}