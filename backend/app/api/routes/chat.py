from fastapi import APIRouter
from fastapi import HTTPException

import time

from app.core.logging import setup_logger

from app.schemas.chat import ChatRequest

from app.schemas.response import (
    ChatResponse,
    ErrorResponse,
    RetrievedChunk
)

from app.services.query_rewriter_service import (
    QueryRewriterService
)

from app.services.retrieval_service import (
    RetrievalService
)

from app.services.llm_service import (
    LLMService
)

from app.services.session_service import (
    SessionService
)

from app.services.result_service import (
    ResultService
)

from app.services.section_fetch_service import (
    SectionFetchService
)

from app.utils.prompts import (
    build_chat_prompt,
    build_no_context_response
)


logger = setup_logger("chat_route")

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        500: {
            "model": ErrorResponse
        }
    }
)
def chat(
    request: ChatRequest
):

    request_start = time.time()

    try:

        logger.info(
            f"Received chat request | "
            f"session_id={request.session_id}"
        )

        logger.info(
            f"Question: {request.question}"
        )

        # =========================
        # Result Flow (before RAG)
        # =========================
        result_response = ResultService.handle(
            session_id=request.session_id,
            question=request.question
        )
        if result_response is not None:
            SessionService.add_message(
                session_id=request.session_id,
                question=request.question,
                answer=result_response
            )
            return ChatResponse(
                answer=result_response,
                sources=[],
                rewritten_query="",
                retrieved_documents_count=0,
                debug_chunks=[]
            )

        # =========================
        # Session History (needed before rewrite)
        # =========================
        recent_history = (
            SessionService.get_recent_history(
                request.session_id
            )
        )

        # =========================
        # Rewrite Query
        # =========================
        rewrite_start = time.time()

        rewritten_query = (
            QueryRewriterService.rewrite_query(
                request.question,
                recent_history=recent_history
            )
        )

        rewrite_time = (
            time.time() - rewrite_start
        )

        logger.info(
            f"Rewrite completed in "
            f"{rewrite_time:.2f}s"
        )

        logger.info(
            f"Rewritten query: "
            f"{rewritten_query}"
        )

        # =========================
        # Retrieve Documents
        # =========================
        retrieval_start = time.time()

        documents = (
            RetrievalService.retrieve_documents(
                question=request.question,
                rewritten_query=rewritten_query
            )
        )

        retrieval_time = (
            time.time() - retrieval_start
        )

        logger.info(
            f"Retrieval completed in "
            f"{retrieval_time:.2f}s"
        )

        logger.info(
            f"Retrieved {len(documents)} "
            f"documents"
        )

        # =========================
        # No Context Found
        # =========================
        if not documents:

            logger.warning(
                "No relevant documents found"
            )

            total_time = (
                time.time() - request_start
            )

            logger.info(
                f"Request completed in "
                f"{total_time:.2f}s"
            )

            return ChatResponse(
                answer=build_no_context_response(),
                sources=[],
                rewritten_query=rewritten_query,
                retrieved_documents_count=0,
                debug_chunks=[]
            )

        # =========================
        # Section Fetch (full section for best chunk)
        # =========================
        full_section = SectionFetchService.get_best_section_context(documents)

        # =========================
        # Build Context
        # =========================
        if full_section:
            # Find which section_id the full_section belongs to so we can
            # avoid repeating those chunk texts verbatim in the context.
            def _score(doc):
                m = doc.metadata
                for k in ("boosted_score", "adjusted_score", "score"):
                    v = m.get(k)
                    if v is not None:
                        return float(v)
                return 0.0
            best_section_id = max(
                enumerate(documents),
                key=lambda p: (_score(p[1]), -p[0]),
            )[1].metadata.get("section_id")

            other_chunks = "\n\n".join(
                doc.page_content
                for doc in documents
                if doc.metadata.get("section_id") != best_section_id
            )

            context = "[Complete Section]\n" + full_section
            if other_chunks:
                context += "\n\n---\n\n" + other_chunks
        else:
            context = "\n\n".join([
                doc.page_content
                for doc in documents
            ])

        sources = list(set([
            doc.metadata.get(
                "source",
                "Unknown"
            )
            for doc in documents
        ]))

        # =========================
        # Retrieval Transparency
        # =========================
        logger.info(
            "Retrieved document previews:"
        )

        for index, doc in enumerate(
            documents,
            start=1
        ):

            preview = (
                doc.page_content[:250]
                .replace("\n", " ")
                .strip()
            )

            logger.info(
                f"[DOC {index}] "
                f"source="
                f"{doc.metadata.get('source')} "
                f"| preview={preview}"
            )

        # =========================
        # Debug Mode
        # =========================
        debug_chunks = None

        if request.debug:

            logger.info(
                "Debug mode enabled"
            )

            debug_chunks = []

            for doc in documents:

                preview = (
                    doc.page_content[:300]
                    .replace("\n", " ")
                    .strip()
                )

                debug_chunks.append(
                    RetrievedChunk(
                        source=doc.metadata.get(
                            "source",
                            "Unknown"
                        ),
                        preview=preview
                    )
                )

        logger.info(
            f"Recent history length: "
            f"{len(recent_history)}"
        )

        # =========================
        # Build Prompt
        # =========================
        prompt = build_chat_prompt(
            question=request.question,
            context=context,
            recent_history=recent_history
        )

        logger.info(
            f"Context length: "
            f"{len(context)} characters"
        )

        logger.info(
            "Generating LLM response"
        )

        # =========================
        # Generate Response
        # =========================
        llm_start = time.time()

        answer = (
            LLMService.generate_response(
                prompt=prompt
            )
        )

        llm_time = (
            time.time() - llm_start
        )

        logger.info(
            f"LLM response generated in "
            f"{llm_time:.2f}s"
        )

        logger.info(
            f"Answer length: "
            f"{len(answer)} characters"
        )

        # =========================
        # Save Conversation
        # =========================
        SessionService.add_message(
            session_id=request.session_id,
            question=request.question,
            answer=answer
        )

        total_time = (
            time.time() - request_start
        )

        logger.info(
            f"Total request completed in "
            f"{total_time:.2f}s"
        )

        logger.info(
            "Chat request completed successfully"
        )

        return ChatResponse(
            answer=answer,
            sources=sources,
            rewritten_query=rewritten_query,
            retrieved_documents_count=len(
                documents
            ),
            debug_chunks=debug_chunks
        )

    except Exception as e:

        total_time = (
            time.time() - request_start
        )

        logger.exception(
            f"Chat route failed after "
            f"{total_time:.2f}s | {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Internal server error"
            )
        )