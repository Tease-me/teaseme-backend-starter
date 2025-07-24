
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import router
from app.api.auth import router as auth_router

origins = [
    "https://localhost:3000",  # frontend dev
    "http://localhost:3000",  # frontend dev
    "https://192.168.68.72:3000",  # frontend dev
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

@app.get("/health")
def health():
    return {"ok": True}
