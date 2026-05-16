from app.core.logging import setup_logger
from app.services.llm_service import LLMService
from app.utils.prompts import build_rewrite_prompt


logger = setup_logger("query_rewriter_service")


class QueryRewriterService:

    INVALID_PATTERNS = [
        "select ", "drop table", "delete from",
        "{", "}", "<script", "assistant:", "answer:",
    ]

    @classmethod
    def validate_response(cls, rewritten_query: str) -> bool:
        lowered = rewritten_query.lower()
        return not any(p in lowered for p in cls.INVALID_PATTERNS)

    @classmethod
    def rewrite_query(cls, question: str) -> str:
        question = question.strip()

        if not question:
            logger.warning("Empty question received for query rewriting")
            return ""

        # Only skip rewrite for single-word queries
        if len(question.split()) <= 1:
            logger.info("Skipping rewrite for single-word query")
            return question

        prompt = build_rewrite_prompt(question)

        logger.info(f"Rewriting query: {question}")

        rewritten_query = LLMService.generate_response(
            prompt=prompt,
            temperature=0
        )

        if not rewritten_query:
            logger.warning("Empty rewritten query returned")
            return question

        rewritten_query = (
            rewritten_query.strip()
            .replace('"', '')
            .replace("'", "")
            .split("\n")[0]  # take only first line — prevents multi-line bleed
        )

        if not cls.validate_response(rewritten_query):
            logger.warning("Unsafe rewritten query detected, using original")
            return question

        logger.info(f"Rewritten query: {rewritten_query}")
        return rewritten_query
