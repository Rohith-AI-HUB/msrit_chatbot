"""
Parents Portal Scraper
======================
Logs into https://parents.msrit.edu/newparents/index.php with USN + DOB.

Login form structure (from UI):
  - Username field: <input> with placeholder "USN"
  - Password field: THREE <select> dropdowns — Day / Month / Year
  - Submit: "LOGIN" button

Runs headless Chromium via Playwright — no CAPTCHA on this portal.
"""

import re
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser

from config import settings
from shared.logging import setup_logger

logger = setup_logger("parents-scraper")

# Table section header keywords used to classify tables
ATTENDANCE_KEYWORDS = ["attendance", "present", "absent", "held", "classes", "percentage"]
MARKS_KEYWORDS = ["marks", "cie", "internal", "test", "ia", "score", "grade", "subject"]


# ── Main entry point ──────────────────────────────────────────────────────────

async def fetch_portal_data(usn: str, dob: str) -> dict:
    """
    Returns:
        {
          "success": True/False,
          "error": "..." (on failure),
          "student_info": {...},
          "attendance": [...],
          "marks": [...],
          "raw_text": "..."   # fallback plain text
        }
    """
    logger.info(f"Fetching portal data for USN={usn}")

    dob_parts = _parse_dob(dob)
    if not dob_parts:
        return {"success": False, "error": "Could not parse date of birth. Use DD/MM/YYYY format."}

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            result = await _login_and_scrape(page, usn, dob_parts)
            return result
        except Exception as exc:
            logger.exception(f"Scraper error: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            await browser.close()


# ── Login ─────────────────────────────────────────────────────────────────────

async def _login_and_scrape(page: Page, usn: str, dob_parts: dict) -> dict:
    logger.info(f"Navigating to {settings.PORTAL_URL}")
    await page.goto(settings.PORTAL_URL, wait_until="domcontentloaded", timeout=settings.SCRAPE_TIMEOUT_MS)
    await page.wait_for_timeout(1500)

    # ── Fill USN (Username field with placeholder "USN") ──────────────────────
    usn_selectors = [
        "input[placeholder='USN']",
        "input[placeholder*='USN' i]",
        "input[name='username']",
        "input[name='usn']",
        "input[id='username']",
        "input[id='usn']",
        "input[type='text']:first-of-type",
    ]
    usn_el = None
    for sel in usn_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=800):
                usn_el = el
                break
        except Exception:
            pass

    if usn_el is None:
        return {"success": False, "error": "Could not find the USN input field on the login page."}

    await usn_el.fill(usn)
    logger.info(f"USN filled: {usn}")

    # ── Fill DOB via three <select> dropdowns (Day / Month / Year) ────────────
    #
    # The portal uses:
    #   select[0]  → Day   (options: "Day", "1".."31")
    #   select[1]  → Month (options: "Month", "1".."12"  OR  "January".."December")
    #   select[2]  → Year  (options: "Year", "1990".."2010" etc.)
    #
    dob_filled = await _fill_dob_selects(page, dob_parts)
    if not dob_filled:
        return {"success": False, "error": "Could not find the Date of Birth dropdowns on the login page."}

    # ── Click LOGIN button ────────────────────────────────────────────────────
    login_selectors = [
        "button:text('LOGIN')",
        "button:text('Login')",
        "input[value='LOGIN']",
        "input[value='Login']",
        "button[type='submit']",
        "input[type='submit']",
        "a:text('LOGIN')",
        "a:text('Login')",
    ]
    clicked = False
    for sel in login_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=800):
                await el.click()
                clicked = True
                logger.info(f"Clicked login: {sel}")
                break
        except Exception:
            pass

    if not clicked:
        await page.keyboard.press("Enter")
        logger.info("Login via Enter key")

    # Wait for navigation after login
    await page.wait_for_timeout(settings.NAV_WAIT_MS)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass

    # ── Check for login failure ───────────────────────────────────────────────
    body_text = await page.inner_text("body")
    body_lower = body_text.lower()
    failure_phrases = [
        "invalid", "incorrect", "wrong", "not found",
        "login failed", "unauthorized", "please check", "no record",
        "error", "mismatch",
    ]
    # Only treat as failure if still on login page (no dashboard content found)
    still_on_login = await page.locator("input[placeholder*='USN' i], input[name='username']").count() > 0
    if still_on_login and any(p in body_lower for p in failure_phrases):
        return {
            "success": False,
            "error": "Login failed — invalid USN or Date of Birth. Please check your credentials.",
        }
    # Also fail if the URL hasn't changed and we still see the form
    if still_on_login:
        return {
            "success": False,
            "error": "Login did not proceed. The USN or Date of Birth may be incorrect.",
        }

    logger.info("Login successful — scraping dashboard")
    return await _scrape_dashboard(page)


