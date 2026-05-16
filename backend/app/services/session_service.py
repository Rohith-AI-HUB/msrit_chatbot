from collections import defaultdict
from typing import Dict
from typing import List

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("session_service")


class SessionService:

    # =========================
    # Temporary In-Memory Store
    # =========================
    #
    # Structure:
    #
    # {
    #     session_id: [
    #         {
    #             "question": "...",
    #             "answer": "..."
    #         }
    #     ]
    # }
    #
    # =========================
    _sessions: Dict[
        str,
        List[dict]
    ] = defaultdict(list)

    @classmethod
    def add_message(
        cls,
        session_id: str,
        question: str,
        answer: str
    ) -> None:

        cls._sessions[session_id].append({
            "question": question,
            "answer": answer
        })

        logger.info(
            f"Message added to session: "
            f"{session_id}"
        )

        # Limit memory growth
        if (
            len(cls._sessions[session_id])
            > settings.MAX_CHAT_HISTORY
        ):

            cls._sessions[session_id] = (
                cls._sessions[session_id][
                    -settings.MAX_CHAT_HISTORY:
                ]
            )

    @classmethod
    def get_history(
        cls,
        session_id: str
    ) -> List[dict]:

        return cls._sessions.get(
            session_id,
            []
        )

    @classmethod
    def get_recent_history(
        cls,
        session_id: str
    ) -> str:

        history = cls.get_history(
            session_id
        )

        if not history:

            return ""

        formatted_history = []

        for item in history[-3:]:

            formatted_history.append(
                (
                    f"User: "
                    f"{item['question']}\n"
                    f"Assistant: "
                    f"{item['answer']}"
                )
            )

        return "\n\n".join(
            formatted_history
        )

    @classmethod
    def clear_session(
        cls,
        session_id: str
    ) -> None:

        if session_id in cls._sessions:

            del cls._sessions[session_id]

            logger.info(
                f"Session cleared: "
                f"{session_id}"
            )

    @classmethod
    def session_exists(
        cls,
        session_id: str
    ) -> bool:

        return (
            session_id
            in cls._sessions
        )