import httpx

from config import settings
from shared.logging import setup_logger


logger = setup_logger("clients")

TIMEOUT = httpx.Timeout(timeout=settings.REQUEST_TIMEOUT)
PORTAL_TIMEOUT = httpx.Timeout(timeout=settings.PARENTS_PORTAL_TIMEOUT)


class RetrievalClient:

    @staticmethod
    def search(question: str, rewritten_query: str, top_k: int = 6) -> dict:
        url = f"{settings.RETRIEVAL_SERVICE_URL}/search"
        payload = {
            "question": question,
            "rewritten_query": rewritten_query,
            "top_k": top_k,
            "strategy": "auto",
        }

        response = httpx.post(url, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()


class LLMClient:

    @staticmethod
    def rewrite(question: str) -> dict:
        url = f"{settings.LLM_SERVICE_URL}/rewrite"
        payload = {"question": question}

        response = httpx.post(url, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def generate(prompt: str, temperature: float = 0.0, task: str = "chat") -> dict:
        url = f"{settings.LLM_SERVICE_URL}/generate"
        payload = {
            "prompt": prompt,
            "temperature": temperature,
            "task": task,
        }

        response = httpx.post(url, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()


class SessionClient:

    @staticmethod
    def get_history(session_id: str) -> dict:
        url = f"{settings.SESSION_SERVICE_URL}/sessions/{session_id}/history"

        response = httpx.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def add_message(session_id: str, question: str, answer: str) -> None:
        url = f"{settings.SESSION_SERVICE_URL}/sessions/{session_id}/messages"
        payload = {"question": question, "answer": answer}

        response = httpx.post(url, json=payload, timeout=TIMEOUT)
        response.raise_for_status()

    @staticmethod
    def get_flow_state(session_id: str):
        url = f"{settings.SESSION_SERVICE_URL}/sessions/{session_id}/flow"
        response = httpx.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json().get("state")  # None or dict

    @staticmethod
    def set_flow_state(session_id: str, state: dict) -> None:
        url = f"{settings.SESSION_SERVICE_URL}/sessions/{session_id}/flow"
        response = httpx.put(url, json={"state": state}, timeout=TIMEOUT)
        response.raise_for_status()

    @staticmethod
    def clear_flow_state(session_id: str) -> None:
        url = f"{settings.SESSION_SERVICE_URL}/sessions/{session_id}/flow"
        response = httpx.delete(url, timeout=TIMEOUT)
        response.raise_for_status()


class ParentsPortalClient:

    @staticmethod
    def fetch(usn: str, dob: str) -> dict:
        url = f"{settings.PARENTS_SERVICE_URL}/fetch"
        payload = {"usn": usn, "dob": dob}
        response = httpx.post(url, json=payload, timeout=PORTAL_TIMEOUT)
        response.raise_for_status()
        return response.json()
