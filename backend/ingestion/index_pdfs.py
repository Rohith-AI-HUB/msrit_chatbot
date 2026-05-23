"""
PDF Indexer
===========
Extracts text from every PDF in data/pdfs/ and appends it to
data/msrit_full.txt in the same PAGE_URL format that build_vector_db.py reads.

Then rebuilds the Chroma vector DB so the chatbot can answer questions
about PDF content (syllabi, fee structures, placement lists, etc.)

Usage
-----
    python -m ingestion.index_pdfs
"""

import sys
from pathlib import Path

import pdfplumber

# Optional — install for better coverage
try:
    import fitz as pymupdf        # pip install pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

# Optional — requires Tesseract + Poppler installed on the system
try:
    import pytesseract            # pip install pytesseract
    from pdf2image import convert_from_path  # pip install pdf2image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

PDF_DIR    = Path(__file__).parent.parent / "data" / "pdfs"
CRAWL_TXT  = Path(__file__).parent.parent / "data" / "msrit_full.txt"
MIN_CHARS  = 100

# Path to Poppler bin folder on Windows.
# Download from https://github.com/oschwartz10612/poppler-windows/releases
# Extract and set the path to the bin/ folder inside it.
# Example: r"C:\poppler\poppler-24.08.0\Library\bin"
POPPLER_PATH = r"C:\poppler\Library\bin"   # ← update this after extracting

# Tesseract executable path on Windows
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _extract_pdfplumber(pdf_path: Path) -> str:
    pages_text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text.strip())
                except Exception:
                    pass
    except Exception:
        pass
    return "\n\n".join(pages_text)


def _extract_pymupdf(pdf_path: Path) -> str:
    pages_text = []
    try:
        doc = pymupdf.open(str(pdf_path))
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages_text.append(text.strip())
        doc.close()
    except Exception:
        pass
    return "\n\n".join(pages_text)


def _extract_ocr(pdf_path: Path) -> str:
    """Last resort: convert pages to images and run Tesseract OCR."""
    pages_text = []
    try:
        poppler_path = POPPLER_PATH if Path(POPPLER_PATH).exists() else None
        images = convert_from_path(str(pdf_path), dpi=200, poppler_path=poppler_path)
        for img in images:
            text = pytesseract.image_to_string(img)
            if text.strip():
                pages_text.append(text.strip())
    except Exception as e:
        print(f"  [ocr-error] {e}")
    return "\n\n".join(pages_text)


def extract_text(pdf_path: Path) -> tuple[str, str]:
    """
    Try extractors in order: pdfplumber → PyMuPDF → OCR.
    Returns (text, method_used).
    """
    # 1. pdfplumber
    text = _extract_pdfplumber(pdf_path)
    if len(text) >= MIN_CHARS:
        return text, "pdfplumber"

    # 2. PyMuPDF (handles more PDF types)
    if HAS_PYMUPDF:
        text = _extract_pymupdf(pdf_path)
        if len(text) >= MIN_CHARS:
            return text, "pymupdf"

    # 3. OCR (scanned image PDFs)
    if HAS_OCR:
        text = _extract_ocr(pdf_path)
        if len(text) >= MIN_CHARS:
            return text, "ocr"

    return text, "none"


def already_indexed(pdf_path: Path, existing_content: str) -> bool:
    """Check if this PDF was already appended in a previous run."""
    return f"PDF: {pdf_path.name}" in existing_content


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDFs in {PDF_DIR}\n")

    # Load existing content to avoid duplicates
    existing = CRAWL_TXT.read_text(encoding="utf-8") if CRAWL_TXT.exists() else ""

    new_count   = 0
    skip_count  = 0
    empty_count = 0

    with open(CRAWL_TXT, "a", encoding="utf-8") as fh:
        for pdf_path in pdfs:
            if already_indexed(pdf_path, existing):
                skip_count += 1
                continue

            print(f"Extracting: {pdf_path.name} ...", end=" ", flush=True)
            text, method = extract_text(pdf_path)

            if len(text) < MIN_CHARS:
                if HAS_OCR:
                    print(f"skipped (only {len(text)} chars even after OCR)")
                else:
                    print(f"skipped (scanned image — install Tesseract+Poppler for OCR)")
                empty_count += 1
                continue

            # Write in the same format as the crawler so build_vector_db.py
            # can parse it without any changes
            fh.write(f"\nPAGE_URL: PDF: {pdf_path.name}\n\n")
            fh.write("CONTENT:\n")
            fh.write(text)
            fh.write("\n\n" + "─" * 60 + "\n\n")

            print(f"OK ({len(text):,} chars) [{method}]")
            new_count += 1

    ocr_note = ""
    if not HAS_OCR and empty_count > 0:
        ocr_note = (
            f"\n  {empty_count} scanned PDFs skipped. "
            "To index them install Tesseract from "
            "https://github.com/UB-Mannheim/tesseract/wiki "
            "then: pip install pytesseract pdf2image"
        )

    print(f"\nDone — {new_count} PDFs indexed, "
          f"{skip_count} already indexed, "
          f"{empty_count} skipped (scanned/unreadable)"
          f"{ocr_note}")

    if new_count == 0:
        print("Nothing new to add — vector DB is already up to date.")
        return

    print("\nRebuilding vector DB ...")
    # Import and run the builder directly
    from ingestion.build_vector_db import VectorDBBuilder
    VectorDBBuilder().build()
    print("Vector DB rebuilt successfully.")


if __name__ == "__main__":
    main()
