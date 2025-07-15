import os
from fastapi import APIRouter, WebSocket, Depends
from app.agents.engine import handle_turn
from app.db.session import get_db
from app.db.models import Message, User
from jose import jwt
from app.api.utils import get_embedding
from starlette.websockets import WebSocketDisconnect

SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

router = APIRouter()

@router.websocket("/ws/chat/{persona_id}")
async def websocket_chat(ws: WebSocket, persona_id: str, db=Depends(get_db)):
    await ws.accept()
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected from chat/persona={persona_id}")
    except Exception as e:
        await ws.close(code=4002)
        print("JWT decode error:", e)
        return

    while True:
        raw = await ws.receive_json()
        embedding = await get_embedding(raw["message"])

        db.add(Message(
            user_id=user_id,
            persona_id=persona_id,
            sender='user',
            content=raw["message"],
            embedding=embedding
        ))
        await db.commit()
        reply = await handle_turn(
            raw["message"],
            chat_id=raw["chat_id"],
            persona_id=persona_id,
            user_id=user_id,
            db=db
        )
       
        db.add(Message(
            user_id=user_id,
            persona_id=persona_id,
            sender='ai',
            content=reply
        ))
        await db.commit()
        await ws.send_json({"reply": reply})