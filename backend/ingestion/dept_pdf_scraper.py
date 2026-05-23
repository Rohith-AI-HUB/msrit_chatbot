"""
Department PDF Scraper
======================
Visits every MSRIT department page, clicks ALL tabs/sections,
and downloads every PDF that wasn't already grabbed by the main crawler.

This specifically targets the "Syllabus", "PG Syllabus", "UG Syllabus",
"Scheme", "Board of Studies" etc. tabs that the BFS crawler missed because
the PDF links only appear after a tab click.

Usage
-----
    python -m ingestion.dept_pdf_scraper
"""

import asyncio
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright


# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://msrit.edu"

# All department and key section pages to hit
TARGET_PAGES = [
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
    "/admissions.html",
    "/placement.html",
    "/examination.html",
    "/facilities.html",
    "/governance.html",
    "/about.html",
]

# Sub-pages per department (query params)
DEPT_SUBPAGES = [
    "syllabus",
    "pg-syllabus",
    "ug-syllabus",
    "board-of-studies",
    "research",
    "achievements",
    "activities",
    "faculty",
]

PDF_DIR = Path(__file__).parent.parent / "data" / "pdfs"
PAGE_TIMEOUT = 20_000  # ms


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_filename(url: str) -> str:
    name = url.split("/")[-1].split("?")[0] or "document.pdf"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:200]


def _is_pdf(url: str) -> bool:
    return ".pdf" in urlparse(url).path.lower()


async def _collect_all_pdf_links(page) -> set[str]:
    """Grab every PDF link currently visible in the DOM."""
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href)"
        )
        return {h for h in hrefs if _is_pdf(h)}
    except Exception:
        return set()


async def _click_all_tabs(page) -> None:
    """Click every visible tab, nav-link, accordion, and section button."""
    TAB_SELS = [
        "[role='tab']",
        "[data-toggle='tab']",
        "[data-bs-toggle='tab']",
        ".nav-tabs .nav-link",
        ".nav-pills .nav-link",
        ".tab-link",
        "[class*='tab-head']",
        "[data-toggle='collapse']",
        "[data-bs-toggle='collapse']",
        ".accordion-button",
        ".accordion-header button",
        "[aria-expanded='false']",
        "li.nav-item > a",
        ".list-group-item",
    ]
    clicked = set()
    for sel in TAB_SELS:
        try:
            items = await page.locator(sel).all()
            for item in items[:60]:
                try:
                    text = (await item.inner_text()).strip()[:80]
                    if text in clicked:
                        continue
                    if not await item.is_visible():
                        continue
                    clicked.add(text)
                    await item.click(timeout=2_000)
                    await page.wait_for_timeout(400)
                except Exception:
                    pass
        except Exception:
            pass


async def _download_pdf(url: str, dest: Path, context) -> bool:
    try:
        resp = await context.request.get(url, timeout=30_000)
        if resp.ok:
            dest.write_bytes(await resp.body())
            return True
    except Exception:
        pass
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    existing = {f.name for f in PDF_DIR.glob("*.pdf")}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (compatible; MSRITBot/1.0)"
        )
        page = await context.new_page()

        all_pdf_urls: set[str] = set()

        for path in TARGET_PAGES:
            url = urljoin(BASE_URL, path)
            print(f"\n[Page] {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                await page.wait_for_timeout(800)
            except Exception as e:
                print(f"  [skip] {e}")
                continue

            # Collect PDFs before clicking tabs
            before = await _collect_all_pdf_links(page)
            all_pdf_urls.update(before)

            # Click every tab/section to reveal hidden PDFs
            await _click_all_tabs(page)
            await page.wait_for_timeout(600)

            # Collect PDFs after clicking tabs
            after = await _collect_all_pdf_links(page)
            new_pdfs = after - before
            all_pdf_urls.update(after)

            if new_pdfs:
                print(f"  Found {len(new_pdfs)} new PDF(s) after tab clicks:")
                for p in sorted(new_pdfs):
                    print(f"    {p.split('/')[-1][:80]}")
            else:
                print(f"  {len(before)} PDF link(s) (no new ones after tabs)")

        await browser.close()

        # ── Download all discovered PDFs ──────────────────────────
        print(f"\n\nTotal unique PDF URLs found: {len(all_pdf_urls)}")

        new_count = 0
        skip_count = 0

        async with async_playwright() as pw2:
            browser2 = await pw2.chromium.launch(headless=True)
            ctx2 = await browser2.new_context()

            for pdf_url in sorted(all_pdf_urls):
                fname = _safe_filename(pdf_url)
                dest = PDF_DIR / fname

                if fname in existing or dest.exists():
                    skip_count += 1
                    continue

                print(f"  Downloading: {fname[:70]} ...", end=" ", flush=True)
                ok = await _download_pdf(pdf_url, dest, ctx2)
                if ok:
                    print("OK")
                    new_count += 1
                    existing.add(fname)
                else:
                    print("FAILED")

            await browser2.close()

        print(f"\nDone — {new_count} new PDFs downloaded, {skip_count} already existed.")
        print(f"Total PDFs in folder: {len(list(PDF_DIR.glob('*.pdf')))}")

        if new_count > 0:
            print("\nNow index the new PDFs:")
            print("  python -m ingestion.index_pdfs")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
