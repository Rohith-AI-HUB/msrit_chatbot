import re
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from clients import RetrievalClient, LLMClient, SessionClient, ParentsPortalClient
from prompts import build_chat_prompt, build_no_context_response
from shared.logging import setup_logger
from shared.schemas.chat import (
    ChatRequest,
    ChatResponse,
    RetrievedChunk,
    ErrorResponse,
)


logger = setup_logger("chat-orchestrator")

app = FastAPI(
    title="MSRIT Chatbot — Chat Orchestrator",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# Parents Portal flow
# ══════════════════════════════════════════════════════════════════════════════

PORTAL_INTENT_KEYWORDS = [
    "my marks", "my attendance", "my result", "my grades",
    "check attendance", "check marks", "check my attendance", "check my marks",
    "my cgpa", "my sgpa", "my internal", "my cie", "my internal marks",
    "attendance percentage", "view marks", "view attendance",
    "show marks", "show attendance", "my academic",
    "my semester marks", "my exam marks", "what are my marks",
    "what is my attendance", "how much attendance",
    # SEE / exam-history keywords
    "my see", "see marks", "see result", "see results",
    "last sem marks", "last semester marks", "previous semester",
    "semester result", "semester results", "exam history",
    "my gpa", "my grade", "my grades", "end exam", "semester end",
    "external marks", "external exam", "my backlogs",
]

PORTAL_EXCLUSION_KEYWORDS = [
    "minimum attendance", "attendance rules", "attendance policy",
    "attendance criteria", "required attendance", "attendance cut",
    "how to check", "where to check", "portal link",
]

CANCEL_WORDS = {"cancel", "exit", "quit", "stop", "nevermind", "never mind", "back"}


_CIE_KEYWORDS = [
    "cie", "internal marks", "internal", "my marks", "check marks", "check my marks",
    "view marks", "show marks", "my semester marks", "my exam marks",
    "what are my marks", "my cie marks",
]
_ATTENDANCE_KEYWORDS = [
    "attendance", "present", "absent", "classes attended",
    "how much attendance", "what is my attendance", "attendance percentage",
]
_SEE_KEYWORDS = [
    "see marks", "see result", "see results", "my see", "last sem marks",
    "last semester marks", "previous semester", "semester result", "semester results",
    "exam history", "my cgpa", "my sgpa", "my gpa", "my grades", "my grade",
    "end exam", "semester end", "external marks", "external exam", "my backlogs",
]


def _classify_data_intent(question: str) -> str:
    """
    Return one of: 'cie', 'attendance', 'see', 'all'.
    Used to filter which sections of portal data are shown.
    """
    q = question.lower()
    wants_cie        = any(k in q for k in _CIE_KEYWORDS)
    wants_attendance = any(k in q for k in _ATTENDANCE_KEYWORDS)
    wants_see        = any(k in q for k in _SEE_KEYWORDS)

    # Exactly one category matched → be specific
    if wants_cie and not wants_attendance and not wants_see:
        return "cie"
    if wants_attendance and not wants_cie and not wants_see:
        return "attendance"
    if wants_see and not wants_cie and not wants_attendance:
        return "see"
    # Multiple or none → show everything
    return "all"


def _is_portal_intent(question: str) -> bool:
    q = question.lower()
    if any(ex in q for ex in PORTAL_EXCLUSION_KEYWORDS):
        return False
    return any(k in q for k in PORTAL_INTENT_KEYWORDS)


def _make_portal_response(answer: str) -> ChatResponse:
    return ChatResponse(
        answer=answer,
        sources=[],
        rewritten_query=None,
        retrieved_documents_count=0,
        debug_chunks=None,
    )


def _format_portal_result(result: dict, usn: str, requested: str = "all") -> str:
    """
    Convert scraper result dict into a readable markdown string.

    requested — one of 'cie', 'attendance', 'see', 'all'
                controls which sections are included in the output.
    """
    show_cie        = requested in ("cie", "all")
    show_attendance = requested in ("attendance", "all")
    show_see        = requested in ("see", "all")

    section_title = {
        "cie":        "CIE Marks",
        "attendance": "Attendance",
        "see":        "SEE Results",
        "all":        "Academic Data",
    }.get(requested, "Academic Data")

    parts = [f"## {section_title} — **{usn}**\n"]

    # Student info (always shown — brief context)
    info = result.get("student_info") or {}
    if info:
        parts.append("### Student Information")
        for key, val in info.items():
            parts.append(f"- **{key}:** {val}")
        parts.append("")

    # Attendance tables
    attendance_tables = result.get("attendance") or []
    if show_attendance and attendance_tables:
        parts.append("### Attendance")
        for tbl in attendance_tables:
            headers = tbl.get("headers", [])
            rows = tbl.get("rows", [])
            if headers:
                parts.append("| " + " | ".join(headers) + " |")
                parts.append("|" + "|".join(["---"] * len(headers)) + "|")
            for row in rows:
                # Pad row to match header length
                padded = row + [""] * max(0, len(headers) - len(row))
                parts.append("| " + " | ".join(str(c) for c in padded[:len(headers)]) + " |")
        parts.append("")

    # CIE Marks — list of dicts {course_code, course_name, T 1, T 2, ..., FINAL CIE, ATTENDANCE}
    marks_list = result.get("marks") or []
    if show_cie and marks_list:
        parts.append("### CIE Marks")
        # Collect all unique column headers across all entries (preserve order)
        skip_keys = {"course_code", "course_name", "note"}
        col_keys: list[str] = []
        for entry in marks_list:
            for k in entry:
                if k not in skip_keys and k not in col_keys:
                    col_keys.append(k)

        # Header row
        parts.append("| Course | Name | " + " | ".join(col_keys) + " |")
        parts.append("|" + "|".join(["---"] * (2 + len(col_keys))) + "|")
        for entry in marks_list:
            code = entry.get("course_code", "-")
            name = entry.get("course_name", "-").split("(")[0].strip() or "-"
            cols = " | ".join(str(entry.get(k, "-")) for k in col_keys)
            parts.append(f"| {code} | {name} | {cols} |")
        parts.append("")

    # SEE Results (Exam History)
    see_results = result.get("see_results")
    if show_see and see_results:
        cgpa           = see_results.get("cgpa", "-")
        credits_earned = see_results.get("credits_earned", "-")
        credits_to_earn = see_results.get("credits_to_earn", "-")

        parts.append("### SEE Results (Exam History)")
        parts.append(f"- **CGPA:** {cgpa}")
        parts.append(f"- **Credits Earned:** {credits_earned} | **Credits to be Earned:** {credits_to_earn}")
        parts.append("")

        for sem in see_results.get("semesters", []):
            name  = sem.get("name", "Semester")
            sgpa  = sem.get("sgpa", "-")
            parts.append(f"**{name}** — SGPA: {sgpa}")

            courses = sem.get("courses", [])
            if courses:
                headers = list(courses[0].keys())
                parts.append("| " + " | ".join(headers) + " |")
                parts.append("|" + "|".join(["---"] * len(headers)) + "|")
                for course in courses:
                    row = " | ".join(str(course.get(h, "-")) for h in headers)
                    parts.append(f"| {row} |")
            parts.append("")

    # Raw text fallback
    raw = result.get("raw_text", "")
    if raw and not attendance_tables and not marks_list and not see_results:
        parts.append("### Portal Data")
        parts.append("```")
        parts.append(raw[:3000] + ("..." if len(raw) > 3000 else ""))
        parts.append("```")

    if len(parts) == 1:  # only the header line
        parts.append("No academic data could be extracted from the portal. "
                      "Please visit the portal directly.")

    return "\n".join(parts)


def handle_portal_flow(session_id: str, question: str) -> Optional[ChatResponse]:
    """
    Returns a ChatResponse if the question is part of the portal flow,
    or None to fall through to the normal RAG pipeline.
    """
    flow_state = SessionClient.get_flow_state(session_id)

    # ── Not in flow: check intent ────────────────────────────────────────────
    if not flow_state:
        if not _is_portal_intent(question):
            return None
        # Classify what the student wants so we can filter the response later
        data_intent = _classify_data_intent(question)
        SessionClient.set_flow_state(session_id, {
            "status": "waiting_usn",
            "usn": "",
            "dob": "",
            "intent": data_intent,
        })
        return _make_portal_response(
            "I can look up your **marks and attendance** from the MSRIT Parents Portal.\n\n"
            "Please enter your **USN** (e.g. `1MS22CS001`):"
        )

    status = flow_state.get("status", "waiting_usn")
    q = question.strip()

    # ── Cancel ───────────────────────────────────────────────────────────────
    if q.lower() in CANCEL_WORDS:
        SessionClient.clear_flow_state(session_id)
        return _make_portal_response("Cancelled. How else can I help you?")

    # ── Collecting USN ───────────────────────────────────────────────────────
    if status == "waiting_usn":
        usn = re.sub(r'\s+', '', q).upper()
        if not re.match(r'^[A-Z0-9]{6,15}$', usn) or not re.search(r'\d', usn):
            return _make_portal_response(
                "That doesn't look like a valid USN. Please enter it again (e.g. `1MS22CS001`):"
            )
        flow_state["usn"] = usn
        flow_state["status"] = "waiting_dob"
        SessionClient.set_flow_state(session_id, flow_state)
        return _make_portal_response(
            f"USN: **{usn}**\n\n"
            "Now please enter your **Date of Birth** in `DD/MM/YYYY` format\n"
            "(e.g. `15/08/2002`):"
        )

    # ── Collecting DOB ───────────────────────────────────────────────────────
    if status == "waiting_dob":
        dob = q.strip()
        if not re.match(r'^\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4}$', dob):
            return _make_portal_response(
                "Please enter your date of birth in **DD/MM/YYYY** format "
                "(e.g. `15/08/2002`):"
            )
        usn = flow_state["usn"]

        # Mark as fetching so concurrent messages are handled gracefully
        flow_state["dob"] = dob
        flow_state["status"] = "fetching"
        SessionClient.set_flow_state(session_id, flow_state)

        try:
            logger.info(f"Calling parents-service for USN={usn}")
            result = ParentsPortalClient.fetch(usn, dob)
            SessionClient.clear_flow_state(session_id)

            if result.get("success"):
                data_intent = flow_state.get("intent", "all")
                answer = _format_portal_result(result, usn, requested=data_intent)
                sources = ["https://parents.msrit.edu/newparents/index.php"]
            else:
                error = result.get("error", "Unknown error from portal.")
                answer = (
                    f"Could not fetch data from the MSRIT Parents Portal.\n\n"
                    f"**Reason:** {error}\n\n"
                    f"Please verify your USN and Date of Birth, then type "
                    f"**check attendance** to try again, or visit the portal directly."
                )
                sources = []

        except Exception as exc:
            SessionClient.clear_flow_state(session_id)
            logger.exception(f"Parents portal error: {exc}")
            answer = (
                "Sorry, the MSRIT Parents Portal is currently unreachable. "
                "Please try again later, or visit the portal directly at "
                "https://parents.msrit.edu/newparents/index.php"
            )
            sources = []

        return ChatResponse(
            answer=answer,
            sources=sources,
            rewritten_query=None,
            retrieved_documents_count=0,
            debug_chunks=None,
        )

    # ── Already fetching (parallel request edge case) ────────────────────────
    if status == "fetching":
        return _make_portal_response(
            "Fetching your data from the portal, please wait a moment..."
        )

    return None


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "chat-orchestrator",
        "downstream": {
            "retrieval": settings.RETRIEVAL_SERVICE_URL,
            "llm": settings.LLM_SERVICE_URL,
            "session": settings.SESSION_SERVICE_URL,
            "parents": settings.PARENTS_SERVICE_URL,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Chat endpoint
# ══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/api/chat",
    response_model=ChatResponse,
    responses={500: {"model": ErrorResponse}},
)
def chat(request: ChatRequest):
    request_start = time.time()

    try:
        logger.info(f"Question: {request.question} | session={request.session_id}")

        # ==========================
        # Step 0: Portal flow check
        # (runs before RAG — intercepts marks/attendance questions)
        # ==========================
        portal_response = handle_portal_flow(request.session_id, request.question)
        if portal_response is not None:
            return portal_response

        # ==========================
        # Step 1: Rewrite Query
        # ==========================
        rewrite_start = time.time()
        rewrite_result = LLMClient.rewrite(request.question)
        rewritten_query = rewrite_result["rewritten_query"]
        logger.info(f"Rewrite ({int((time.time()-rewrite_start)*1000)}ms): {rewritten_query}")

        # ==========================
        # Step 2: Retrieve Documents
        # ==========================
        retrieval_start = time.time()
        search_result = RetrievalClient.search(
            question=request.question,
            rewritten_query=rewritten_query,
        )
        documents = search_result["documents"]
        logger.info(f"Retrieval ({int((time.time()-retrieval_start)*1000)}ms): {len(documents)} docs")

        # ==========================
        # Step 3: No Context
        # ==========================
        if not documents:
            logger.warning("No relevant documents found")
            return ChatResponse(
                answer=build_no_context_response(),
                sources=[],
                rewritten_query=rewritten_query,
                retrieved_documents_count=0,
                debug_chunks=[],
            )

        # ==========================
        # Step 4: Build Context
        # ==========================
        context = "\n\n".join([doc["content"] for doc in documents])
        sources = list(set([doc["source"] for doc in documents]))

        # ==========================
        # Step 5: Get Session History
        # ==========================
        history_result = SessionClient.get_history(request.session_id)
        recent_history = history_result["formatted"]

        # ==========================
        # Step 6: Generate Answer
        # ==========================
        prompt = build_chat_prompt(
            question=request.question,
            context=context,
            recent_history=recent_history,
        )

        llm_start = time.time()
        llm_result = LLMClient.generate(prompt=prompt, task="chat")
        answer = llm_result["content"]
        logger.info(f"LLM ({int((time.time()-llm_start)*1000)}ms): {len(answer)} chars")

        # ==========================
        # Step 7: Save to Session
        # ==========================
        SessionClient.add_message(request.session_id, request.question, answer)

        # ==========================
        # Step 8: Build Response
        # ==========================
        total_ms = int((time.time() - request_start) * 1000)
        logger.info(f"Total: {total_ms}ms")

        debug_chunks = None
        if request.debug:
            debug_chunks = [
                RetrievedChunk(
                    source=doc["source"],
                    preview=doc["content"][:300].replace("\n", " ").strip(),
                )
                for doc in documents
            ]

        return ChatResponse(
            answer=answer,
            sources=sources,
            rewritten_query=rewritten_query,
            retrieved_documents_count=len(documents),
            debug_chunks=debug_chunks,
        )

    except Exception as e:
        total_ms = int((time.time() - request_start) * 1000)
        logger.exception(f"Chat failed after {total_ms}ms: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
