from langchain_community.vectorstores import FAISS
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
            logger.info(f"Loading FAISS index: {settings.VECTOR_DB_DIR}")
            cls._db = FAISS.load_local(
                settings.VECTOR_DB_DIR,
                embeddings=cls.get_embedding_model(),
                allow_dangerous_deserialization=True,
            )
            logger.info(
                f"FAISS index loaded — {cls._db.index.ntotal} vectors"
            )
        return cls._db

    @classmethod
    def health_check(cls) -> bool:
        try:
            db = cls.get_db()
            return db.index.ntotal > 0
        except Exception as e:
            logger.error(f"Vector DB health check failed: {e}")
            return False

    @classmethod
    def get_document_count(cls) -> int:
        try:
            db = cls.get_db()
            return db.index.ntotal
        except Exception:
            return 0
