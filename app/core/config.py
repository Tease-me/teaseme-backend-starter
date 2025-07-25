from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_URL: str
    OPENAI_API_KEY: str
    REDIS_URL: str 
    MAX_HISTORY_WINDOW: int
    SCORE_TTL: int
    HISTORY_TTL: int

    secret_key: str
    algorithm: str = "HS256"
    bland_api_key: str
    bland_voice_id: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    vapid_public_key: str
    vapid_private_key: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",extra='ignore' )

settings = Settings()