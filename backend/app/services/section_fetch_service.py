"""
SectionFetchService — instant section lookup from a pre-built JSON store.

During ingestion, build_vector_db.py writes section_store.json alongside the
FAISS index.  That file maps every section_id to its complete, ordered text.
This service loads that file once and does O(1) dict lookups — no DB query
needed.

Usage
-----
    from app.services.section_fetch_service import SectionFetchService

    full_text = SectionFetchService.get_best_section_context(retrieved_docs)
    # full_text is the complete section text, or None if section_id is absent.
"""

import json
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("section_fetch_service")

# Path is sibling of the FAISS index directory
_SECTION_STORE_PATH = Path(settings.VECTOR_DB_DIR).parent / "section_store.json"


class SectionFetchService:
    """
    Returns the complete text of a section given its section_id.

    The section store is a JSON file built at ingestion time:
        { "<source_url>::<section_index>": "<full section text>", ... }

    Chunks for each section are already joined in chunk_index order, so
    no sorting or reconstruction is needed at query time.
    """

    _store: Optional[dict] = None

    # ------------------------------------------------------------------ #
    # Store loading (lazy, cached)                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def _get_store(cls) -> dict:
        if cls._store is None:
            if not _SECTION_STORE_PATH.exists():
                logger.warning(
                    f"Section store not found at {_SECTION_STORE_PATH}. "
                    "Rebuild the index to enable full-section fetch."
                )
                cls._store = {}
            else:
                with open(_SECTION_STORE_PATH, "r", encoding="utf-8") as f:
                    cls._store = json.load(f)
                logger.info(
                    f"Section store loaded: {len(cls._store)} sections "
                    f"from {_SECTION_STORE_PATH}"
                )
        return cls._store

    # ------------------------------------------------------------------ #
    # Core fetch                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    def fetch_full_section(cls, section_id: str) -> Optional[str]:
        """
        Return the complete text of *section_id*, or None if not found.

        Args:
            section_id: Value stored in chunk metadata.
                        Format: "<source_url>::<section_index>"
        """
        if not section_id:
            return None

        store = cls._get_store()
        text = store.get(section_id)

        if text:
            logger.info(
                f"section_fetch | id={section_id!r} chars={len(text)}"
            )
        else:
            logger.warning(f"section_id not found in store: {section_id!r}")

        return text

    # ------------------------------------------------------------------ #
    # Pipeline helper                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def get_best_section_context(
        cls,
        documents: List[Document],
    ) -> Optional[str]:
        """
        Find the highest-scoring chunk in *documents*, look up its section_id,
        and return the complete section text.

        Score priority: boosted_score > adjusted_score > score > list order.

        Returns:
            Complete section text, or None when section_id metadata is absent.
        """
        if not documents:
            return None

        def _score(doc: Document) -> float:
            m = doc.metadata
            for key in ("boosted_score", "adjusted_score", "score"):
                v = m.get(key)
                if v is not None:
                    return float(v)
            return 0.0

        # enumerate so equal scores preserve list order (first = best)
        best_doc = max(
            enumerate(documents),
            key=lambda pair: (_score(pair[1]), -pair[0]),
        )[1]

        section_id = best_doc.metadata.get("section_id")
        section_title = best_doc.metadata.get("section_title", "(untitled)")
        source = best_doc.metadata.get("source", "")

        if not section_id:
            logger.info(
                "Best chunk has no section_id — "
                "index was built without section metadata; "
                "skipping section fetch"
            )
            return None

        logger.info(
            f"section_fetch trigger | "
            f"section='{section_title}' source={source}"
        )
        return cls.fetch_full_section(section_id)
