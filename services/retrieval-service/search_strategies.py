from collections import defaultdict
from typing import List

from langchain_core.documents import Document

from config import settings
from shared.logging import setup_logger


logger = setup_logger("search_strategies")


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


def is_pg_question(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in [
        "pg", "postgraduate", "post graduate",
        "m.tech", "mtech", "mba", "mca", "m.arch"
    ])


def is_cse_faculty_question(question: str) -> bool:
    q = question.lower()
    return (
        any(k in q for k in ["faculty", "professor", "teachers"])
        and any(k in q for k in ["cse", "computer science"])
    )


def is_factual_query(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in FACTUAL_KEYWORDS)


def build_search_query(question: str, rewritten_query: str) -> str:
    q = question.lower()

    if is_cse_faculty_question(question):
        return f"{rewritten_query} MSRIT CSE faculty Computer Science Department Professor"

    if is_pg_question(question):
        return f"{rewritten_query} MSRIT postgraduate programs M.Tech MBA MCA M.Arch"

    if any(w in q for w in ["department", "departments", "branch", "branches"]):
        return f"{rewritten_query} MSRIT engineering departments"

    return rewritten_query


def rerank_documents(docs: List[Document]) -> List[Document]:
    for doc in docs:
        score = doc.metadata.get("score", 0.5)
        source = doc.metadata.get("source", "")
        adjusted = score
        if source in HOMEPAGE_PENALTY_SOURCES:
            adjusted -= 0.08
        doc.metadata["adjusted_score"] = round(adjusted, 4)

    return sorted(docs, key=lambda x: x.metadata.get("adjusted_score", 0), reverse=True)


def keyword_boost(question: str, docs: List[Document]) -> List[Document]:
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


def diversify_sources(docs: List[Document]) -> List[Document]:
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