# ── DOB Select Fill ───────────────────────────────────────────────────────────

MONTH_ABBREVS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL    = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]


async def _fill_dob_selects(page: Page, dob_parts: dict) -> bool:
    """
    Fill the three DOB dropdowns (Day / Month / Year).

    Strategy: inspect actual option values/texts first, then select the
    matching one directly — avoids Playwright's 30-second per-attempt timeout
    that burned 60+ seconds on failed guesses.
    """
    day_num   = int(dob_parts["day"])    # 4
    month_num = int(dob_parts["month"])  # 8
    year_str  = dob_parts["year"]        # "2003"

    select_count = await page.locator("select").count()
    logger.info(f"Found {select_count} <select> elements")
    if select_count < 3:
        return False

    # ── Inspect all selects once ─────────────────────────────────────────────
    sel_info = []
    for i in range(select_count):
        el = page.locator("select").nth(i)
        try:
            values = await el.evaluate("el => [...el.options].map(o => o.value.trim())")
            texts  = await el.evaluate("el => [...el.options].map(o => o.text.trim())")
            first  = texts[0].lower() if texts else ""
            logger.info(f"Select[{i}] first='{first}' sample_vals={values[:4]} sample_texts={texts[:4]}")
            sel_info.append({"el": el, "values": values, "texts": texts, "first": first})
        except Exception as e:
            logger.warning(f"Could not inspect select[{i}]: {e}")
            sel_info.append({"el": el, "values": [], "texts": [], "first": ""})

    # ── Identify day / month / year selects ──────────────────────────────────
    day_info = month_info = year_info = None
    for info in sel_info:
        f = info["first"]
        if "day" in f:
            day_info = info
        elif "month" in f:
            month_info = info
        elif "year" in f:
            year_info = info

    # Positional fallback (Day=0, Month=1, Year=2)
    if day_info   is None and len(sel_info) >= 1: day_info   = sel_info[0]
    if month_info is None and len(sel_info) >= 2: month_info = sel_info[1]
    if year_info  is None and len(sel_info) >= 3: year_info  = sel_info[2]

    # ── Select Day ────────────────────────────────────────────────────────────
    filled_day = False
    if day_info:
        filled_day = await _pick_option(
            day_info,
            candidates=[str(day_num), f"{day_num:02d}"],
        )
        logger.info(f"Day filled={filled_day}")

    # ── Select Month ──────────────────────────────────────────────────────────
    filled_month = False
    if month_info:
        filled_month = await _pick_option(
            month_info,
            candidates=[
                str(month_num), f"{month_num:02d}",
                MONTH_ABBREVS[month_num - 1],
                MONTH_FULL[month_num - 1],
            ],
        )
        logger.info(f"Month filled={filled_month}")

    # ── Select Year ───────────────────────────────────────────────────────────
    filled_year = False
    if year_info:
        filled_year = await _pick_option(year_info, candidates=[year_str])
        logger.info(f"Year filled={filled_year}")

    return filled_day or filled_month or filled_year


async def _pick_option(info: dict, candidates: list[str]) -> bool:
    """
    Select the first matching option by checking actual values/texts — no
    timeout wasted on wrong guesses.
    """
    el     = info["el"]
    values = info["values"]
    texts  = info["texts"]

    for candidate in candidates:
        if candidate in values:
            await el.select_option(value=candidate)
            return True
        if candidate in texts:
            await el.select_option(label=candidate)
            return True

    # Last resort: partial text match
    for candidate in candidates:
        for text in texts:
            if text.lower() == candidate.lower():
                await el.select_option(label=text)
                return True

    logger.warning(f"No match for {candidates} in values={values[:6]} texts={texts[:6]}")
    return False


# ── Dashboard Scraping ────────────────────────────────────────────────────────

