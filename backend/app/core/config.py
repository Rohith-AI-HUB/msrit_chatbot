from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):

    # App
    APP_NAME: str = "MSRIT Chatbot"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # API
    API_PREFIX: str = "/api"

    # LLM
    GROQ_API_KEY: str
    LLM_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT: int = 30

    # Embeddings — upgraded from all-MiniLM-L6-v2
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # Vector DB
    VECTOR_DB_DIR: Path = BASE_DIR / "data" / "chroma_db"

    # Data Files
    RAW_DATA_PATH: Path = BASE_DIR / "data" / "msrit_full.txt"
    SUPPLEMENT_DATA_PATH: Path = BASE_DIR / "data" / "msrit_supplement.txt"

    # Retrieval — increased chunk quality + fetch window
    RETRIEVAL_TOP_K: int = 6
    RETRIEVAL_FETCH_K: int = 20

    # Chunking — larger chunks for coherent university page content
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150

    # Session Memory — keep 3 turns only to avoid prompt bloat
    MAX_CHAT_HISTORY: int = 3

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Crawling
    MAX_CRAWL_PAGES: int = 50
    REQUEST_TIMEOUT: int = 15

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
