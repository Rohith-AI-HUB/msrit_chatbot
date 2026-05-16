from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.core.config import settings
from app.core.logging import setup_logger
from app.db.vector_store import VectorStoreManager
from app.services.session_service import SessionService


logger = setup_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MSRIT chatbot backend")
    if not VectorStoreManager.health_check():
        logger.error("Vector DB health check failed")
        raise RuntimeError("Failed to initialize vector DB")
    logger.info("Application startup completed")
    yield
    logger.info("Shutting down backend")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "vector_db": VectorStoreManager.health_check(),
        "redis": SessionService.health_check(),
    }


app.include_router(chat_router, prefix=settings.API_PREFIX)
