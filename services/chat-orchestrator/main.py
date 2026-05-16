import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Add parent directory so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from clients import RetrievalClient, LLMClient, SessionClient
from prompts import build_chat_prompt, build_no_context_response
from shared.logging import setup_logger
from shared.schemas.chat import (
    ChatRequest,
    ChatResponse,
    RetrievedChunk,
    ErrorResponse,
)


logger = setup_logger("chat-orchestrator")

app = FastAPI(
    title="MSRIT Chatbot — Chat Orchestrator",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "chat-orchestrator",
        "downstream": {
            "retrieval": settings.RETRIEVAL_SERVICE_URL,
            "llm": settings.LLM_SERVICE_URL,
            "session": settings.SESSION_SERVICE_URL,
        },
    }


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    responses={500: {"model": ErrorResponse}},
)
def chat(request: ChatRequest):
    request_start = time.time()

    try:
        logger.info(f"Question: {request.question} | session={request.session_id}")

        # ==========================
        # Step 1: Rewrite Query
        # ==========================
        rewrite_start = time.time()
        rewrite_result = LLMClient.rewrite(request.question)
        rewritten_query = rewrite_result["rewritten_query"]
        logger.info(f"Rewrite ({int((time.time()-rewrite_start)*1000)}ms): {rewritten_query}")

        # ==========================
        # Step 2: Retrieve Documents
        # ==========================
        retrieval_start = time.time()
        search_result = RetrievalClient.search(
            question=request.question,
            rewritten_query=rewritten_query,
        )
        documents = search_result["documents"]
        logger.info(f"Retrieval ({int((time.time()-retrieval_start)*1000)}ms): {len(documents)} docs")

        # ==========================
        # Step 3: No Context
        # ==========================
        if not documents:
            logger.warning("No relevant documents found")
            return ChatResponse(
                answer=build_no_context_response(),
                sources=[],
                rewritten_query=rewritten_query,
                retrieved_documents_count=0,
                debug_chunks=[],
            )

        # ==========================
        # Step 4: Build Context
        # ==========================
        context = "\n\n".join([doc["content"] for doc in documents])
        sources = list(set([doc["source"] for doc in documents]))

        # ==========================
        # Step 5: Get Session History
        # ==========================
        history_result = SessionClient.get_history(request.session_id)
        recent_history = history_result["formatted"]

        # ==========================
        # Step 6: Generate Answer
        # ==========================
        prompt = build_chat_prompt(
            question=request.question,
            context=context,
            recent_history=recent_history,
        )

        llm_start = time.time()
        llm_result = LLMClient.generate(prompt=prompt, task="chat")
        answer = llm_result["content"]
        logger.info(f"LLM ({int((time.time()-llm_start)*1000)}ms): {len(answer)} chars")

        # ==========================
        # Step 7: Save to Session
        # ==========================
        SessionClient.add_message(request.session_id, request.question, answer)

        # ==========================
        # Step 8: Build Response
        # ==========================
        total_ms = int((time.time() - request_start) * 1000)
        logger.info(f"Total: {total_ms}ms")

        debug_chunks = None
        if request.debug:
            debug_chunks = [
                RetrievedChunk(
                    source=doc["source"],
                    preview=doc["content"][:300].replace("\n", " ").strip(),
                )
                for doc in documents
            ]

        return ChatResponse(
            answer=answer,
            sources=sources,
            rewritten_query=rewritten_query,
            retrieved_documents_count=len(documents),
            debug_chunks=debug_chunks,
        )

    except Exception as e:
        total_ms = int((time.time() - request_start) * 1000)
        logger.exception(f"Chat failed after {total_ms}ms: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
