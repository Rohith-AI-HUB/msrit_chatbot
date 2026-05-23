"""
MSRIT Intelligent Playwright Crawler
=====================================
Exhaustively discovers and crawls every page on msrit.edu:

  Phase 0 – Seed Discovery
      • Probes common page paths (admissions, placement, etc.)

  Phase 1 – Navigation Menu Discovery
      • Opens the homepage, hovers every nav trigger to reveal dropdowns
      • Collects all link hrefs discovered after hovering

  Phase 2 – BFS Deep Crawl
      • Visits every internal URL breadth-first
      • On each page: expands tabs, accordions, show-more buttons,
        intercepts onclick JS links
      • Extracts headings + full body text

  Phase 3 – PDF Downloads
      • Downloads every .pdf found across all pages

Output
------
  data/msrit_full.txt       ← all page content (RAG-ready, feeds build_vector_db.py)
  data/crawl_report.json    ← structured summary
  data/pdfs/                ← downloaded PDFs

Usage
-----
    python ingestion/intelligent_crawler.py
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, Page, Response, async_playwright


# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════

START_URL = "https://msrit.edu/"

ALLOWED_DOMAINS = {"msrit.edu", "www.msrit.edu"}

# Common paths probed on startup even if not linked from homepage
SEED_PATHS = [
    "/",
    "/index.html",
    "/admissions.html",
    "/placement.html",
    "/examination.html",
    "/facilities.html",
    "/departments.html",
    "/governance.html",
    "/news.html",
    "/events.html",
    "/about.html",
    "/contact.html",
    "/research.html",
    "/alumni.html",
    "/library.html",
    "/hostel.html",
    "/sitemap.html",
]

MAX_PAGES = 600          # hard cap on pages crawled
PAGE_TIMEOUT = 20_000    # ms — per page (domcontentloaded, not networkidle)
NAV_HOVER_DELAY = 150    # ms — wait after each nav hover
INTERACT_DELAY = 200     # ms — wait after tab / accordion click
MAX_ITEMS_PER_SEL = 40   # max elements to interact with per selector

# URL substrings — any matching URL is skipped entirely.
# Prevents crawling hundreds of near-identical parameterised pages
# and known-dead subtrees.
SKIP_PATTERNS = [
    "faculty-detail.html",   # individual faculty bios: ~1000 pages, very slow
    "/research/phd/",        # entire subtree returns 404
]

# Output
OUTPUT_DIR = Path(__file__).parent.parent / "data"
PDF_DIR    = OUTPUT_DIR / "pdfs"
CRAWL_TXT  = OUTPUT_DIR / "msrit_full.txt"       # same path build_vector_db.py reads
CRAWL_REPORT = OUTPUT_DIR / "crawl_report.json"

# ══════════════════════════════════════════════════════════════


@dataclass
class PageData:
    url: str
    title: str = ""
    headings: list[str] = field(default_factory=list)
    content: str = ""
    links: list[str] = field(default_factory=list)
    pdf_links: list[str] = field(default_factory=list)
    error: str = ""


# ──────────────────────────────────────────────────────────────
# URL helpers
# ──────────────────────────────────────────────────────────────

def _normalize(url: str) -> str:
    try:
        p = urlparse(url.strip())
        clean = urlunparse((p.scheme.lower(), p.netloc.lower(),
                            p.path, p.params, p.query, ""))
        parts = urlparse(clean)
        if parts.path.endswith("/") and parts.path != "/":
            clean = urlunparse((parts.scheme, parts.netloc,
                                parts.path.rstrip("/"),
                                parts.params, parts.query, ""))
        return clean
    except Exception:
        return url


def _is_internal(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower().lstrip("www.")
        return netloc in {d.lstrip("www.") for d in ALLOWED_DOMAINS}
    except Exception:
        return False


def _is_pdf(url: str) -> bool:
    return ".pdf" in urlparse(url).path.lower()


def _is_skippable(url: str) -> bool:
    lower = url.lower().strip()
    if any(lower.startswith(p) for p in
           ("mailto:", "tel:", "javascript:", "#", "data:", "ftp:", "whatsapp:")):
        return True
    return any(p in lower for p in SKIP_PATTERNS)


def _safe_filename(url: str) -> str:
    name = url.split("/")[-1].split("?")[0] or "document.pdf"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


# ──────────────────────────────────────────────────────────────
# Crawler
# ──────────────────────────────────────────────────────────────

class MSRITIntelligentCrawler:

    def __init__(self) -> None:
        self.queue: list[str] = []
        self.visited: set[str] = set()
        self.pdf_queue: set[str] = set()
        self.pages: dict[str, PageData] = {}
        self.errors: list[str] = []

    # ── queue helpers ──────────────────────────────────────────

    def _enqueue(self, url: str) -> None:
        norm = _normalize(url)
        if (norm and not _is_skippable(norm) and _is_internal(norm)
                and norm not in self.visited and norm not in self.queue):
            if _is_pdf(norm):
                self.pdf_queue.add(norm)
            else:
                self.queue.append(norm)

    def _enqueue_many(self, urls: list[str]) -> None:
        for url in urls:
            self._enqueue(url)

    # ── Phase 0: seed ──────────────────────────────────────────

    async def _seed_from_paths(self, page: Page) -> None:
        print("\n[Seed] Probing common paths …")
        for path in SEED_PATHS:
            url = urljoin(START_URL, path)
            norm = _normalize(url)
            if norm in self.visited or norm in self.queue:
                continue
            try:
                resp = await page.request.get(url, timeout=8_000)
                if resp.ok:
                    ct = resp.headers.get("content-type", "")
                    if "html" in ct or "xml" in ct:
                        self._enqueue(url)
                        print(f"  [Seed] ✓ {path}")
            except Exception:
                pass

    # ── Phase 1: nav hover discovery ──────────────────────────

    async def _hover_nav(self, page: Page) -> list[str]:
        """
        Hover over nav triggers to open CSS/JS dropdowns.
        Capped at MAX_ITEMS_PER_SEL per selector so it never stalls.
        """
        NAV_SELECTORS = [
            "nav li",
            "header li",
            ".navbar li",
            ".nav-item",
            ".menu-item",
            "[class*='dropdown'] > a",
            "ul.nav > li",
            "ul.menu > li",
        ]

        seen_els: set[str] = set()   # avoid re-hovering the same element
        hovered = 0

        for selector in NAV_SELECTORS:
            try:
                items = await page.locator(selector).all()
                for item in items[:MAX_ITEMS_PER_SEL]:
                    try:
                        # Use bounding box as a cheap identity check
                        bb = await item.bounding_box()
                        key = f"{bb['x']:.0f},{bb['y']:.0f}" if bb else ""
                        if key and key in seen_els:
                            continue
                        if key:
                            seen_els.add(key)

                        await item.hover(timeout=1_500)
                        await page.wait_for_timeout(NAV_HOVER_DELAY)
                        hovered += 1
                    except Exception:
                        pass
            except Exception:
                pass

        print(f"  Hovered {hovered} nav item(s)")

        # Collect all links now visible (including those revealed by dropdowns)
        try:
            return await page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
        except Exception:
            return []

    # ── Phase 2: in-page interaction ──────────────────────────

    async def _expand_tabs(self, page: Page) -> None:
        TAB_SELS = [
            "[role='tab']",
            "[data-toggle='tab']",
            "[data-bs-toggle='tab']",
            ".nav-tabs .nav-link",
            ".tab-link",
            "[class*='tab-head']",
        ]
        for sel in TAB_SELS:
            try:
                for tab in (await page.locator(sel).all())[:MAX_ITEMS_PER_SEL]:
                    try:
                        if await tab.is_visible():
                            await tab.click(timeout=2_000)
                            await page.wait_for_timeout(INTERACT_DELAY)
                    except Exception:
                        pass
            except Exception:
                pass

    async def _expand_accordions(self, page: Page) -> None:
        ACC_SELS = [
            "[data-toggle='collapse']",
            "[data-bs-toggle='collapse']",
            ".accordion-button",
            ".accordion-header button",
            "[aria-expanded='false']",
            ".collapsible",
        ]
        for sel in ACC_SELS:
            try:
                for el in (await page.locator(sel).all())[:MAX_ITEMS_PER_SEL]:
                    try:
                        if await el.is_visible():
                            expanded = await el.get_attribute("aria-expanded")
                            if expanded != "true":
                                await el.click(timeout=2_000)
                                await page.wait_for_timeout(INTERACT_DELAY)
                    except Exception:
                        pass
            except Exception:
                pass

    async def _click_show_more(self, page: Page) -> None:
        MORE_SELS = [
            "button:has-text('Read More')",
            "button:has-text('Show More')",
            "button:has-text('View All')",
            "button:has-text('Load More')",
            "[class*='read-more']",
            "[class*='show-more']",
        ]
        for sel in MORE_SELS:
            try:
                for btn in (await page.locator(sel).all())[:6]:
                    try:
                        href = await btn.get_attribute("href")
                        if href and href not in ("#", "", None):
                            continue   # it's a nav link, not a toggle
                        if await btn.is_visible():
                            await btn.click(timeout=2_000)
                            await page.wait_for_timeout(INTERACT_DELAY)
                    except Exception:
                        pass
            except Exception:
                pass

    async def _intercept_js_links(self, page: Page) -> list[str]:
        """Extract URLs from onclick attributes that aren't regular hrefs."""
        try:
            return await page.evaluate(r"""
                () => {
                    const urls = new Set();
                    const base = location.origin;
                    document.querySelectorAll('[onclick]').forEach(el => {
                        const m = el.getAttribute('onclick')
                            .match(/(?:location\.href|window\.location)\s*=\s*['"]([^'"]+)['"]/);
                        if (m) { try { urls.add(new URL(m[1], base).href); } catch {} }
                    });
                    document.querySelectorAll('a[href]').forEach(el => {
                        if (!el.href.startsWith('javascript:')) urls.add(el.href);
                        const dh = el.dataset.href || el.dataset.url || el.dataset.link;
                        if (dh) { try { urls.add(new URL(dh, base).href); } catch {} }
                    });
                    return [...urls];
                }
            """)
        except Exception:
            return []

    # ── Content extraction ─────────────────────────────────────

    async def _extract(self, page: Page, url: str) -> PageData:
        data = PageData(url=url)
        try:
            data.title = await page.title()
        except Exception:
            pass
        try:
            data.headings = await page.eval_on_selector_all(
                "h1, h2, h3, h4",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 2)",
            )
        except Exception:
            pass
        try:
            data.content = await page.evaluate(r"""
                () => {
                    ['script','style','noscript','svg','iframe',
                     'header','footer','nav'].forEach(tag =>
                        document.querySelectorAll(tag).forEach(el => el.remove())
                    );
                    return (document.body?.innerText || '')
                        .replace(/[ \t]+/g, ' ')
                        .replace(/\n{3,}/g, '\n\n')
                        .trim();
                }
            """)
        except Exception:
            pass
        try:
            data.links = await page.eval_on_selector_all(
                "a[href]", "els => [...new Set(els.map(e => e.href))]"
            )
        except Exception:
            pass
        data.pdf_links = [u for u in data.links if _is_pdf(u)]
        return data

    # ── Single-page crawl ──────────────────────────────────────

    async def _crawl_page(self, page: Page, url: str) -> PageData:
        data = PageData(url=url)
        try:
            # "domcontentloaded" never hangs — unlike "networkidle"
            resp: Response | None = await page.goto(
                url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT
            )
            if resp and resp.status >= 400:
                data.error = f"HTTP {resp.status}"
                print(f"  ✗ {data.error}")
                return data
            # Give JS a moment to render without waiting for analytics calls
            await page.wait_for_timeout(600)
        except Exception as exc:
            data.error = str(exc)[:120]
            print(f"  ✗ {data.error}")
            return data

        # Expand hidden content
        await self._hover_nav(page)
        await self._expand_tabs(page)
        await self._expand_accordions(page)
        await self._click_show_more(page)

        js_links = await self._intercept_js_links(page)
        data = await self._extract(page, url)
        data.links = list(dict.fromkeys(data.links + js_links))
        data.pdf_links = list({u for u in data.links if _is_pdf(u)})

        print(
            f"  ✓  title={repr(data.title)[:48]}\n"
            f"     links={len(data.links)}  pdfs={len(data.pdf_links)}"
            f"  chars={len(data.content)}"
        )
        return data

    # ── PDF download ───────────────────────────────────────────

    async def _download_pdf(self, page: Page, pdf_url: str) -> None:
        filename = _safe_filename(pdf_url)
        dest = PDF_DIR / filename
        if dest.exists():
            print(f"  [PDF] skip (exists): {filename}")
            return
        print(f"  [PDF] downloading: {filename} …")
        try:
            resp = await page.request.get(pdf_url, timeout=40_000)
            if resp.ok:
                PDF_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(await resp.body())
                print(f"  [PDF] saved → {dest.name}")
            else:
                print(f"  [PDF] HTTP {resp.status}: {pdf_url}")
        except Exception as exc:
            print(f"  [PDF] error: {exc}")

    # ── Main run ───────────────────────────────────────────────

    async def run(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=False,
                # no slow_mo — delays multiplied across hundreds of actions
            )
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page: Page = await context.new_page()

            # ── Phase 0 ────────────────────────────────────────
            _banner("Phase 0 · Seed Discovery")
            await self._seed_from_paths(page)
            self._enqueue(START_URL)
            print(f"  Queue: {len(self.queue)} seed URL(s)")

            # ── Phase 1 ────────────────────────────────────────
            _banner("Phase 1 · Navigation Menu Discovery")
            try:
                print(f"  Loading {START_URL} …")
                await page.goto(
                    START_URL,
                    wait_until="domcontentloaded",   # never hangs
                    timeout=PAGE_TIMEOUT,
                )
                await page.wait_for_timeout(800)     # let JS settle
                print("  Homepage loaded. Hovering nav items …")
                nav_links = await self._hover_nav(page)
                self._enqueue_many(nav_links)
                print(f"  Queue after nav discovery: {len(self.queue)} URL(s)")
            except Exception as exc:
                print(f"  [Warn] Nav discovery failed: {exc}")

            # ── Phase 2 ────────────────────────────────────────
            _banner("Phase 2 · BFS Deep Crawl")

            while self.queue:
                if len(self.visited) >= MAX_PAGES:
                    print(f"\n[Limit] Reached MAX_PAGES={MAX_PAGES}")
                    break

                url = self.queue.pop(0)
                norm = _normalize(url)
                if norm in self.visited:
                    continue
                self.visited.add(norm)

                print(
                    f"\n[{len(self.visited):>4}/{MAX_PAGES}]"
                    f"  queue={len(self.queue)}"
                    f"  pdfs={len(self.pdf_queue)}"
                )
                print(f"[Page] {norm}")

                data = await self._crawl_page(page, norm)
                self.pages[norm] = data

                if data.error:
                    self.errors.append(f"{norm}  →  {data.error}")
                    continue

                self._enqueue_many(data.links)
                for pdf in data.pdf_links:
                    self.pdf_queue.add(pdf)

            # ── Phase 3 ────────────────────────────────────────
            _banner(f"Phase 3 · PDF Downloads  ({len(self.pdf_queue)} found)")
            for pdf_url in sorted(self.pdf_queue):
                await self._download_pdf(page, pdf_url)

            await browser.close()

        # ── Save ───────────────────────────────────────────────
        _banner("Saving Outputs")
        self._save_txt()
        self._save_report()

        _banner("DONE")
        print(f"  Pages crawled  : {len(self.pages)}")
        print(f"  Pages OK       : {sum(1 for d in self.pages.values() if not d.error)}")
        print(f"  PDFs found     : {len(self.pdf_queue)}")
        print(f"  Errors         : {len(self.errors)}")
        print(f"  Content file   : {CRAWL_TXT}")
        print(f"  Report file    : {CRAWL_REPORT}")
        print(f"  PDFs dir       : {PDF_DIR}")
        if self.errors:
            print("\n  Error list:")
            for e in self.errors[:30]:
                print(f"    • {e}")

    # ── Output helpers ─────────────────────────────────────────

    def _save_txt(self) -> None:
        with open(CRAWL_TXT, "w", encoding="utf-8") as fh:
            for url, data in self.pages.items():
                if data.error or not data.content:
                    continue
                fh.write(f"PAGE_URL: {url}\n\n")
                if data.title:
                    fh.write(f"TITLE: {data.title}\n\n")
                if data.headings:
                    fh.write("HEADINGS:\n")
                    for h in data.headings:
                        fh.write(f"  {h}\n")
                    fh.write("\n")
                fh.write("CONTENT:\n")
                fh.write(data.content)
                fh.write("\n\n" + "─" * 60 + "\n\n")
        print(f"  Saved: {CRAWL_TXT}")

    def _save_report(self) -> None:
        report = {
            "summary": {
                "pages_crawled": len(self.pages),
                "pages_ok": sum(1 for d in self.pages.values() if not d.error),
                "pages_error": sum(1 for d in self.pages.values() if d.error),
                "pdfs_found": len(self.pdf_queue),
                "total_errors": len(self.errors),
            },
            "pages": [
                {
                    "url": url,
                    "title": d.title,
                    "headings": d.headings,
                    "link_count": len(d.links),
                    "pdf_links": d.pdf_links,
                    "content_length": len(d.content),
                    "error": d.error or None,
                }
                for url, d in self.pages.items()
            ],
            "pdf_urls": sorted(self.pdf_queue),
            "errors": self.errors,
        }
        CRAWL_REPORT.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  Saved: {CRAWL_REPORT}")


# ──────────────────────────────────────────────────────────────

def _banner(text: str) -> None:
    print("\n" + "═" * 60)
    print(f"  {text}")
    print("═" * 60)


if __name__ == "__main__":
    crawler = MSRITIntelligentCrawler()
    asyncio.run(crawler.run())