async def _scrape_dashboard(page: Page) -> dict:
    """Scrape student info, attendance, CIE marks, and SEE results from the dashboard."""

    result: dict = {
        "success": True,
        "student_info": {},
        "attendance": [],
        "marks": [],
        "see_results": None,
        "raw_text": "",
    }

    # ── Student info from body text ───────────────────────────────────────────
    result["student_info"] = await _extract_student_info(page)

    # ── Attendance: parse the main dashboard table ────────────────────────────
    tables = await _extract_tables(page)
    for tbl in tables:
        if _looks_like_attendance(tbl):
            # Strip "LESSON PLAN" / "COURSE MATERIALS" columns — keep useful ones
            result["attendance"].append(_clean_attendance_table(tbl))

    # ── Extract exam history URL from dashboard BEFORE navigating away ────────
    exam_history_url = await page.evaluate("""() => {
        const a = [...document.querySelectorAll('a')].find(el => {
            const oc = el.getAttribute('onclick') || '';
            const hr = el.getAttribute('href') || '';
            return oc.includes('getResult') || hr.includes('getResult');
        });
        if (!a) return null;
        // .href gives the absolute URL resolved by the browser
        if (a.href && a.href.includes('getResult')) return a.href;
        // Fallback: extract from onclick="window.location.href='...'"
        const oc = a.getAttribute('onclick') || '';
        const marker = "window.location.href='";
        const start = oc.indexOf(marker);
        if (start >= 0) {
            const rel = oc.substring(start + marker.length, oc.indexOf("'", start + marker.length));
            return rel.startsWith('http') ? rel
                 : 'https://parents.msrit.edu/newparents/' + rel;
        }
        return null;
    }""")
    logger.info(f"Exam history URL found: {bool(exam_history_url)}")

    # ── CIE Marks: navigate via JS onclick links on the dashboard ─────────────
    try:
        result["marks"] = await _scrape_cie_marks(page)
    except Exception as e:
        logger.warning(f"CIE marks scraping failed: {e}")

    # ── SEE Results: navigate to exam history page ────────────────────────────
    if exam_history_url:
        try:
            result["see_results"] = await _scrape_exam_history(page, exam_history_url)
        except Exception as e:
            logger.warning(f"Exam history scraping failed: {e}")

    # ── Fallback raw text ─────────────────────────────────────────────────────
    if not result["attendance"] and not result["marks"] and not result["see_results"]:
        raw = await page.inner_text("body")
        result["raw_text"] = raw.strip()[:4000]
        logger.info("No structured tables — returning raw text")

    return result


def _clean_attendance_table(tbl: dict) -> dict:
    """Remove LESSON PLAN / COURSE MATERIALS columns from the attendance table."""
    drop_cols = {"lesson plan", "course materials"}
    headers = tbl.get("headers", [])
    keep_idx = [i for i, h in enumerate(headers) if h.lower() not in drop_cols]
    return {
        "headers": [headers[i] for i in keep_idx],
        "rows": [
            [row[i] for i in keep_idx if i < len(row)]
            for row in tbl.get("rows", [])
        ],
    }


