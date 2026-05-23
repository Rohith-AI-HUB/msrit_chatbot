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
        "phone", "grade", "hostel", "mess",
        "placement", "package", "lpa", "salary", "companies",
        "department", "departments", "branch", "branches",
    ]

    HOMEPAGE_PENALTY_SOURCES = [
        "https://www.msrit.edu/",
        "https://www.msrit.edu",
        "https://www.msrit.edu/index.html",
    ]

    @staticmethod
    def is_ug_question(question: str) -> bool:
        q = question.lower()
        return any(k in q for k in ["ug", "undergraduate", "under graduate", "b.e", "be ", "bachelor", "b.arch", "barch"])

    @staticmethod
    def is_pg_question(question: str) -> bool:
        q = question.lower()
        return any(k in q for k in ["pg", "postgraduate", "post graduate", "m.tech", "mtech", "mba", "mca", "m.arch"])

    @staticmethod
    def is_cse_faculty_question(question: str) -> bool:
        q = question.lower()
        hod_terms = ["hod", "head of department", "head of dept", "head of the department"]
        faculty_terms = ["faculty", "professor", "teachers"]
        dept_terms = ["cse", "computer science"]
        return (
            any(k in q for k in faculty_terms + hod_terms)
            and any(k in q for k in dept_terms)
        )

    @staticmethod
    def is_main_cse_hod_question(question: str) -> bool:
        """True when asking about HOD of main CSE (not AI&ML or Cyber Security sub-depts)."""
        q = question.lower()
        is_hod = any(k in q for k in ["hod", "head of department", "head of dept", "head of the department", "head"])
        is_cse = any(k in q for k in ["cse", "computer science"])
        is_subdept = any(k in q for k in ["ai&ml", "ai ml", "artificial intelligence", "cyber security", "cybersecurity"])
        return is_hod and is_cse and not is_subdept

    @staticmethod
    def is_placement_question(question: str) -> bool:
        q = question.lower()
        return any(k in q for k in [
            "placement", "placements", "placed", "recruit", "package",
            "salary", "lpa", "company", "companies", "job offer", "campus"
        ])

    @staticmethod
    def is_department_question(question: str) -> bool:
        q = question.lower()
        return any(k in q for k in [
            "department", "departments", "branch", "branches",
            "all courses", "all programs", "all departments"
        ])

    @classmethod
    def is_factual_query(cls, question: str) -> bool:
        q = question.lower()
        return any(k in q for k in cls.FACTUAL_KEYWORDS)

    @classmethod
    def build_search_query(cls, question: str, rewritten_query: str) -> str:
        q = question.lower()

        if cls.is_main_cse_hod_question(question):
            return f"{rewritten_query} Head of Department HOD CSE Computer Science Dr R China Appala Naidu MSRIT"

        if cls.is_cse_faculty_question(question):
            return f"{rewritten_query} MSRIT CSE faculty Computer Science Department Professor Assistant Professor"

        if any(w in q for w in ["hostel", "accommodation", "mess", "dormitory"]):
            return f"{rewritten_query} MSRIT hostel accommodation fee charges mess"

        if cls.is_pg_question(question):
            return f"{rewritten_query} MSRIT postgraduate programs M.Tech MBA MCA M.Arch"

        if cls.is_ug_question(question):
            return f"{rewritten_query} MSRIT undergraduate Bachelor of Engineering B.E. B.Arch programs courses"

        if any(w in q for w in ["department", "departments", "branch", "branches"]):
            return f"{rewritten_query} MSRIT engineering departments"

        if any(w in q for w in ["fee", "fees", "tuition", "cost", "charges"]):
            return f"{rewritten_query} MSRIT fee structure tuition charges"

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
        hostel_terms = ["hostel", "accommodation", "mess", "single", "double", "bed", "room"]
        fee_terms = ["fee", "tuition", "charges", "amount", "rs.", "₹", "lakh", "per year"]
        placement_terms = ["placement", "lpa", "package", "companies", "offers", "recruit", "salary"]
        department_terms = ["department", "engineering", "b.e.", "bachelor", "program", "branch"]

        for doc in docs:
            content = doc.page_content.lower()
            source = doc.metadata.get("source", "").lower()
            page_type = doc.metadata.get("page_type", "")
            score = doc.metadata.get("adjusted_score", 0)

            if any(k in q for k in ["naac", "nba", "accreditation", "nirf", "ranking", "grade"]):
                matches = sum(1 for t in accreditation_terms if t in content)
                score += matches * 0.08

            if any(k in q for k in ["hostel", "accommodation", "mess"]):
                matches = sum(1 for t in hostel_terms if t in content)
                score += matches * 0.06
                if "hostel" in source:
                    score += 0.15

            if any(k in q for k in ["fee", "fees", "tuition", "charges", "cost"]):
                matches = sum(1 for t in fee_terms if t in content)
                score += matches * 0.05
                if page_type in ("fees", "admissions"):
                    score += 0.12

            if any(k in q for k in ["placement", "package", "salary", "lpa", "company", "companies", "recruit", "job"]):
                matches = sum(1 for t in placement_terms if t in content)
                score += matches * 0.07
                if page_type == "placements" or "placement" in source:
                    score += 0.20  # strongly prefer the placement page

            if any(k in q for k in ["department", "departments", "branch", "branches", "programs", "courses"]):
                matches = sum(1 for t in department_terms if t in content)
                score += matches * 0.04
                if page_type == "department" or "department" in source or "departments-overview" in source:
                    score += 0.15

            # HOD of CSE boost — strongly prefer hod-profiles page and main cse sources
            if any(k in q for k in ["hod", "head of department", "head of dept"]) and any(k in q for k in ["cse", "computer science"]):
                if "hod-profiles" in source:
                    score += 0.40
                elif "cse" in source and "cse_ai" not in source and "cse_cs" not in source:
                    score += 0.20
                elif "cse_ai" in source or "cse_cs" in source:
                    score -= 0.15  # penalize sub-dept sources for main CSE HOD query

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
            # HOD of CSE (main dept) — strongly prefer hod-profiles and cse.html
            # =====================================
            if cls.is_main_cse_hod_question(question):
                logger.info("Using main CSE HOD retrieval")
                hod_query = "Head of Department HOD CSE Computer Science Dr R China Appala Naidu MSRIT"
                raw_hod = db.similarity_search(hod_query, k=settings.RETRIEVAL_FETCH_K * 3)
                # Prefer hod-profiles page, then cse.html sources; exclude ai_ml/cs sub-dept sources
                hod_docs = [
                    d for d in raw_hod
                    if "hod-profiles" in d.metadata.get("source", "").lower()
                    or (
                        "cse" in d.metadata.get("source", "").lower()
                        and "cse_ai" not in d.metadata.get("source", "").lower()
                        and "cse_cs" not in d.metadata.get("source", "").lower()
                    )
                ][:settings.RETRIEVAL_FETCH_K]
                documents.extend(hod_docs)

            # =====================================
            # Faculty Retrieval — filtered similarity search (no full db.get() scan)
            # =====================================
            if cls.is_cse_faculty_question(question) and not cls.is_main_cse_hod_question(question):
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

            # =====================================
            # UG Retrieval — targeted similarity search
            # =====================================
            if cls.is_ug_question(question):
                logger.info("Using UG retrieval")
                ug_query = f"{rewritten_query} Bachelor of Engineering B.E. undergraduate programs courses"
                ug_docs = db.similarity_search(ug_query, k=settings.RETRIEVAL_FETCH_K)
                for doc in ug_docs:
                    content = doc.page_content.lower()
                    if any(
                        m in content
                        for m in ["bachelor of engineering", "b.e.", "b.arch", "undergraduate", "four years"]
                    ):
                        documents.append(doc)

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
            # Placement Retrieval
            # =====================================
            if cls.is_placement_question(question):
                logger.info("Using placement retrieval")
                placement_query = f"{rewritten_query} MSRIT placement statistics companies package salary LPA offers"
                raw_placement = db.similarity_search(placement_query, k=settings.RETRIEVAL_FETCH_K * 2)
                placement_docs = [
                    d for d in raw_placement
                    if d.metadata.get("page_type") == "placements"
                    or "placement" in d.metadata.get("source", "").lower()
                    or any(t in d.page_content.lower() for t in ["lpa", "package", "companies visited", "job offers"])
                ][:settings.RETRIEVAL_FETCH_K]
                documents.extend(placement_docs)

            # =====================================
            # Department Retrieval
            # =====================================
            if cls.is_department_question(question):
                logger.info("Using department retrieval")
                dept_query = f"{rewritten_query} MSRIT departments programs engineering courses offered"
                raw_dept = db.similarity_search(dept_query, k=settings.RETRIEVAL_FETCH_K * 2)
                dept_docs = [
                    d for d in raw_dept
                    if d.metadata.get("page_type") == "department"
                    or "department" in d.metadata.get("source", "").lower()
                    or "departments-overview" in d.metadata.get("source", "").lower()
                ][:settings.RETRIEVAL_FETCH_K]
                documents.extend(dept_docs)

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
