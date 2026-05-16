from collections import defaultdict
from typing import List

from langchain_core.documents import Document

from app.core.config import settings
from app.core.logging import setup_logger
from app.db.vector_store import VectorStoreManager


logger = setup_logger("retrieval_service")


class RetrievalService:

    FACTUAL_KEYWORDS = [
        "naac", "nba", "nirf", "ranking", "accreditation",
        "accredited", "fees", "fee", "address", "email",
        "phone", "grade",
    ]

    HOMEPAGE_PENALTY_SOURCES = [
        "https://www.msrit.edu/",
        "https://www.msrit.edu",
        "https://www.msrit.edu/index.html",
    ]

    @staticmethod
    def is_pg_question(question: str) -> bool:
        q = question.lower()
        return any(k in q for k in ["pg", "postgraduate", "post graduate", "m.tech", "mtech", "mba", "mca", "m.arch"])

    @staticmethod
    def is_cse_faculty_question(question: str) -> bool:
        q = question.lower()
        return (
            any(k in q for k in ["faculty", "professor", "teachers"])
            and any(k in q for k in ["cse", "computer science"])
        )

    @classmethod
    def is_factual_query(cls, question: str) -> bool:
        q = question.lower()
        return any(k in q for k in cls.FACTUAL_KEYWORDS)

    @classmethod
    def build_search_query(cls, question: str, rewritten_query: str) -> str:
        q = question.lower()

        if cls.is_cse_faculty_question(question):
            return f"{rewritten_query} MSRIT CSE faculty Computer Science Department Professor Assistant Professor"

        if cls.is_pg_question(question):
            return f"{rewritten_query} MSRIT postgraduate programs M.Tech MBA MCA M.Arch"

        if any(w in q for w in ["department", "departments", "branch", "branches"]):
            return f"{rewritten_query} MSRIT engineering departments"

        return rewritten_query

    @classmethod
    def rerank_documents(cls, docs: List[Document]) -> List[Document]:
        for doc in docs:
            score = doc.metadata.get("score", 0.5)
            source = doc.metadata.get("source", "")
            # Penalty: distance-based scores are lower=better; relevance scores are higher=better
            # Normalize: treat score as relevance (higher=better), invert for sorting
            adjusted = score
            if source in cls.HOMEPAGE_PENALTY_SOURCES:
                adjusted -= 0.08  # penalize by reducing relevance score
            doc.metadata["adjusted_score"] = round(adjusted, 4)

        return sorted(docs, key=lambda x: x.metadata.get("adjusted_score", 0), reverse=True)

    @classmethod
    def keyword_boost(cls, question: str, docs: List[Document]) -> List[Document]:
        q = question.lower()
        accreditation_terms = ["naac", "nba", "accredited", "a+", "ranking", "nirf"]

        for doc in docs:
            content = doc.page_content.lower()
            score = doc.metadata.get("adjusted_score", 0)

            if any(k in q for k in ["naac", "nba", "accreditation", "nirf", "ranking", "grade"]):
                matches = sum(1 for t in accreditation_terms if t in content)
                score += matches * 0.08

            doc.metadata["boosted_score"] = round(score, 4)

        return sorted(docs, key=lambda x: x.metadata.get("boosted_score", 0), reverse=True)

    @classmethod
    def diversify_sources(cls, docs: List[Document]) -> List[Document]:
        grouped = defaultdict(list)
        for doc in docs:
            grouped[doc.metadata.get("source", "unknown")].append(doc)

        diversified = []
        while grouped:
            empty = []
            for source in list(grouped.keys()):
                if grouped[source]:
                    diversified.append(grouped[source].pop(0))
                if not grouped[source]:
                    empty.append(source)
            for s in empty:
                del grouped[s]

        return diversified

    @classmethod
    def retrieve_documents(cls, question: str, rewritten_query: str) -> List[Document]:
        db = VectorStoreManager.get_db()
        search_query = cls.build_search_query(question=question, rewritten_query=rewritten_query)

        logger.info(f"Search query: {search_query}")

        documents = []

        try:
            # =====================================
            # Faculty Retrieval — filtered similarity search (no full db.get() scan)
            # =====================================
            if cls.is_cse_faculty_question(question):
                logger.info("Using faculty filtered retrieval")
                faculty_docs = db.similarity_search(
                    search_query,
                    k=settings.RETRIEVAL_FETCH_K,
                    filter={"source": {"$contains": "faculty"}}
                )
                documents.extend(faculty_docs)

            # =====================================
            # PG Retrieval — targeted similarity search
            # =====================================
            if cls.is_pg_question(question):
                logger.info("Using PG retrieval")
                pg_query = f"{rewritten_query} M.Tech MBA MCA postgraduate master programs"
                pg_docs = db.similarity_search(pg_query, k=settings.RETRIEVAL_FETCH_K)
                # Filter to likely PG content by page_type metadata if available, else keyword filter
                for doc in pg_docs:
                    page_type = doc.metadata.get("page_type", "")
                    content = doc.page_content.lower()
                    if page_type == "postgrad" or any(
                        m.lower() in content
                        for m in ["master of technology", "m.tech", "mba", "mca", "postgraduate"]
                    ):
                        documents.append(doc)

            # =====================================
            # Main Retrieval Strategy
            # =====================================
            use_similarity = cls.is_factual_query(question)
            logger.info(f"Main retrieval strategy: {'similarity' if use_similarity else 'MMR'}")

            semantic_docs = []

            if use_similarity:
                scored_results = db.similarity_search_with_relevance_scores(
                    search_query,
                    k=settings.RETRIEVAL_FETCH_K
                )
                for doc, score in scored_results:
                    logger.info(f"Score={score:.4f} | Source={doc.metadata.get('source')}")
                    doc.metadata["score"] = round(score, 4)
                    semantic_docs.append(doc)

            else:
                # fetch_k must be >> k for MMR to have candidates to select from
                semantic_docs = db.max_marginal_relevance_search(
                    search_query,
                    k=settings.RETRIEVAL_FETCH_K,
                    fetch_k=settings.RETRIEVAL_FETCH_K * 3,
                    lambda_mult=0.6  # 0=max diversity, 1=max relevance; 0.6 balances both
                )

            semantic_docs = cls.rerank_documents(semantic_docs)
            semantic_docs = cls.keyword_boost(question, semantic_docs)
            semantic_docs = cls.diversify_sources(semantic_docs)

            documents.extend(semantic_docs)

            logger.info(f"Documents before deduplication: {len(documents)}")

            # Deduplicate
            seen = set()
            unique_documents = []
            for doc in documents:
                key = (doc.metadata.get("source"), doc.page_content)
                if key not in seen:
                    seen.add(key)
                    unique_documents.append(doc)

            logger.info(f"Final unique documents: {len(unique_documents)}")
            return unique_documents[:settings.RETRIEVAL_TOP_K]

        except Exception as e:
            logger.exception(f"Retrieval failed: {e}")
            return []
