from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    RETRIEVAL_SERVICE_URL: str = "http://retrieval-service:8001"
    LLM_SERVICE_URL: str = "http://llm-service:8002"
    SESSION_SERVICE_URL: str = "http://session-service:8003"
    REQUEST_TIMEOUT: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
