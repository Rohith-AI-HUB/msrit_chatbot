import sys
from pathlib import Path

from fastapi import FastAPI

# Add parent directory so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redis_store import RedisStore
from shared.logging import setup_logger
from shared.schemas.chat import AddMessageRequest, SessionHistoryResponse, SetFlowStateRequest, FlowStateResponse


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


# ── Portal Flow State ─────────────────────────────────────────────────────────

@app.get("/sessions/{session_id}/flow", response_model=FlowStateResponse)
def get_flow_state(session_id: str):
    state = RedisStore.get_flow_state(session_id)
    return FlowStateResponse(state=state)


@app.put("/sessions/{session_id}/flow")
def set_flow_state(session_id: str, request: SetFlowStateRequest):
    RedisStore.set_flow_state(session_id, request.state)
    return {"status": "ok"}


@app.delete("/sessions/{session_id}/flow")
def clear_flow_state(session_id: str):
    RedisStore.clear_flow_state(session_id)
    return {"status": "ok"}
