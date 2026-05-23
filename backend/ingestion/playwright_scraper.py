"""
MSRIT Playwright Scraper
========================
Capabilities:
  1. PDF Downloader  — crawls given pages and downloads every PDF found
  2. Result Checker  — fills USN search forms, lets you type CAPTCHAs
                       manually in the terminal, then saves the result page
                       as a PDF

Usage
-----
  # download all PDFs from configured pages
  python playwright_scraper.py pdfs

  # check results for every USN in USN_LIST
  python playwright_scraper.py results

  # do both
  python playwright_scraper.py
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import (
    Download,
    Page,
    async_playwright,
)


# ══════════════════════════════════════════════════════════════
# CONFIG — edit this section before running
# ══════════════════════════════════════════════════════════════

# URL of the exam / results portal
RESULTS_URL = "https://exam.msrit.edu/"

# List of USNs (University Seat Numbers) to check
USN_LIST: list[str] = [
    "1MS21CS001",
    "1MS21CS002",
    # add more USNs here …
]

# CSS selectors for the results form
# Playwright tries each in order and uses the first match
USN_FIELD_SELECTORS = [
    "input[placeholder*='USN' i]",
    "input[placeholder*='seat' i]",
    "input[placeholder*='roll' i]",
    "input[name*='usn' i]",
    "input[id*='usn' i]",
    "input[type='text']:first-of-type",
]

CAPTCHA_IMG_SELECTORS = [
    "img[id*='captcha' i]",
    "img[src*='captcha' i]",
    "img[class*='captcha' i]",
    ".captcha img",
    "#captchaImg",
]

CAPTCHA_INPUT_SELECTORS = [
    "input[id*='captcha' i]",
    "input[placeholder*='captcha' i]",
    "input[name*='captcha' i]",
    "input[placeholder*='type' i]",
]

SUBMIT_BTN_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Search')",
    "button:has-text('Get Result')",
]

# Pages to scrape PDFs from
PDF_SOURCE_PAGES: list[str] = [
    "https://www.msrit.edu/",
    "https://www.msrit.edu/examination.html",
    "https://www.msrit.edu/admissions.html",
    # add more pages here …
]

# Where to save downloaded PDFs
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "pdfs"

# ══════════════════════════════════════════════════════════════


def _first_match(selectors: list[str]) -> str:
    """Return a comma-joined CSS selector string (Playwright picks first)."""
    return ", ".join(selectors)


async def _find(page: Page, selectors: list[str]):
    """Return the first visible element that matches any selector."""
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if await el.is_visible():
                return el
        except Exception:
            continue
    return None


# ──────────────────────────────────────────────────────────────
# 1. PDF DOWNLOADER
# ──────────────────────────────────────────────────────────────

async def download_pdfs_from_page(
    page: Page,
    url: str,
    out_dir: Path,
) -> list[Path]:
    """
    Navigate to *url*, collect every PDF link on the page, and
    download each one into *out_dir*.  Returns paths to saved files.
    """
    print(f"\n[PDF] Scanning {url}")

    await page.goto(url, wait_until="networkidle")

    # Collect all href / src that end with .pdf
    pdf_links: list[str] = await page.eval_on_selector_all(
        "a[href$='.pdf' i], a[href*='.pdf' i]",
        """
        els => els
            .map(el => el.href)
            .filter(href => href && href.toLowerCase().includes('.pdf'))
        """,
    )

    # Deduplicate
    pdf_links = list(dict.fromkeys(pdf_links))

    if not pdf_links:
        print(f"[PDF] No PDFs found on {url}")
        return []

    print(f"[PDF] Found {len(pdf_links)} PDF link(s)")

    saved: list[Path] = []

    for pdf_url in pdf_links:

        filename = pdf_url.split("/")[-1].split("?")[0] or "document.pdf"
        dest = out_dir / filename

        if dest.exists():
            print(f"[PDF] Already downloaded: {filename}")
            saved.append(dest)
            continue

        print(f"[PDF] Downloading: {filename}")

        try:
            async with page.expect_download(timeout=30_000) as dl_info:
                await page.evaluate(
                    "url => { const a = document.createElement('a'); "
                    "a.href = url; a.download = ''; "
                    "document.body.appendChild(a); a.click(); "
                    "document.body.removeChild(a); }",
                    pdf_url,
                )

            download: Download = await dl_info.value
            await download.save_as(dest)
            print(f"[PDF] Saved → {dest}")
            saved.append(dest)

        except Exception:
            # Fallback: fetch via CDP if the click trick doesn't work
            try:
                response = await page.request.get(pdf_url)

                if response.ok:
                    dest.write_bytes(await response.body())
                    print(f"[PDF] Saved (fetch) → {dest}")
                    saved.append(dest)
                else:
                    print(
                        f"[PDF] Failed ({response.status}): {pdf_url}"
                    )

            except Exception as exc:
                print(f"[PDF] Error downloading {pdf_url}: {exc}")

    return saved


async def run_pdf_downloader(pages: list[str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        total: list[Path] = []

        for url in pages:
            saved = await download_pdfs_from_page(page, url, out_dir)
            total.extend(saved)

        await browser.close()

    print(f"\n[PDF] Done — {len(total)} file(s) saved to {out_dir}")


# ──────────────────────────────────────────────────────────────
# 2. RESULT CHECKER  (with manual CAPTCHA input)
# ──────────────────────────────────────────────────────────────

async def _fill_captcha(page: Page) -> bool:
    """
    Find the CAPTCHA on the page.
    The browser window stays open so the user can read the CAPTCHA image.
    Prompts the user to type the CAPTCHA text in the terminal.
    Returns True if a CAPTCHA was found and filled.
    """
    captcha_img = await _find(page, CAPTCHA_IMG_SELECTORS)
    captcha_input = await _find(page, CAPTCHA_INPUT_SELECTORS)

    if not captcha_input:
        return False  # no CAPTCHA on this page

    print()
    print("=" * 52)
    print("  CAPTCHA REQUIRED")
    print("  Look at the browser window to read the CAPTCHA.")
    print("=" * 52)

    captcha_text = input("  Type CAPTCHA here and press Enter: ").strip()

    await captcha_input.triple_click()
    await captcha_input.type(captcha_text, delay=80)

    print(f"  Filled CAPTCHA: {captcha_text}")
    return True


async def check_result_for_usn(
    page: Page,
    usn: str,
    out_dir: Path,
) -> Path | None:
    """
    Fill the result-search form for *usn*, handle CAPTCHA, submit,
    and save the result as a PDF.  Returns the saved path or None.
    """
    print(f"\n[Result] Checking USN: {usn}")

    await page.goto(RESULTS_URL, wait_until="networkidle")

    # --- Fill USN field ---
    usn_field = await _find(page, USN_FIELD_SELECTORS)

    if not usn_field:
        print(
            "[Result] ERROR: Could not find USN input field.\n"
            "         Update USN_FIELD_SELECTORS in the config section."
        )
        return None

    await usn_field.triple_click()
    await usn_field.type(usn, delay=60)
    print(f"[Result] Filled USN: {usn}")

    # --- Fill CAPTCHA ---
    await _fill_captcha(page)

    # --- Submit ---
    submit_btn = await _find(page, SUBMIT_BTN_SELECTORS)

    if not submit_btn:
        print(
            "[Result] ERROR: Could not find Submit button.\n"
            "         Update SUBMIT_BTN_SELECTORS in the config section."
        )
        return None

    await submit_btn.click()
    await page.wait_for_load_state("networkidle")

    # --- Save result as PDF ---
    dest = out_dir / f"result_{usn}.pdf"

    await page.pdf(path=str(dest))

    print(f"[Result] Saved → {dest}")

    return dest


async def run_result_checker(usn_list: list[str], out_dir: Path) -> None:
    if not usn_list:
        print("[Result] USN_LIST is empty — add USNs to the config.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        # headless=False so the user can read the CAPTCHA in the browser
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        success: list[str] = []
        failed: list[str] = []

        for usn in usn_list:
            result_path = await check_result_for_usn(page, usn, out_dir)

            if result_path:
                success.append(usn)
            else:
                failed.append(usn)

        await browser.close()

    print(f"\n[Result] Done — {len(success)} succeeded, {len(failed)} failed")

    if failed:
        print(f"[Result] Failed USNs: {failed}")


# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────

async def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if mode in ("pdfs", "pdf", "all"):
        await run_pdf_downloader(PDF_SOURCE_PAGES, OUTPUT_DIR)

    if mode in ("results", "result", "all"):
        await run_result_checker(USN_LIST, OUTPUT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
