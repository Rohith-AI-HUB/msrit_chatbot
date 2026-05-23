"""
Syllabus Scraper — Google Drive Edition
========================================
MSRIT stores syllabus PDFs on Google Drive (not S3).
This script:
  1. Visits every department page
  2. Extracts all Google Drive file links
  3. Downloads them as PDFs into data/pdfs/

Then run:
    python -m ingestion.index_pdfs
to extract text and rebuild the vector DB.

Usage
-----
    python -m ingestion.syllabus_scraper
"""

import asyncio
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright


# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://msrit.edu"

DEPARTMENT_PAGES = [
    "/department/aerospace.html",
    "/department/architecture.html",
    "/department/ai_ds.html",
    "/department/ai_ml.html",
    "/department/biotechnology.html",
    "/department/chemical-engineering.html",
    "/department/chemistry.html",
    "/department/civil-engineering.html",
    "/department/cse.html",
    "/department/cse_ai_ml.html",
    "/department/cse_cs.html",
    "/department/ece.html",
    "/department/eie.html",
    "/department/eee.html",
    "/department/te.html",
    "/department/humanities.html",
    "/department/iem.html",
    "/department/ise.html",
    "/department/maths.html",
    "/department/mca.html",
    "/department/mba.html",
    "/department/me.html",
    "/department/medical-engineering.html",
    "/department/physics.html",
    "/department/certificate-programs.html",
    "/department/int-411.html",
    # Sub-pages
    "/department/faculty.html?dept=cse.html",
    "/department/faculty.html?dept=cse_ai_ml.html",
    "/department/faculty.html?dept=cse_cs.html",
    "/department/faculty.html?dept=ece.html",
    "/department/faculty.html?dept=eee.html",
    "/department/faculty.html?dept=me.html",
    "/department/faculty.html?dept=ise.html",
    "/admissions.html",
    "/placement.html",
    "/examination.html",
    "/governance.html",
    "/about.html",
]

PDF_DIR     = Path(__file__).parent.parent / "data" / "pdfs"
PAGE_TIMEOUT = 20_000

# Google Drive file ID pattern
GDRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)")


def gdrive_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"


