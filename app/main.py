import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.chat import router
from app.api.chat_18 import router as chat_18_router
from app.api.auth import router as auth_router
from app.api.push import router as push_router 
from app.api import billing

from app.api.notify_ws import router as notify_ws_router
from app.api.influencer import router as influencer_router
from app.api.influencer_subscriptions import router as influencer_subscriptions_router
from app.api.user import router as user_router
from app.api.elevenlabs import router as elevenlabs_router
from app.api.webhooks import router as webhooks_router

from app.api.follow import router as follow_router
from app.api.pre_influencers import router as pre_influencers_router
from app.api.social import router as social_router
from app.api.admin import router as admin_router
from app.api.relationship import router as relationship_router
from app.api.re_engagement import router as re_engagement_router

from app.api import system_prompts as system_prompts_router

from .api import health_router
from app.scheduler import start_scheduler, stop_scheduler

log = logging.getLogger("teaseme")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

origins_str = os.getenv("CORS_ORIGINS", "")
origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting re-engagement scheduler...")
    start_scheduler()
    
    yield
    
    log.info("Stopping re-engagement scheduler...")
    stop_scheduler()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return a safe JSON response."""
    error_id = str(uuid.uuid4())[:8]
    log.exception("[%s] Unhandled exception on %s %s: %s", error_id, request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": "An unexpected error occurred. Please try again.",
            "error_id": error_id,
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with detailed feedback."""
    error_id = str(uuid.uuid4())[:8]
    log.warning("[%s] Validation error on %s %s: %s", error_id, request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "error": "Validation error",
            "error_id": error_id,
            "details": exc.errors(),
        }
    )

# we cant have this due to need to launch asap 
# @app.exception_handler(StarletteHTTPException)
# async def http_exception_handler(request: Request, exc: StarletteHTTPException):
#     """Handle HTTP exceptions with consistent format."""
#     return JSONResponse(
#         status_code=exc.status_code,
#         content={
#             "ok": False,
#             "error": exc.detail if isinstance(exc.detail, str) else "Request failed",
#             "details": exc.detail if isinstance(exc.detail, dict) else None,
#         }
#     )


app.include_router(auth_router)
app.include_router(router)
app.include_router(chat_18_router)
app.include_router(push_router)
app.include_router(notify_ws_router)
app.include_router(billing.router)
app.include_router(influencer_router)
app.include_router(user_router)
app.include_router(elevenlabs_router)
app.include_router(follow_router)
app.include_router(influencer_subscriptions_router)
app.include_router(health_router.router)
app.include_router(webhooks_router)
app.include_router(system_prompts_router.router)
app.include_router(pre_influencers_router)
app.include_router(social_router)
app.include_router(admin_router)
app.include_router(relationship_router)
app.include_router(re_engagement_router)