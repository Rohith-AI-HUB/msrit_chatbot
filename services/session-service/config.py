from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://redis:6379/0"
    MAX_CHAT_HISTORY: int = 3
    SESSION_TTL: int = 1800  # 30 minutes

    class Config:
        env_file = ".env"


settings = Settings()
