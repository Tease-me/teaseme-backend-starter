from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_URL: str
    OPENAI_API_KEY: str
    REDIS_URL: str 
    MAX_HISTORY_WINDOW: int
    SCORE_TTL: int
    HISTORY_TTL: int

    SECRET_KEY: str
    REFRESH_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    ACCESS_TOKEN_HTTPONLY: bool = True
    REFRESH_TOKEN_HTTPONLY: bool = True
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    BLAND_API_KEY: str
    BLAND_VOICE_ID: str
    ELEVENLABS_API_KEY: str
    ELEVEN_BASE_URL: str 
    ELEVENLABS_VOICE_ID: str
    ELEVENLABS_CONVAI_WEBHOOK_SECRET: str | None = None
    
    VAPID_PUBLIC_KEY: str
    VAPID_PRIVATE_KEY: str
    VAPID_EMAIL: str | None = None

    AWS_REGION: str
    SES_SENDER: str
    SES_SERVER: str
    SES_AWS_ACCESS_KEY_ID: str
    SES_AWS_SECRET_ACCESS_KEY: str
    S3_AWS_ACCESS_KEY_ID: str
    S3_AWS_SECRET_ACCESS_KEY: str

    PUBLIC_BASE_URL: str

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1].parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    LANDING_PAGE_AGENT_ID: str
    BUCKET_NAME: str
    INFLUENCER_PREFIX: str
    USER_PREFIX: str = "user-content"  # Default fallback if missing in .env

    TWITTER_BEARER_TOKEN: str | None = None

    PAYPAL_MODE: str | None = None
    PAYPAL_CURRENCY: str | None = None
    PAYPAL_CLIENT_ID: str | None = None
    PAYPAL_CLIENT_SECRET: str | None = None
    PAYPAL_BASE_URL: str | None = None
    PAYPAL_RETURN_URL: str | None = None
    PAYPAL_CANCEL_URL: str | None = None

    FIRSTPROMOTER_TOKEN: str | None = None
    FIRSTPROMOTER_ACCOUNT_ID: str | None = None
    FIRSTPROMOTER_API_KEY: str | None = None
    FIRSTPROMOTER_NOTIFY_EMAIL: str | None = None

settings = Settings()
