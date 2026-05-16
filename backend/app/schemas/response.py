from typing import List
from typing import Optional

from pydantic import BaseModel


class RetrievedChunk(BaseModel):

    source: str

    preview: str


class ChatResponse(BaseModel):

    answer: str

    sources: List[str]

    rewritten_query: Optional[str] = None

    retrieved_documents_count: int

    debug_chunks: Optional[
        List[RetrievedChunk]
    ] = None


class ErrorResponse(BaseModel):

    error: str

    detail: Optional[str] = None