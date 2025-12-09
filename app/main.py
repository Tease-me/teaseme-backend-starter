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
from app.api.webhooks import router as webhooks_router

from app.api.persona_import import router as persona_import_router
from app.api.influencer_knowledge import router as influencer_knowledge_router

from app.api import system_prompts as system_prompts_router

from .api import health_router
from app.mcp.router import router as mcp_router

log = logging.getLogger("teaseme")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

origins = [
    "https://localhost:3000",  # frontend dev
    "http://localhost:3000",  # frontend dev (non-TLS)
    "http://localhost:4174",
    "https://192.168.68.72:4174",  # frontend dev
    "https://192.168.68.61:3000",  # frontend dev
    "https://localhost:4174",
    "http://192.168.68.72:4174",
    "http://192.168.68.61:3000",
    "https://teaseme.mxjprod.work",
    "https://api.teaseme.live",
    "https://teaseme.live",
]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
app.include_router(push_router)
app.include_router(notify_ws_router)
app.include_router(billing.router)
app.include_router(influencer_router)
app.include_router(elevenlabs_router)
app.include_router(health_router.router)
app.include_router(persona_import_router)
app.include_router(webhooks_router)
app.include_router(mcp_router)
app.include_router(influencer_knowledge_router)
app.include_router(system_prompts_router.router)
