import sys
from pathlib import Path

from fastapi import FastAPI

# Add parent directory so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redis_store import RedisStore
from shared.logging import setup_logger
from shared.schemas.chat import AddMessageRequest, SessionHistoryResponse


logger = setup_logger("session-service")

app = FastAPI(title="Session Service", version="1.0.0")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "session",
        "redis": RedisStore.health_check(),
    }


@app.post("/sessions/{session_id}/messages")
def add_message(session_id: str, request: AddMessageRequest):
    RedisStore.add_message(session_id, request.question, request.answer)
    return {"status": "ok"}


@app.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
def get_history(session_id: str):
    messages = RedisStore.get_history(session_id)
    formatted = RedisStore.get_formatted_history(session_id)
    return SessionHistoryResponse(messages=messages, formatted=formatted)


@app.delete("/sessions/{session_id}")
def clear_session(session_id: str):
    RedisStore.clear(session_id)
    return {"status": "ok"}
