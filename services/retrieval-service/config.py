from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    VECTOR_DB_DIR: str = "/app/data/chroma_db"
    RETRIEVAL_TOP_K: int = 6
    RETRIEVAL_FETCH_K: int = 20

    class Config:
        env_file = ".env"


settings = Settings()
