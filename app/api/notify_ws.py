from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from jose import JWTError
from app.core.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

router = APIRouter()
notification_sockets = {}

async def notify_email_verified(email: str):
    ws = notification_sockets.get(email)
    if ws:
        try:
            await ws.send_json({"type": "email_verified"})
        except Exception:
            notification_sockets.pop(email, None)

async def notify_low_balance(email: str, balance_cents: int):
    ws = notification_sockets.get(email)
    if ws:
        try:
            await ws.send_json({
                "type": "low_balance",
                "balance_cents": balance_cents,
                "msg": "Balance is low. Top up to continue chatting."
            })
        except Exception:
            notification_sockets.pop(email, None)

@router.websocket("/ws/notifications")
async def websocket_notifications(ws: WebSocket):
    await ws.accept()
    email = ws.query_params.get("email")
    if not email:
        await ws.close(code=4001)
        return
    try:
        notification_sockets[email] = ws

        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        notification_sockets.pop(email, None)
    except JWTError:
        await ws.close(code=4002)
    except Exception:
        notification_sockets.pop(email, None)
        await ws.close(code=4003)