from pathlib import Path
import shutil

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
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

    def parse_documents(self, text: str) -> list[Document]:
        logger.info("Parsing crawled pages")
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

                documents.append(Document(
                    page_content=content,
                    metadata={
                        "source": source_url,
                        "page_type": page_type
                    }
                ))

            except Exception as e:
                logger.warning(f"Failed to parse page: {e}")

        logger.info(f"Parsed {len(documents)} documents")
        return documents

    def chunk_documents(self, documents: list[Document]) -> list[Document]:
        logger.info("Chunking documents")
        chunks = self.splitter.split_documents(documents)
        logger.info(f"Generated {len(chunks)} chunks")
        return chunks

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

    def build(self):
        logger.info("Starting vector DB build")

        raw_text = self.load_raw_text()
        documents = self.parse_documents(raw_text)

        if not documents:
            raise RuntimeError("No documents parsed")

        chunks = self.chunk_documents(documents)
        chunks = self.deduplicate_chunks(chunks)
        self.clear_existing_db()

        # Embed and insert in batches so progress is visible and memory stays low
        BATCH_SIZE = 200
        total = len(chunks)
        logger.info(f"Creating Chroma vector DB — {total} chunks in batches of {BATCH_SIZE}")

        db = None
        for i in range(0, total, BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            pct = (i + len(batch)) / total * 100
            print(f"  Embedding batch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}"
                  f"  ({i + len(batch)}/{total} chunks, {pct:.0f}%)", flush=True)
            if db is None:
                db = Chroma.from_documents(
                    documents=batch,
                    embedding=self.embedding_model,
                    persist_directory=str(settings.VECTOR_DB_DIR)
                )
            else:
                db.add_documents(batch)

        logger.info("Vector DB created successfully")

        from collections import Counter
        type_counts = Counter(c.metadata.get("page_type", "general") for c in chunks)
        logger.info(f"Chunk distribution by page_type: {dict(type_counts)}")


if __name__ == "__main__":
    builder = VectorDBBuilder()
    builder.build()
