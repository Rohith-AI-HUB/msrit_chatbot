import re
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


RESULT_INTENT_KEYWORDS = [
    "result", "my result", "my marks", "my grade", "my score",
    "check result", "exam result", "semester result",
    "show result", "view result", "what are my marks",
    "check my result", "see my result", "view my result",
    "my exam result", "my semester result",
    "want my result", "want my marks", "get my result",
    "marks", "semester marks", "subject marks",
    "cie", "internal assessment", "internal marks",
    "parents portal", "parent portal", "academic performance",
]

RESULT_EXCLUSION_KEYWORDS = [
    "attendance", "percentage", "class", "lecture",
    "assignment", "hall ticket", "time table",
]

PARENTS_BASE = "https://parents.msrit.edu/newparents/"
PARENTS_LOGIN = PARENTS_BASE + "index.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class ParentSession:
    usn: str = ""
    dob: str = ""
    status: str = "waiting_usn"


@dataclass
class ResultResponse:
    answer: str
    input_type: Optional[str] = None


_sessions: dict[str, ParentSession] = {}


def is_result_intent(question: str) -> bool:
    q = question.lower().strip()
    if not q or any(ex in q for ex in RESULT_EXCLUSION_KEYWORDS):
        return False
    if q in ("usn", "dob", "date of birth"):
        return False
    return any(k in q for k in RESULT_INTENT_KEYWORDS)


def _format_date(dob: str) -> str:
    parts = re.split(r'[/\-\.]', dob)
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"


def _extract_student_info(soup: BeautifulSoup) -> dict:
    info = {"name": "", "usn": "", "program": ""}
    for h3 in soup.find_all("h3"):
        txt = h3.get_text(strip=True)
        if txt and not any(x in (txt.lower()) for x in ["internal", "attendance", "title", "modal"]):
            info["name"] = txt
            break
    for h2 in soup.find_all("h2"):
        txt = h2.get_text(strip=True)
        if re.match(r'^\d+[A-Za-z]+\d+', txt):
            info["usn"] = txt
            break
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if any(x in txt for x in ["M.Tech", "B.E", "B.Arch", "MCA", "MBA"]):
            info["program"] = txt
            break
    return info


def _parse_exam_history(soup: BeautifulSoup) -> str:
    lines = []
    tables = soup.find_all("table", class_="res-table")
    for table in tables:
        caption = table.find("caption")
        if not caption:
            continue
        title = caption.get_text(" ", strip=True)
        lines.append(f"\n### {title}")
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        lines.append("| Course Code | Subject | Reg | Earned | GPA | Grade |")
        lines.append("|------------|---------|----|--------|-----|-------|")
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) >= 6:
                c = [col.get_text(strip=True) for col in cols[:6]]
                lines.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} | {c[4]} | {c[5]} |")
    return "\n".join(lines)


def _get_courses_from_cie_page(soup: BeautifulSoup) -> list[dict]:
    courses = []
    for li in soup.find_all("li", id=re.compile(r"tab\d")):
        tooltip = li.get("uk-tooltip", "")
        a = li.find("a")
        if not a:
            continue
        onclick = a.get("onclick", "")
        m = re.search(r'courseId=(\d+)&secId=(\d+)', onclick)
        if m:
            code = a.get_text(strip=True)
            name = ""
            if "title:" in tooltip:
                name = tooltip.split("title:")[1].split(";")[0].strip()
            courses.append({
                "id": m.group(1),
                "sec_id": m.group(2),
                "code": code,
                "name": name,
            })
    return courses


