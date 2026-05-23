from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("vector_store")


class VectorStoreManager:

    _db = None
    _embedding_model = None

    @classmethod
    def get_embedding_model(cls):

        if cls._embedding_model is None:

            logger.info(
                f"Loading embedding model: "
                f"{settings.EMBEDDING_MODEL}"
            )

            cls._embedding_model = HuggingFaceEmbeddings(
                model_name=settings.EMBEDDING_MODEL
            )

        return cls._embedding_model

    @classmethod
    def get_db(cls):

        if cls._db is None:

            logger.info(
                f"Loading FAISS index: "
                f"{settings.VECTOR_DB_DIR}"
            )

            embedding_model = cls.get_embedding_model()

            cls._db = FAISS.load_local(
                str(settings.VECTOR_DB_DIR),
                embeddings=embedding_model,
                allow_dangerous_deserialization=True
            )

            logger.info(
                f"FAISS index loaded — "
                f"{cls._db.index.ntotal} vectors"
            )

        return cls._db

    @classmethod
    def health_check(cls) -> bool:

        try:

            db = cls.get_db()

            return db.index.ntotal > 0

        except Exception as e:

            logger.error(
                f"Vector DB health check failed: {e}"
            )

            return False