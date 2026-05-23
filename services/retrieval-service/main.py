import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Add parent directory so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from vector_store import VectorStoreManager
from search_strategies import (
    is_pg_question,
    is_cse_faculty_question,
    is_factual_query,
    build_search_query,
    rerank_documents,
    keyword_boost,
    diversify_sources,
)
from shared.logging import setup_logger
from shared.schemas.chat import SearchRequest, SearchResponse, DocumentResult


logger = setup_logger("retrieval-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Retrieval Service")
    if not VectorStoreManager.health_check():
        logger.error("Vector DB health check failed")
        raise RuntimeError("Failed to initialize vector DB")
    logger.info(f"Vector DB ready — {VectorStoreManager.get_document_count()} documents")
    yield
    logger.info("Shutting down Retrieval Service")


app = FastAPI(title="Retrieval Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "retrieval",
        "document_count": VectorStoreManager.get_document_count(),
    }


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    db = VectorStoreManager.get_db()
    search_query = build_search_query(request.question, request.rewritten_query)

    logger.info(f"Search query: {search_query}")

    documents = []

    # Faculty-specific retrieval
    if is_cse_faculty_question(request.question):
        logger.info("Using faculty filtered retrieval")
        raw_faculty = db.similarity_search(
            search_query,
            k=settings.RETRIEVAL_FETCH_K * 3,
        )
        faculty_docs = [
            d for d in raw_faculty
            if "faculty" in d.metadata.get("source", "").lower()
        ][:settings.RETRIEVAL_FETCH_K]
        documents.extend(faculty_docs)

    # PG-specific retrieval
    if is_pg_question(request.question):
        logger.info("Using PG retrieval")
        pg_query = f"{request.rewritten_query} M.Tech MBA MCA postgraduate master programs"
        pg_docs = db.similarity_search(pg_query, k=settings.RETRIEVAL_FETCH_K)
        for doc in pg_docs:
            page_type = doc.metadata.get("page_type", "")
            content = doc.page_content.lower()
            if page_type == "postgrad" or any(
                m.lower() in content
                for m in ["master of technology", "m.tech", "mba", "mca", "postgraduate"]
            ):
                documents.append(doc)

    # Main retrieval strategy
    use_similarity = is_factual_query(request.question)
    logger.info(f"Strategy: {'similarity' if use_similarity else 'MMR'}")

    semantic_docs = []

    if use_similarity:
        scored_results = db.similarity_search_with_relevance_scores(
            search_query, k=settings.RETRIEVAL_FETCH_K
        )
        for doc, score in scored_results:
            doc.metadata["score"] = round(score, 4)
            semantic_docs.append(doc)
    else:
        semantic_docs = db.max_marginal_relevance_search(
            search_query,
            k=settings.RETRIEVAL_FETCH_K,
            fetch_k=settings.RETRIEVAL_FETCH_K * 3,
            lambda_mult=0.6,
        )

    semantic_docs = rerank_documents(semantic_docs)
    semantic_docs = keyword_boost(request.question, semantic_docs)
    semantic_docs = diversify_sources(semantic_docs)

    documents.extend(semantic_docs)

    # Deduplicate
    seen = set()
    unique = []
    for doc in documents:
        key = (doc.metadata.get("source"), doc.page_content)
        if key not in seen:
            seen.add(key)
            unique.append(doc)

    final_docs = unique[:request.top_k]
    logger.info(f"Returning {len(final_docs)} documents")

    return SearchResponse(
        documents=[
            DocumentResult(
                content=doc.page_content,
                source=doc.metadata.get("source", "Unknown"),
                page_type=doc.metadata.get("page_type", "general"),
                score=doc.metadata.get("boosted_score",
                       doc.metadata.get("adjusted_score",
                       doc.metadata.get("score", 0.5))),
            )
            for doc in final_docs
        ]
    )