async def _scrape_cie_marks(page: Page) -> list:
    """
    Navigate to the CIE page and collect marks for every course.

    How the portal works:
      - Dashboard has empty CIE links (href contains ciedetails but wrong secId)
      - After clicking ANY ciedetails link, the CIE page loads
      - CIE page has a sidebar with <a onclick="window.location.href='index.php?...&secId=450'">
        per course — these have the CORRECT secId
      - We execute each onclick URL and scrape the marks table
    """
    BASE = "https://parents.msrit.edu/newparents/"

    # Close any modal that blocks clicks
    await page.evaluate("""() => {
        document.querySelectorAll('.uk-modal.uk-open, [id=ebook]').forEach(m => {
            m.classList.remove('uk-open');
            m.style.display = 'none';
        });
    }""")

    # Click the first CIE link — use expect_navigation so we wait for load properly
    cie_count = await page.locator("a[href*='ciedetails']").count()
    if cie_count == 0:
        logger.info("No ciedetails links found on dashboard")
        return []

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.evaluate("document.querySelector(\"a[href*='ciedetails']\").click()")
    except Exception:
        await page.wait_for_timeout(3000)   # fallback if navigation event misfires

    logger.info(f"Navigated to CIE page: {page.url[:60]}")

    # Extract course sidebar onclick URLs (these have the correct secId)
    course_info = await page.evaluate(f"""() => {{
        const base = '{BASE}';
        return [...document.querySelectorAll('a[onclick*=ciedetails]')].map(a => {{
            const m = a.getAttribute('onclick').match(/window\\.location\\.href='([^']+)'/);
            if (!m) return null;
            const rel = m[1];
            const url = rel.startsWith('http') ? rel : base + rel;
            const li = a.closest('li');
            const code = li ? li.innerText.trim() : a.innerText.trim();
            return {{ url, code }};
        }}).filter(Boolean);
    }}""")

    logger.info(f"Found {len(course_info)} CIE course links")
    if not course_info:
        return []

    all_marks = []

    for item in course_info:
        url  = item["url"]
        code = item["code"]
        try:
            # Use window.location.href (preserves ksign session) +
            # expect_navigation (waits for load to complete) to avoid
            # "Execution context was destroyed" errors from unwaited navigation
            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
                    await page.evaluate(f"window.location.href = '{url}'")
            except Exception:
                await page.wait_for_timeout(2000)   # fallback

            # Extract course name: "COURSECODE - Course Name" pattern in body
            body_text = await page.inner_text("body")
            m = re.search(rf'{re.escape(code)}\s*[-–]\s*([^\n]+)', body_text)
            course_name = m.group(1).strip() if m else code

            # Find the marks table (must have FINAL CIE column)
            tables = await _extract_tables(page)
            marks_tbl = None
            for tbl in tables:
                hdrs = " ".join(tbl.get("headers", [])).lower()
                if "final cie" in hdrs:
                    marks_tbl = tbl
                    break

            if marks_tbl and marks_tbl.get("rows"):
                row     = marks_tbl["rows"][0]
                headers = marks_tbl["headers"]
                entry   = {"course_code": code, "course_name": course_name}
                for j, h in enumerate(headers):
                    entry[h] = row[j] if j < len(row) else "-"
                all_marks.append(entry)
                logger.info(f"CIE scraped for {code}: CIE={entry.get('FINAL CIE', '?')}")
            else:
                logger.warning(f"No marks table for {code}")
                all_marks.append({
                    "course_code": code, "course_name": course_name,
                    "FINAL CIE": "Not entered", "ATTENDANCE": "-",
                })

        except Exception as e:
            logger.warning(f"Failed CIE for {code}: {e}")
            all_marks.append({
                "course_code": code, "course_name": code,
                "FINAL CIE": "Error", "ATTENDANCE": "-",
            })

    return all_marks


# ── SEE / Exam History Scraping ───────────────────────────────────────────────

async def _scrape_exam_history(page: Page, url: str) -> Optional[dict]:
    """
    Navigate to the EXAM HISTORY page and extract semester-wise SEE results.

    Page structure (observed):
      Cumulative History
      Credits Earned: 22 | Credits to be Earned: 58 | CGPA: 8.45
      ODD Jan 2026 | CREDITS REGISTERED: 22 | CREDITS EARNED: 22 | SGPA: 8.45
      Table: COURSE CODE | SUBJECT NAME | CREDITS REG. | CREDITS EARNED | GPA | GRADE

    Returns:
        {
          "cgpa": "8.45",
          "credits_earned": "22",
          "credits_to_earn": "58",
          "semesters": [
            {
              "name": "ODD Jan 2026",
              "sgpa": "8.45",
              "courses": [
                {"COURSE CODE": "25MCS13", "SUBJECT NAME": "...", "GPA": "8", "GRADE": "A", ...}
              ]
            }
          ]
        }
    """
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.evaluate(f"window.location.href = '{url}'")
    except Exception:
        await page.wait_for_timeout(3000)

    logger.info(f"Navigated to exam history: {page.url[:80]}")
    body_text = await page.inner_text("body")

    # ── Cumulative stats from body text ───────────────────────────────────────
    # "Credits to be Earned" must be matched before "Credits Earned" to avoid
    # the shorter pattern consuming it first
    to_earn_m = re.search(r'Credits?\s+to\s+be\s+Earned\s*:?\s*(\d+)', body_text, re.IGNORECASE)
    earned_m  = re.search(r'Credits?\s+Earned\s*:?\s*(\d+)', body_text, re.IGNORECASE)
    cgpa_m    = re.search(r'CGPA\s*:?\s*([\d.]+)', body_text, re.IGNORECASE)

    cgpa           = cgpa_m.group(1)    if cgpa_m    else "-"
    credits_earned = earned_m.group(1)  if earned_m  else "-"
    credits_to_earn = to_earn_m.group(1) if to_earn_m else "-"

    # ── Extract result tables (have GRADE or GPA columns) ─────────────────────
    all_tables = await _extract_tables(page)
    result_tables = [
        tbl for tbl in all_tables
        if any(k in " ".join(tbl.get("headers", [])).lower() for k in ["grade", "gpa"])
    ]
    logger.info(f"Exam history: found {len(result_tables)} result table(s)")

    # ── Per-semester name and SGPA from body text ─────────────────────────────
    sem_names  = re.findall(r'((?:ODD|EVEN)\s+\w+\s+\d{4})', body_text, re.IGNORECASE)
    sgpa_vals  = re.findall(r'SGPA\s*:?\s*([\d.]+)', body_text, re.IGNORECASE)

    semesters = []
    for i, tbl in enumerate(result_tables):
        headers = tbl.get("headers", [])
        courses = []
        for row in tbl.get("rows", []):
            padded = row + ["-"] * max(0, len(headers) - len(row))
            courses.append({h: padded[j] for j, h in enumerate(headers)})

        semesters.append({
            "name": sem_names[i] if i < len(sem_names) else f"Semester {i + 1}",
            "sgpa": sgpa_vals[i]  if i < len(sgpa_vals)  else "-",
            "courses": courses,
        })

    return {
        "cgpa":           cgpa,
        "credits_earned": credits_earned,
        "credits_to_earn": credits_to_earn,
        "semesters":      semesters,
    }


