"""
Result Service
==============
Handles the multi-turn result-checking flow:
  1. Detect "what is my result" intent
  2. Ask for USN
  3. Ask for DOB
  4. Open a visible browser, fill form, wait for user to solve CAPTCHA
  5. Scrape result and return to chat

Uses a background thread per session so the browser stays open
across chat turns while waiting for the user to submit.
"""

import asyncio
import re
import threading
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright, Page


RESULTS_URL = "https://exam.msrit.edu/"

RESULT_INTENT_KEYWORDS = [
    "my result", "my marks", "my grade", "my score",
    "check result", "exam result", "semester result",
    "show result", "view result", "what are my marks",
    "check my result", "see my result", "view my result",
    "my exam result", "my semester result",
]

# Keywords that override result intent detection (prevent false positives)
RESULT_EXCLUSION_KEYWORDS = [
    "attendance", "percentage", "cgpa", "sgpa", "internal",
    "assignment", "class", "lecture",
]

USN_SELECTORS = [
    "input[placeholder*='USN' i]",
    "input[name*='usn' i]",
    "input[id*='usn' i]",
    "input[placeholder*='seat' i]",
    "input[type='text']:first-of-type",
]

DOB_SELECTORS = [
    "input[type='date']",
    "input[placeholder*='DOB' i]",
    "input[placeholder*='birth' i]",
    "input[name*='dob' i]",
    "input[name*='date' i]",
    "input[placeholder*='date' i]",
]


@dataclass
class ResultSession:
    usn: str = ""
    dob: str = ""
    # idle → waiting_usn → waiting_dob → browser_open → done / error
    status: str = "waiting_usn"
    result_text: str = ""
    error: str = ""
    thread: Optional[threading.Thread] = field(default=None, repr=False)


# In-memory store — one per chat session
_sessions: dict[str, ResultSession] = {}


def is_result_intent(question: str) -> bool:
    q = question.lower()
    if any(ex in q for ex in RESULT_EXCLUSION_KEYWORDS):
        return False
    return any(k in q for k in RESULT_INTENT_KEYWORDS)


def is_show_result(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in ["show result", "get result", "my result", "done", "submitted"])


