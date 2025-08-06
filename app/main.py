import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router
from app.api.auth import router as auth_router
from app.api.push import router as push_router 
from app.api import billing
from app.api.notify_ws import router as notify_ws_router
from app.api.influencer import router as influencer_router
from app.api.elevenlabs import router as elevenlabs_router

log = logging.getLogger("teaseme")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

origins = [
    "https://localhost:3000",  # frontend dev
    "http://localhost:3000",  # frontend dev
    "https://192.168.68.72:4174",  # frontend dev
    "https://192.168.68.61:3000",  # frontend dev
]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(router)
app.include_router(push_router)
app.include_router(notify_ws_router)
app.include_router(billing.router)
app.include_router(influencer_router)
app.include_router(elevenlabs_router)

@app.get("/health")
def health():
    return {"ok": True}