def gdrive_filename(file_id: str, link_text: str) -> str:
    """Make a filename from the link text + file_id suffix."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", link_text.strip())
    safe = safe.strip("_")[:80]
    return f"{safe}__{file_id[:8]}.pdf"


async def extract_gdrive_links(page) -> list[tuple[str, str]]:
    """Return list of (file_id, link_text) for all Google Drive links on page."""
    try:
        links = await page.eval_on_selector_all("a[href]", """
            els => els.map(e => ({href: e.href || '', text: e.innerText.trim()}))
        """)
    except Exception:
        return []

    results = []
    seen = set()
    for item in links:
        m = GDRIVE_FILE_RE.search(item["href"])
        if m:
            fid = m.group(1)
            if fid not in seen:
                seen.add(fid)
                results.append((fid, item["text"] or fid))
    return results


async def download_gdrive_file(file_id: str, dest: Path, context) -> bool:
    """Download a Google Drive file. Handles the virus-scan confirmation page."""
    url = gdrive_download_url(file_id)
    try:
        # First request — may return confirmation page for large files
        resp = await context.request.get(url, timeout=30_000)
        if not resp.ok:
            return False

        body = await resp.body()

        # If Google returns an HTML confirmation page, follow the confirm link
        if b"<html" in body[:500].lower():
            text = body.decode("utf-8", errors="ignore")
            # Look for confirm token
            m = re.search(r'confirm=([0-9A-Za-z_\-]+)', text)
            if m:
                confirm_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm={m.group(1)}"
                resp2 = await context.request.get(confirm_url, timeout=60_000)
                if resp2.ok:
                    body = await resp2.body()
                else:
                    return False
            else:
                # No confirm token — file may be restricted or not a PDF
                return False

        # Verify it looks like a PDF
        if not body[:4].startswith(b"%PDF") and len(body) < 1000:
            return False

        dest.write_bytes(body)
        return True

    except Exception as e:
        print(f"    [error] {e}")
        return False


def _filter_latest_batches(gdrive: dict[str, str]) -> dict[str, str]:
    """
    For links that share the same program name but differ only in batch year,
    keep only the one with the highest start year.

    e.g. {"id1": "PG CSE (Batch 2024-2026)", "id2": "PG CSE (Batch 2025-2027)"}
         → keeps id2 only.
    """
    YEAR_RE = re.compile(r'(\d{4})\s*[-–]\s*\d{4}')

    # Group by "base name" (text with the year range stripped)
    groups: dict[str, list[tuple[str, str, int]]] = {}  # base → [(fid, text, start_year)]

    for fid, text in gdrive.items():
        m = YEAR_RE.search(text)
        if m:
            start_year = int(m.group(1))
            base = YEAR_RE.sub("", text).strip().lower()
            base = re.sub(r'[\s\(\)]+', ' ', base).strip()
            groups.setdefault(base, []).append((fid, text, start_year))
        else:
            # No year range — always include
            groups.setdefault(f"__no_year_{fid}", []).append((fid, text, 0))

    result = {}
    for base, entries in groups.items():
        # Pick the entry with the highest start year
        best = max(entries, key=lambda x: x[2])
        result[best[0]] = best[1]

    return result


async def run():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    existing = {f.name for f in PDF_DIR.glob("*.pdf")}

    # Collect all Google Drive links across all pages
    all_gdrive: dict[str, str] = {}  # file_id → best link text

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537"
        )
        page = await context.new_page()

        for dept_path in DEPARTMENT_PAGES:
            url = urljoin(BASE_URL, dept_path)
            print(f"[Scan] {url} ...", end=" ", flush=True)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                await page.wait_for_timeout(600)
            except Exception as e:
                print(f"skip ({e})")
                continue

            gdrive_links = await extract_gdrive_links(page)
            new = [(fid, txt) for fid, txt in gdrive_links if fid not in all_gdrive]
            for fid, txt in gdrive_links:
                all_gdrive.setdefault(fid, txt)  # keep first seen link text

            print(f"{len(gdrive_links)} GDrive links ({len(new)} new)")

        await browser.close()

    print(f"\nTotal unique Google Drive files found: {len(all_gdrive)}")

    # Keep only the latest batch when multiple batches exist for the same program.
    # e.g. "PG CSE (Batch 2024-2026)" and "PG CSE (Batch 2025-2027)" → keep 2025-2027
    all_gdrive = _filter_latest_batches(all_gdrive)
    print(f"After filtering to latest batches:    {len(all_gdrive)}")
    print("-" * 60)

    # Download all
    new_count = 0
    skip_count = 0
    fail_count = 0

    async with async_playwright() as pw2:
        browser2 = await pw2.chromium.launch(headless=True)
        ctx2 = await browser2.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537"
        )

        for file_id, link_text in all_gdrive.items():
            fname = gdrive_filename(file_id, link_text)
            dest = PDF_DIR / fname

            if fname in existing or dest.exists():
                skip_count += 1
                continue

            print(f"  Downloading: {link_text[:60]} ...", end=" ", flush=True)
            ok = await download_gdrive_file(file_id, dest, ctx2)
            if ok:
                size_kb = dest.stat().st_size // 1024
                print(f"OK ({size_kb} KB)")
                new_count += 1
                existing.add(fname)
            else:
                print("FAILED (restricted or not a PDF)")
                fail_count += 1

        await browser2.close()

    print(f"\n{'-'*60}")
    print(f"Downloaded: {new_count} new | Skipped: {skip_count} existing | Failed: {fail_count}")
    print(f"Total PDFs: {len(list(PDF_DIR.glob('*.pdf')))}")

    if new_count > 0:
        print("\nNext step — index the new PDFs:")
        print("  python -m ingestion.index_pdfs")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
