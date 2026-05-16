import hashlib
import json

import redis

from config import settings
from shared.logging import setup_logger


logger = setup_logger("llm-cache")


class LLMCache:

    _redis = None

    @classmethod
    def get_redis(cls):
        if cls._redis is None:
            cls._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._redis

    @classmethod
    def _key(cls, prompt: str) -> str:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return f"llm_cache:{prompt_hash}"

    @classmethod
    def get(cls, prompt: str) -> dict | None:
        try:
            r = cls.get_redis()
            data = r.get(cls._key(prompt))
            if data:
                logger.info("Cache HIT")
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
            return None

    @classmethod
    def set(cls, prompt: str, response: dict) -> None:
        try:
            r = cls.get_redis()
            r.setex(cls._key(prompt), settings.CACHE_TTL, json.dumps(response))
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
