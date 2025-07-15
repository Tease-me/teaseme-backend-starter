
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/teaseme"

settings = Settings()
