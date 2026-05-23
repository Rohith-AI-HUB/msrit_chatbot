from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    RETRIEVAL_SERVICE_URL: str = "http://retrieval-service:8001"
    LLM_SERVICE_URL: str = "http://llm-service:8002"
    SESSION_SERVICE_URL: str = "http://session-service:8003"
    PARENTS_SERVICE_URL: str = "http://parents-service:8004"
    REQUEST_TIMEOUT: int = 30
    PARENTS_PORTAL_TIMEOUT: int = 60   # parents portal scrape can take ~30s

    class Config:
        env_file = ".env"


settings = Settings()
