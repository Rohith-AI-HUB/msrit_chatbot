from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GROQ_API_KEY: str
    LLM_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    LLM_TEMPERATURE: float = 0.0
    REDIS_URL: str = "redis://redis:6379/0"
    CACHE_TTL: int = 3600  # 1 hour

    class Config:
        env_file = ".env"


settings = Settings()
