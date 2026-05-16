from pydantic import BaseModel
from pydantic import Field


class ChatRequest(BaseModel):

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User question"
    )

    session_id: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Unique session identifier"
    )

    debug: bool = Field(
        default=False,
        description="Enable retrieval debugging"
    )