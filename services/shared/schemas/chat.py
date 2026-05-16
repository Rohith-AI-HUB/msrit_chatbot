from typing import List, Optional

from pydantic import BaseModel, Field


# === Request/Response for Chat Orchestrator (public API) ===

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(..., min_length=3, max_length=100)
    debug: bool = Field(default=False)


class RetrievedChunk(BaseModel):
    source: str
    preview: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    rewritten_query: Optional[str] = None
    retrieved_documents_count: int
    debug_chunks: Optional[List[RetrievedChunk]] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# === Request/Response for Retrieval Service ===

class SearchRequest(BaseModel):
    question: str
    rewritten_query: str
    top_k: int = 6
    strategy: str = "auto"  # "similarity", "mmr", or "auto"


class DocumentResult(BaseModel):
    content: str
    source: str
    page_type: str
    score: float


class SearchResponse(BaseModel):
    documents: List[DocumentResult]


# === Request/Response for LLM Service ===

class GenerateRequest(BaseModel):
    prompt: str
    temperature: float = 0.0
    model: Optional[str] = None
    task: str = "chat"  # "chat" or "rewrite"


class GenerateResponse(BaseModel):
    content: str
    model: str
    tokens_used: int
    latency_ms: int


class RewriteRequest(BaseModel):
    question: str


class RewriteResponse(BaseModel):
    rewritten_query: str
    original: str


# === Request/Response for Session Service ===

class AddMessageRequest(BaseModel):
    question: str
    answer: str


class SessionHistoryResponse(BaseModel):
    messages: List[dict]
    formatted: str
