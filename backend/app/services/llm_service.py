from groq import Groq
from groq import APIConnectionError
from groq import RateLimitError
from groq import APIStatusError

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("llm_service")


class LLMService:

    _client = None

    @classmethod
    def get_client(cls):

        if cls._client is None:

            logger.info("Initializing Groq client")

            cls._client = Groq(
                api_key=settings.GROQ_API_KEY
            )

        return cls._client

    @classmethod
    def generate_response(
        cls,
        prompt: str,
        temperature: float = None,
        model: str = None
    ) -> str:

        client = cls.get_client()

        try:

            response = client.chat.completions.create(
                model=model or settings.LLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=(
                    temperature
                    if temperature is not None
                    else settings.LLM_TEMPERATURE
                )
            )

            content = (
                response
                .choices[0]
                .message
                .content
            )

            if not content:

                logger.warning(
                    "LLM returned empty response"
                )

                return (
                    "I could not generate "
                    "a proper response."
                )

            return content.strip()

        except RateLimitError as e:

            logger.error(
                f"Groq rate limit exceeded: {e}"
            )

            return (
                "The AI service is currently busy. "
                "Please try again shortly."
            )

        except APIConnectionError as e:

            logger.error(
                f"Groq connection error: {e}"
            )

            return (
                "Could not connect to the AI service."
            )

        except APIStatusError as e:

            logger.error(
                f"Groq API status error: "
                f"{e.status_code} | {e.response}"
            )

            return (
                "The AI service encountered "
                "an internal error."
            )

        except Exception as e:

            logger.exception(
                f"Unexpected LLM error: {e}"
            )

            return (
                "An unexpected AI error occurred."
            )