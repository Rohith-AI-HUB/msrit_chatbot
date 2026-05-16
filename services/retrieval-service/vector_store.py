from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

from config import settings
from shared.logging import setup_logger


logger = setup_logger("vector_store")


class VectorStoreManager:

    _db = None
    _embedding_model = None

    @classmethod
    def get_embedding_model(cls):
        if cls._embedding_model is None:
            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            cls._embedding_model = HuggingFaceEmbeddings(
                model_name=settings.EMBEDDING_MODEL
            )
        return cls._embedding_model

    @classmethod
    def get_db(cls):
        if cls._db is None:
            logger.info(f"Connecting to ChromaDB: {settings.VECTOR_DB_DIR}")
            cls._db = Chroma(
                persist_directory=settings.VECTOR_DB_DIR,
                embedding_function=cls.get_embedding_model()
            )
            logger.info("Vector DB initialized")
        return cls._db

    @classmethod
    def health_check(cls) -> bool:
        try:
            db = cls.get_db()
            db._collection.count()
            return True
        except Exception as e:
            logger.error(f"Vector DB health check failed: {e}")
            return False

    @classmethod
    def get_document_count(cls) -> int:
        try:
            db = cls.get_db()
            return db._collection.count()
        except Exception:
            return 0
