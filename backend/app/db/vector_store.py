from langchain_community.vectorstores import Chroma
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
                f"Connecting to ChromaDB: "
                f"{settings.VECTOR_DB_DIR}"
            )

            embedding_model = cls.get_embedding_model()

            cls._db = Chroma(
                persist_directory=str(
                    settings.VECTOR_DB_DIR
                ),
                embedding_function=embedding_model
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

            logger.error(
                f"Vector DB health check failed: {e}"
            )

            return False