def _parse_placement(client: httpx.Client) -> str:
    lines = []
    for task, label in [
        ("placementeligibility", "Events to Register"),
        ("placementstatus", "Events in Progress"),
        ("placementresults", "Events Completed"),
    ]:
        url = (
            f"{PARENTS_BASE}index.php"
            f"?option=com_placement"
            f"&controller=placement"
            f"&task={task}"
        )
        resp = client.get(url, headers=HEADERS, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")

        items = soup.select("ul.cn-elig_list > li")
        if not items:
            continue

        lines.append(f"\n#### {label}")
        lines.append("| Company | Apply Before | Event Date | Salary | Status |")
        lines.append("|---------|-------------|------------|--------|--------|")

        for li in items:
            cards = li.find_all("div", class_="cn-comp-card")
            company = ""
            apply_before = ""
            event_date = ""
            salary = ""
            status = ""

            if cards:
                company_el = cards[0].find("div", class_="cn-subtitle")
                if company_el:
                    company = company_el.get_text(strip=True)

            if len(cards) > 1:
                edate = cards[1].find("div", class_="cn-edate")
                if edate:
                    apply_before = edate.get_text(strip=True)

            if len(cards) > 2:
                edate = cards[2].find("div", class_="cn-edate")
                if edate:
                    event_date = edate.get_text(strip=True)

            if len(cards) > 3:
                sal = cards[3].find("div", class_="cn-salary")
                if sal:
                    salary = sal.get_text(strip=True)
                btn = cards[3].find("p")
                if btn:
                    status = btn.get_text(strip=True)

            lines.append(
                f"| {company} | {apply_before or '-'} "
                f"| {event_date or '-'} | {salary or '-'} | {status or '-'} |"
            )

    return "\n".join(lines)


def _fetch_cie(client: httpx.Client, course_id: str, sec_id: str, sem_id: str) -> dict:
    url = (
        f"{PARENTS_BASE}index.php"
        f"?option=com_studentdashboard"
        f"&controller=studentdashboard"
        f"&task=ciedetails"
        f"&courseId={course_id}&secId={sec_id}&semId={sem_id}"
    )
    resp = client.get(url, headers=HEADERS, follow_redirects=True)
    soup = BeautifulSoup(resp.text, "html.parser")

    cie_mark = ""
    att = ""
    for span in soup.find_all("span", class_=re.compile(r"cn-color-green")):
        txt = span.get_text(strip=True)
        m = re.search(r'(\d+)', txt)
        if m:
            cie_mark = m.group(1)
            break
    for span in soup.find_all("span", class_=re.compile(r"cn-color-red")):
        txt = span.get_text(strip=True)
        m = re.search(r'(\d+)%', txt)
        if m:
            att = m.group(1)
            break

    tests = {"T 1": "", "T 2": "", "A/Q 1": ""}
    table = soup.find("table", class_="cn-cie-table")
    if table:
        rows = table.find_all("tr")
        header_row = rows[0] if rows else None
        data_row = rows[1] if len(rows) > 1 else None
        if header_row and data_row:
            headers = header_row.find_all("th")
            data_cells = data_row.find_all("td")
            for label in tests:
                for i, th in enumerate(headers):
                    if th.get_text(strip=True) == label and i < len(data_cells):
                        val = data_cells[i].get_text(strip=True)
                        m = re.search(r'(\d+)/(\d+)', val)
                        if m:
                            tests[label] = m.group(1)

    return {"cie": cie_mark, "att": att, "tests": tests}


def _fetch_from_portal(usn: str, dob: str) -> str:
    dob_fmt = _format_date(dob)
    if not dob_fmt:
        return "Invalid date format. Please use DD/MM/YYYY."

    with httpx.Client(timeout=30.0, verify=False) as client:
        login_resp = client.post(
            PARENTS_LOGIN,
            data={
                "username": usn,
                "passwd": dob_fmt,
                "option": "com_user",
                "task": "login",
            },
            headers=HEADERS,
            follow_redirects=False,
        )
        if login_resp.status_code not in (301, 302, 303):
            return (
                "Could not log into the portal. "
                "Please verify your USN and Date of Birth."
            )

        dash_url = login_resp.headers.get("location", "")
        if not dash_url:
            return "Login failed."

        dash_resp = client.get(dash_url, headers=HEADERS, follow_redirects=True)
        if "Login to Your Account" in dash_resp.text or "login-form" in dash_resp.text:
            return (
                "Login failed. Please verify your USN and Date of Birth, "
                "then try again."
            )

        dash_soup = BeautifulSoup(dash_resp.text, "html.parser")
        student = _extract_student_info(dash_soup)

        history_resp = client.get(
            f"{PARENTS_BASE}index.php?option=com_history&task=getResult",
            headers=HEADERS,
            follow_redirects=True,
        )
        history_html = _parse_exam_history(
            BeautifulSoup(history_resp.text, "html.parser")
        )

        sem_id = "135"
        for a_tag in dash_soup.find_all("a", href=re.compile(r"semId=(\d+)")):
            href = a_tag.get("href", "")
            m = re.search(r"semId=(\d+)", href)
            if m:
                sem_id = m.group(1)

        courses = []
        first_cie_id = ""
        first_cie_sec = ""
        for a_tag in dash_soup.find_all("a", href=re.compile(r"ciedetails")):
            href = a_tag.get("href", "")
            m = re.search(r'courseId=(\d+)&secId=(\d+)', href)
            if m:
                cid = m.group(1)
                sid = m.group(2)
                key = f"{cid}_{sid}"
                if key not in {f"{c['id']}_{c['sec_id']}" for c in courses}:
                    courses.append({"id": cid, "sec_id": sid, "code": "", "name": ""})
                    if not first_cie_id:
                        first_cie_id = cid
                        first_cie_sec = sid

        if first_cie_id:
            first_cie = client.get(
                f"{PARENTS_BASE}index.php"
                f"?option=com_studentdashboard"
                f"&controller=studentdashboard"
                f"&task=ciedetails"
                f"&courseId={first_cie_id}&secId={first_cie_sec}&semId={sem_id}",
                headers=HEADERS,
                follow_redirects=True,
            )
            cie_soup = BeautifulSoup(first_cie.text, "html.parser")
            tab_courses = _get_courses_from_cie_page(cie_soup)
            tab_map = {c["id"]: c for c in tab_courses}
            for c in courses:
                tc = tab_map.get(c["id"])
                if tc:
                    c["name"] = tc["name"]
                    c["code"] = tc["code"]

        cie_data = []
        for c in courses:
            data = _fetch_cie(client, c["id"], c["sec_id"], sem_id)
            data["code"] = c["code"]
            data["name"] = c["name"]
            cie_data.append(data)

        parts = []
        header = f"### {student['name']} ({student['usn'] or usn})"
        if student["program"]:
            header += f"\n*{student['program']}*"
        parts.append(header)

        if history_html.strip():
            parts.append("---\n**Published Semester Results**" + history_html)

        if cie_data:
            parts.append("\n---\n**Current Semester CIE (Internal Assessment)**")
            cie_lines = [
                "| Code | Subject | CIE/50 | Att % | T1 | T2 | A/Q1 |",
                "|------|---------|--------|-------|----|----|------|",
            ]
            for d in cie_data:
                t1 = d["tests"].get("T 1", "-") or "-"
                t2 = d["tests"].get("T 2", "-") or "-"
                aq = d["tests"].get("A/Q 1", "-") or "-"
                cie_lines.append(
                    f"| {d['code']} | {d['name'] or '?'} "
                    f"| {d['cie'] or '-'}/50 | {d['att'] or '-'}% "
                    f"| {t1} | {t2} | {aq} |"
                )
            parts.append("\n".join(cie_lines))

        placement_html = _parse_placement(client)
        if placement_html.strip():
            parts.append("\n---\n**Placement Events**" + placement_html)

        parts.append(
            "\n---\n"
            "*Data sourced from MSRIT Parents Portal. "
            "For official results, visit [exam.msrit.edu](http://exam.msrit.edu/).*"
        )

        return "\n".join(parts)


class ResultService:

    @classmethod
    def in_flow(cls, session_id: str) -> bool:
        return session_id in _sessions

    @classmethod
    def _get(cls, session_id: str) -> Optional[ParentSession]:
        return _sessions.get(session_id)

    @classmethod
    def _start(cls, session_id: str) -> ParentSession:
        s = ParentSession()
        _sessions[session_id] = s
        return s

    @classmethod
    def _clear(cls, session_id: str):
        _sessions.pop(session_id, None)

    @classmethod
    def handle(cls, session_id: str, question: str) -> Optional[ResultResponse]:
        q = question.strip()

        if not cls.in_flow(session_id):
            if is_result_intent(q):
                cls._start(session_id)
                return ResultResponse(
                    answer=(
                        "I can fetch your marks and results from the "
                        "MSRIT portal.\n\n"
                        "Please enter your **USN** (e.g. 1MS22CS001)."
                    ),
                    input_type="usn",
                )
            return None

        session = cls._get(session_id)

        cancel_words = ["cancel", "exit", "stop", "never mind", "forget it", "leave"]
        if q.lower() in cancel_words or q.lower().startswith("cancel"):
            cls._clear(session_id)
            return ResultResponse(
                answer="Alright, cancelled. Ask me anything else about MSRIT!"
            )

        if session.status == "waiting_usn":
            usn = re.sub(r'\s+', "", q).upper()
            if len(usn) < 6 or len(usn) > 15 or not re.search(r'\d', usn):
                return ResultResponse(
                    answer="That doesn't look valid. Enter your **USN** "
                           "(e.g. 1MS22CS001).",
                    input_type="usn",
                )
            session.usn = usn
            session.status = "waiting_dob"
            return ResultResponse(
                answer=f"USN set to **{usn}**.\n\n"
                       "Now enter your **Date of Birth** in DD/MM/YYYY format.",
                input_type="dob",
            )

        if session.status == "waiting_dob":
            dob = q.strip()
            m = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})', dob)
            if not m:
                return ResultResponse(
                    answer="Please use **DD/MM/YYYY** format "
                           "(e.g. 15/08/2002).",
                    input_type="dob",
                )
            session.dob = f"{m.group(1):0>2}/{m.group(2):0>2}/{m.group(3)}"
            cls._clear(session_id)

            try:
                answer = _fetch_from_portal(session.usn, session.dob)
            except Exception as e:
                answer = (
                    f"Could not fetch data from the portal.\n\n"
                    f"Try visiting [exam.msrit.edu](http://exam.msrit.edu/) "
                    f"directly and enter your USN **{session.usn}** "
                    f"and DOB manually."
                )

            return ResultResponse(answer=answer)

        return None