class ResultService:

    # ── session helpers ──────────────────────────────────────────

    @classmethod
    def in_flow(cls, session_id: str) -> bool:
        return session_id in _sessions

    @classmethod
    def _get(cls, session_id: str) -> Optional[ResultSession]:
        return _sessions.get(session_id)

    @classmethod
    def _start(cls, session_id: str) -> ResultSession:
        s = ResultSession()
        _sessions[session_id] = s
        return s

    @classmethod
    def _clear(cls, session_id: str):
        _sessions.pop(session_id, None)

    # ── state machine ─────────────────────────────────────────────

    @classmethod
    def handle(cls, session_id: str, question: str) -> Optional[str]:
        """
        Main entry point. Returns a response string if the question
        is part of the result flow, or None to fall through to RAG.
        """
        q = question.strip()

        # ── Initial intent detection ──
        if not cls.in_flow(session_id):
            if is_result_intent(q):
                cls._start(session_id)
                return (
                    "I can check your result from the MSRIT exam portal.\n\n"
                    "Please provide your **USN** (e.g. 1MS22CS001)."
                )
            return None  # not a result query

        session = cls._get(session_id)

        # ── Collecting USN ──
        if session.status == "waiting_usn":
            # Accept anything that looks like a USN (alphanumeric, 6-15 chars)
            usn = re.sub(r'\s+', '', q).upper()
            if len(usn) < 6 or len(usn) > 15 or not re.search(r'\d', usn):
                return "That doesn't look like a valid USN. Please enter it again (e.g. 1MS22CS001)."
            session.usn = usn
            session.status = "waiting_dob"
            return f"USN set to **{usn}**.\n\nNow enter your **Date of Birth** in DD/MM/YYYY format."

        # ── Collecting DOB ──
        if session.status == "waiting_dob":
            dob = q.strip()
            if not re.search(r'\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4}', dob):
                return "Please enter date of birth in **DD/MM/YYYY** format (e.g. 15/08/2002)."
            session.dob = dob
            session.status = "browser_open"
            cls._launch_browser(session_id)
            return (
                f"**Opening browser...**\n\n"
                f"- USN: `{session.usn}`\n"
                f"- DOB: `{session.dob}`\n\n"
                f"The form is being filled in the browser window that just opened on your screen. "
                f"**Solve the CAPTCHA** and click **Submit**.\n\n"
                f"Once submitted, type **show result** here."
            )

        # ── Browser open — waiting for user to submit ──
        if session.status == "browser_open":
            if is_show_result(q):
                return (
                    "Still waiting for the browser to return your result.\n"
                    "Please make sure you solved the CAPTCHA and clicked Submit in the browser window. "
                    "Then type **show result** again."
                )
            return (
                "The browser window is open on your screen.\n"
                "1. Solve the CAPTCHA\n"
                "2. Click Submit\n"
                "3. Type **show result** here once done."
            )

        # ── Result ready ──
        if session.status == "done":
            result = session.result_text
            cls._clear(session_id)
            if result:
                # Trim to first 3000 chars to keep response readable
                trimmed = result[:3000] + ("..." if len(result) > 3000 else "")
                return f"**Your Result:**\n\n```\n{trimmed}\n```"
            return "The page loaded but result content could not be extracted. Please check the browser window."

        # ── Error ──
        if session.status == "error":
            err = session.error
            cls._clear(session_id)
            return f"Result fetch failed: {err}\n\nType 'check result' to try again."

        return None

    # ── Playwright browser task ───────────────────────────────────

    @classmethod
    def _launch_browser(cls, session_id: str):
        session = _sessions[session_id]

        def run():
            asyncio.run(cls._browser_task(session))

        t = threading.Thread(target=run, daemon=True)
        session.thread = t
        t.start()

    @classmethod
    async def _browser_task(cls, session: ResultSession):
        try:
            async with async_playwright() as pw:
                # headless=False so user can see and solve CAPTCHA
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page()

                await page.goto(RESULTS_URL, wait_until="domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(1500)

                # Fill USN
                usn_el = await cls._find(page, USN_SELECTORS)
                if usn_el:
                    await usn_el.triple_click()
                    await usn_el.type(session.usn, delay=60)

                # Fill DOB
                dob_el = await cls._find(page, DOB_SELECTORS)
                if dob_el:
                    await dob_el.triple_click()
                    # Try typing directly; for date inputs also try fill()
                    try:
                        await dob_el.fill(session.dob)
                    except Exception:
                        await dob_el.type(session.dob, delay=60)

                # Wait up to 5 minutes for result page to appear
                # (user needs to solve CAPTCHA and submit)
                found = await cls._wait_for_result(page, timeout_s=300)

                if found:
                    text = await page.evaluate("""
                        () => {
                            const tables = [...document.querySelectorAll('table')];
                            if (tables.length) {
                                return tables.map(t => t.innerText).join('\\n\\n');
                            }
                            return document.body.innerText;
                        }
                    """)
                    session.result_text = text.strip()
                    session.status = "done"
                else:
                    session.error = "Timed out waiting for result (5 minutes). Please try again."
                    session.status = "error"

                # Keep browser open briefly so user can see result
                await page.wait_for_timeout(5000)
                await browser.close()

        except Exception as e:
            session.error = str(e)
            session.status = "error"

    @staticmethod
    async def _wait_for_result(page: Page, timeout_s: int = 300) -> bool:
        """
        Poll every 2 seconds until a result table/div appears or timeout.
        """
        RESULT_SELS = [
            "table:not(:empty)",
            ".result-table",
            "[id*='result' i]",
            "[class*='result' i]",
            ".marks",
            "#marks",
        ]
        for _ in range(timeout_s // 2):
            await asyncio.sleep(2)
            for sel in RESULT_SELS:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        # Extra wait for full render
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    pass
        return False

    @staticmethod
    async def _find(page: Page, selectors: list[str]):
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible():
                    return el
            except Exception:
                pass
        return None
