from groq import Groq, APIConnectionError, RateLimitError, APIStatusError

from config import settings
from shared.logging import setup_logger


logger = setup_logger("groq-client")


class GroqClient:

    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            logger.info("Initializing Groq client")
            cls._client = Groq(api_key=settings.GROQ_API_KEY)
        return cls._client

    @classmethod
    def generate(cls, prompt: str, temperature: float = None, model: str = None) -> dict:
        """
        Returns: { content: str, model: str, tokens_used: int }
        Raises on unrecoverable errors.
        """
        client = cls.get_client()
        use_model = model or settings.LLM_MODEL
        use_temp = temperature if temperature is not None else settings.LLM_TEMPERATURE

        try:
            response = client.chat.completions.create(
                model=use_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=use_temp,
            )

            content = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0

            if not content:
                logger.warning("Groq returned empty response")
                return {
                    "content": "I could not generate a proper response.",
                    "model": use_model,
                    "tokens_used": tokens,
                }

            return {
                "content": content.strip(),
                "model": use_model,
                "tokens_used": tokens,
            }

        except RateLimitError as e:
            logger.error(f"Groq rate limit: {e}")
            return {
                "content": "The AI service is currently busy. Please try again shortly.",
                "model": use_model,
                "tokens_used": 0,
            }

        except APIConnectionError as e:
            logger.error(f"Groq connection error: {e}")
            return {
                "content": "Could not connect to the AI service.",
                "model": use_model,
                "tokens_used": 0,
            }

        except APIStatusError as e:
            logger.error(f"Groq API error: {e.status_code}")
            return {
                "content": "The AI service encountered an internal error.",
                "model": use_model,
                "tokens_used": 0,
            }
