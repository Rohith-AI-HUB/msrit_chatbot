from pathlib import Path
import json
import re
import shutil
import uuid

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("build_vector_db")


def infer_page_type(source_url: str) -> str:
    url = source_url.lower()
    if "faculty" in url:
        return "faculty"
    if any(k in url for k in ["pg", "postgrad", "mtech", "m-tech", "mba", "mca"]):
        return "postgrad"
    if any(k in url for k in ["fee", "fees", "tuition"]):
        return "fees"
    if any(k in url for k in ["placement", "career", "recruit"]):
        return "placements"
    if any(k in url for k in ["hostel", "accommodation"]):
        return "hostel"
    if any(k in url for k in ["naac", "nba", "accreditation", "nirf"]):
        return "accreditation"
    return "general"


class VectorDBBuilder:

    def __init__(self):
        self.embedding_model = HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP
        )

    def load_raw_text(self) -> str:
        data_path = Path(settings.RAW_DATA_PATH)
        if not data_path.exists():
            raise FileNotFoundError(f"Raw data file not found: {data_path}")
        logger.info(f"Loading raw data from: {data_path}")
        with open(data_path, "r", encoding="utf-8") as f:
            return f.read()

    # ------------------------------------------------------------------
    # Section detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_heading(line: str) -> bool:
        """
        Heuristic: returns True if the line looks like a section heading.
        Designed for university website content scraped to plain text.
        """
        if not line or len(line) < 3 or len(line) > 90:
            return False
        # Skip lines ending with content punctuation — those are sentences
        if line[-1] in '.,:;':
            return False
        # Skip table rows / dividers
        if '|' in line or line.startswith('---') or line.startswith('==='):
            return False

        words = line.split()
        if not words:
            return False

        alpha_only = re.sub(r'[^a-zA-Z]', '', line)
        if len(alpha_only) < 3:
            return False

        # Pattern 1 — all uppercase: "ABOUT US", "FEE STRUCTURE", "VISION"
        if alpha_only == alpha_only.upper():
            return True

        # Pattern 2 — numbered section: "1. Overview", "2) Introduction"
        if re.match(r'^\d+[.)]\s+[A-Z][a-z]', line):
            return True

        # Pattern 3 — title case: 2-8 words, ≥70% capitalized, first word cap
        if 2 <= len(words) <= 8 and words[0][0].isupper():
            minor = {'a', 'an', 'the', 'in', 'on', 'at', 'of', 'for', 'and', 'or', 'to', 'by', 'with'}
            cap_count = sum(
                1 for i, w in enumerate(words)
                if w and (w[0].isupper() or (w.lower() in minor and i > 0))
            )
            if cap_count / len(words) >= 0.7:
                return True

        return False

    def split_into_sections(self, content: str) -> list[tuple[str, str]]:
        """
        Split page content into (section_title, section_body) pairs.

        Each heading line starts a new section.  The body before the first
        heading (if any) is kept under an empty title string.  If no headings
        are detected the whole page is returned as a single section.
        """
        lines = content.split('\n')
        sections: list[tuple[str, str]] = []
        current_title = ""
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if self._is_heading(stripped):
                body = '\n'.join(current_lines).strip()
                if body:
                    sections.append((current_title, body))
                current_title = stripped
                current_lines = []
            else:
                current_lines.append(line)

        # Flush last section
        body = '\n'.join(current_lines).strip()
        if body:
            sections.append((current_title, body))

        # Fallback: whole page as one section
        if not sections:
            sections = [("", content)]

        return sections

    # ------------------------------------------------------------------
    # Document parsing — section-aware
    # ------------------------------------------------------------------

    def parse_documents(self, text: str) -> list[Document]:
        """
        Parse msrit_full.txt into section-level Documents.

        Each document represents one detected section of a crawled page.
        Metadata keys added:
          - source        : page URL
          - page_type     : inferred category (fees, faculty, …)
          - section_title : detected heading text (may be empty for page intro)
          - section_id    : stable "<source>::<section_index>" key
          - section_index : position of the section within the page
        """
        logger.info("Parsing crawled pages into sections")
        raw_pages = text.split("PAGE_URL:")
        documents = []

        for page in raw_pages:
            if not page.strip():
                continue
            try:
                lines = page.strip().split("\n")
                source_url = lines[0].strip()
                content = "\n".join(lines[1:]).strip()

                if len(content) < 100:
                    continue

                page_type = infer_page_type(source_url)
                sections = self.split_into_sections(content)

                for idx, (section_title, section_body) in enumerate(sections):
                    if len(section_body.strip()) < 50:
                        continue

                    documents.append(Document(
                        page_content=section_body,
                        metadata={
                            "source": source_url,
                            "page_type": page_type,
                            "section_title": section_title,
                            "section_id": f"{source_url}::{idx}",
                            "section_index": idx,
                        }
                    ))

            except Exception as e:
                logger.warning(f"Failed to parse page: {e}")

        logger.info(f"Parsed {len(documents)} sections across all pages")
        return documents

    # ------------------------------------------------------------------
    # Chunking — keeps sections whole when they fit, tags chunks otherwise
    # ------------------------------------------------------------------

    def chunk_documents(self, documents: list[Document]) -> list[Document]:
        """
        For sections that fit within CHUNK_SIZE, keep them as a single chunk
        (is_complete_section=True).  Larger sections are split by the text
        splitter; each sub-chunk keeps its section metadata plus a chunk_index
        so the SectionFetchService can reassemble them in reading order.
        """
        logger.info("Chunking sections")
        all_chunks: list[Document] = []

        for doc in documents:
            if len(doc.page_content) <= settings.CHUNK_SIZE:
                doc.metadata["chunk_index"] = 0
                doc.metadata["is_complete_section"] = "true"   # str, not bool
                all_chunks.append(doc)
            else:
                sub_chunks = self.splitter.split_documents([doc])
                for i, chunk in enumerate(sub_chunks):
                    chunk.metadata["chunk_index"] = i
                    chunk.metadata["is_complete_section"] = "false"  # str, not bool
                all_chunks.extend(sub_chunks)

        complete = sum(1 for c in all_chunks if c.metadata.get("is_complete_section") == "true")
        logger.info(
            f"Generated {len(all_chunks)} chunks "
            f"({complete} complete sections, {len(all_chunks) - complete} sub-chunks)"
        )
        return all_chunks

    def clear_existing_db(self):
        db_path = Path(settings.VECTOR_DB_DIR)
        if db_path.exists():
            logger.warning(f"Deleting existing vector DB: {db_path}")
            shutil.rmtree(db_path)

    def deduplicate_chunks(self, chunks: list[Document]) -> list[Document]:
        """Remove chunks with duplicate content (same text, different source is OK)."""
        seen = set()
        unique = []
        for chunk in chunks:
            key = chunk.page_content.strip()[:300]  # first 300 chars as fingerprint
            if key not in seen:
                seen.add(key)
                unique.append(chunk)
        removed = len(chunks) - len(unique)
        if removed:
            logger.info(f"Deduplicated {removed} duplicate chunks")
        return unique

    @staticmethod
    def _sanitize_metadata(meta: dict) -> dict:
        """Replace None values with "" — FAISS docstore can't serialise None."""
        return {k: ("" if v is None else v) for k, v in meta.items()}

    def build(self):
        logger.info("Starting vector DB build")

        raw_text = self.load_raw_text()
        documents = self.parse_documents(raw_text)

        if not documents:
            raise RuntimeError("No documents parsed")

        chunks = self.chunk_documents(documents)
        chunks = self.deduplicate_chunks(chunks)
        self.clear_existing_db()

        total = len(chunks)
        texts     = [c.page_content for c in chunks]
        metadatas = [self._sanitize_metadata(c.metadata) for c in chunks]
        ids       = [str(uuid.uuid4()) for _ in chunks]

        # ── Build section store ────────────────────────────────────────────────
        # Pre-assemble section_id → complete text so SectionFetchService can do
        # an instant dict lookup instead of querying the vector DB.
        logger.info("Building section store (section_id → full text map)")
        section_map: dict[str, list[tuple[int, str]]] = {}
        for chunk in chunks:
            sid = chunk.metadata.get("section_id", "")
            if sid:
                idx = chunk.metadata.get("chunk_index", 0)
                section_map.setdefault(sid, []).append((idx, chunk.page_content))

        section_store = {
            sid: "\n".join(text for _, text in sorted(pairs))
            for sid, pairs in section_map.items()
        }

        store_path = Path(settings.VECTOR_DB_DIR).parent / "section_store.json"
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(section_store, f, ensure_ascii=False)
        logger.info(f"Section store: {len(section_store)} sections → {store_path}")

        # ── Phase 1: pre-compute all embeddings ───────────────────────────────
        EMBED_BATCH = 256
        total_embed_batches = (total + EMBED_BATCH - 1) // EMBED_BATCH
        logger.info(f"Phase 1 — embedding {total} chunks (batches of {EMBED_BATCH})")

        all_embeddings: list = []
        for i in range(0, total, EMBED_BATCH):
            batch_texts = texts[i : i + EMBED_BATCH]
            pct = (i + len(batch_texts)) / total * 100
            print(
                f"  [embed] {i // EMBED_BATCH + 1}/{total_embed_batches}"
                f"  ({i + len(batch_texts)}/{total}, {pct:.0f}%)",
                flush=True,
            )
            all_embeddings.extend(self.embedding_model.embed_documents(batch_texts))

        logger.info(f"Phase 1 complete — {len(all_embeddings)} embeddings ready")

        # ── Phase 2: build FAISS index ────────────────────────────────────────
        # FAISS has no WAL, no compaction, no SQLite — it's a single flat index
        # file.  from_embeddings() takes pre-computed vectors so no re-embedding.
        logger.info("Phase 2 — building FAISS index (no DB writes, just indexing)")

        db = FAISS.from_embeddings(
            text_embeddings=list(zip(texts, all_embeddings)),
            embedding=self.embedding_model,
            metadatas=metadatas,
            ids=ids,
        )
        db.save_local(str(settings.VECTOR_DB_DIR))

        logger.info(f"FAISS index saved → {settings.VECTOR_DB_DIR}")

        from collections import Counter
        type_counts = Counter(c.metadata.get("page_type", "general") for c in chunks)
        logger.info(f"Chunk distribution by page_type: {dict(type_counts)}")


if __name__ == "__main__":
    builder = VectorDBBuilder()
    builder.build()
