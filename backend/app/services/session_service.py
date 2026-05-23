import json
from typing import List

import redis

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("session_service")

SESSION_TTL = 1800  # 30 minutes


class SessionService:

    _redis = None

    @classmethod
    def get_redis(cls):
        if cls._redis is None:
            logger.info(f"Connecting to Redis: {settings.REDIS_URL}")
            cls._redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return cls._redis

    @classmethod
    def _key(cls, session_id: str) -> str:
        return f"session:{session_id}"

    @classmethod
    def add_message(
        cls,
        session_id: str,
        question: str,
        answer: str
    ) -> None:
        try:
            r = cls.get_redis()
            key = cls._key(session_id)
            message = json.dumps({"question": question, "answer": answer})
            r.rpush(key, message)
            r.ltrim(key, -settings.MAX_CHAT_HISTORY, -1)
            r.expire(key, SESSION_TTL)
            logger.info(f"Message added to session: {session_id}")
        except Exception as e:
            logger.warning(f"Redis unavailable, session not saved: {e}")

    @classmethod
    def get_history(
        cls,
        session_id: str
    ) -> List[dict]:
        try:
            r = cls.get_redis()
            key = cls._key(session_id)
            messages = r.lrange(key, 0, -1)
            return [json.loads(m) for m in messages]
        except Exception as e:
            logger.warning(f"Redis unavailable, returning empty history: {e}")
            return []

    @classmethod
    def get_recent_history(
        cls,
        session_id: str
    ) -> str:

        history = cls.get_history(session_id)

        if not history:
            return ""

        formatted_history = []

        for item in history[-3:]:
            formatted_history.append(
                f"User: {item['question']}\n"
                f"Assistant: {item['answer']}"
            )

        return "\n\n".join(formatted_history)

    @classmethod
    def clear_session(
        cls,
        session_id: str
    ) -> None:
        try:
            r = cls.get_redis()
            r.delete(cls._key(session_id))
            logger.info(f"Session cleared: {session_id}")
        except Exception as e:
            logger.warning(f"Redis unavailable, clear skipped: {e}")

    @classmethod
    def session_exists(
        cls,
        session_id: str
    ) -> bool:
        try:
            r = cls.get_redis()
            return r.exists(cls._key(session_id)) > 0
        except Exception:
            return False

    @classmethod
    def health_check(cls) -> bool:
        try:
            r = cls.get_redis()
            return r.ping()
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
