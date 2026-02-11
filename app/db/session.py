from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Explicit connection pool configuration for production resilience
engine = create_async_engine(
    settings.DB_URL.replace("psycopg2", "asyncpg"),
    pool_size=20,           # Persistent connections (was default 5)
    max_overflow=30,        # Burst capacity (total max = 50)
    pool_pre_ping=True,     # Health check before each use
    pool_recycle=300,       # Recycle connections every 5 minutes
    echo=False,             # Set True for SQL debugging
)
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session