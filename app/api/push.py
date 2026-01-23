import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.db.models import User, Subscription
from app.utils.deps import get_current_user
from app.utils.push import send_push
from app.schemas.push import SubscriptionRequest, SubscriptionResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])

@router.post("/subscribe", response_model=SubscriptionResponse)
async def push_subscribe(
    data: SubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        endpoint = data.endpoint

        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.subscription_json['endpoint'].as_string() == endpoint
            )
        )
        sub = result.scalar_one_or_none()

        if sub:
            sub.subscription_json = data.model_dump()
            await db.commit()
            return {"status": "already subscribed (updated)"}

        sub = Subscription(user_id=user.id, subscription_json=data.model_dump())
        db.add(sub)
        await db.commit()

        return {"status": "subscribed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.exception("Failed to subscribe user %s to push: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to subscribe to push notifications")

@router.post("/send-test")
async def push_send_test(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscriptions = result.scalars().all()
        
        if not subscriptions:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        for sub in subscriptions:
            try:
                await send_push(sub, "Oi lindão, vem conversar comigo! 😘")
            except Exception as e:
                log.warning("Push failed for subscription %s: %s", sub.id, e)

        return {"status": "Notifications sent successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to send test push for user %s: %s", user.id, e)
        raise HTTPException(status_code=500, detail="Failed to send test notification")