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


async def send_push_rich(
    subscription: Subscription,
    title: str,
    body: str,
    image_url: str | None = None,
    action_url: str | None = None,
    influencer_id: str | None = None,
    badge_url: str | None = None,
):

    payload = {
        "title": title,
        "body": body,
        "tag": f"reengagement-{influencer_id}" if influencer_id else "reengagement",
    }

    if image_url:
        payload["image"] = image_url

    if action_url:
        payload["url"] = action_url
    elif influencer_id:
        payload["url"] = f"/chat/{influencer_id}"

    if badge_url:
        payload["badge"] = badge_url

    try:
        webpush(
            subscription_info=subscription.subscription_json,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        print(f"[push] ✅ Rich notification sent: {title}")
    except WebPushException as e:
        print(f"[push] ❌ Error sending rich notification: {e}")
        raise