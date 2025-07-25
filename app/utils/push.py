import os
import json
from pywebpush import webpush, WebPushException
from app.db.models import Subscription
from app.core.config import settings

VAPID_PUBLIC_KEY = settings.VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY = settings.VAPID_PRIVATE_KEY
VAPID_EMAIL = settings.VAPID_EMAIL or "mailto:admin@example.com"

async def send_push(subscription: Subscription, message: str = "Oi! 🥰"):
    try:
        webpush(
            subscription_info=subscription.subscription_json,
            data=json.dumps({"message": message}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        print("[push] ✅ Notification sent successfully.")
    except WebPushException as e:
        print(f"[push] ❌ Error sending notification: {e}")