# ── Student Info ──────────────────────────────────────────────────────────────

async def _extract_student_info(page: Page) -> dict:
    try:
        info = await page.evaluate("""
            () => {
                const result = {};
                const KEYS = ['name','branch','department','semester','section','usn','year','programme','class'];
                document.querySelectorAll('table tr').forEach(tr => {
                    const cells = tr.querySelectorAll('td, th');
                    if (cells.length >= 2) {
                        const key = cells[0].innerText.trim().replace(/:$/, '');
                        const val = cells[1].innerText.trim();
                        if (key && val && key.length < 40 && val.length < 100) {
                            if (KEYS.some(k => key.toLowerCase().includes(k))) {
                                result[key] = val;
                            }
                        }
                    }
                });
                return result;
            }
        """)
        return info if isinstance(info, dict) else {}
    except Exception as e:
        logger.warning(f"Student info extraction failed: {e}")
        return {}


# ── Table Extraction ──────────────────────────────────────────────────────────

async def _extract_tables(page: Page) -> list:
    try:
        tables = await page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table').forEach(table => {
                    const headerCells = [];
                    const rows = [];
                    let headerRow = table.querySelector('tr:first-child');
                    if (headerRow) {
                        [...headerRow.querySelectorAll('th, td')].forEach(c => {
                            headerCells.push(c.innerText.trim());
                        });
                    }
                    table.querySelectorAll('tr').forEach((tr, ri) => {
                        if (ri === 0) return;
                        const cells = [...tr.querySelectorAll('td')].map(c => c.innerText.trim());
                        if (cells.some(c => c)) rows.push(cells);
                    });
                    if (headerCells.length > 0 && rows.length > 0) {
                        result.push({ headers: headerCells, rows });
                    }
                });
                return result;
            }
        """)
        return tables if isinstance(tables, list) else []
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
        return []


# ── Table Classification ──────────────────────────────────────────────────────

def _looks_like_attendance(tbl: dict) -> bool:
    text = " ".join(tbl.get("headers", [])).lower()
    return any(k in text for k in ATTENDANCE_KEYWORDS)


def _looks_like_marks(tbl: dict) -> bool:
    text = " ".join(tbl.get("headers", [])).lower()
    return any(k in text for k in MARKS_KEYWORDS)




# ── DOB Format Parser ─────────────────────────────────────────────────────────

def _parse_dob(dob: str) -> Optional[dict]:
    """Parse DD/MM/YYYY (or DD-MM-YYYY, DD.MM.YYYY) into component parts."""
    m = re.match(r'^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$', dob.strip())
    if not m:
        return None
    return {
        "day":   m.group(1).zfill(2),
        "month": m.group(2).zfill(2),
        "year":  m.group(3),
    }
