import sys
import time
from pathlib import Path

from fastapi import FastAPI

# Add parent directory so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from groq_client import GroqClient
from cache import LLMCache
from validators import validate_rewrite, clean_rewrite
from prompts import build_rewrite_prompt
from shared.logging import setup_logger
from shared.schemas.chat import (
    GenerateRequest,
    GenerateResponse,
    RewriteRequest,
    RewriteResponse,
)


logger = setup_logger("llm-service")

app = FastAPI(title="LLM Service", version="1.0.0")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "llm",
        "model": settings.LLM_MODEL,
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    start = time.time()

    # Check cache first
    cached = LLMCache.get(request.prompt)
    if cached:
        latency = int((time.time() - start) * 1000)
        return GenerateResponse(
            content=cached["content"],
            model=cached["model"],
            tokens_used=0,
            latency_ms=latency,
        )

    # Call Groq
    result = GroqClient.generate(
        prompt=request.prompt,
        temperature=request.temperature,
        model=request.model,
    )

    latency = int((time.time() - start) * 1000)
    logger.info(f"Generated response in {latency}ms | tokens={result['tokens_used']}")

    # Cache the response
    LLMCache.set(request.prompt, result)

    return GenerateResponse(
        content=result["content"],
        model=result["model"],
        tokens_used=result["tokens_used"],
        latency_ms=latency,
    )


@app.post("/rewrite", response_model=RewriteResponse)
def rewrite(request: RewriteRequest):
    question = request.question.strip()

    # Skip rewrite for single-word queries
    if len(question.split()) <= 1:
        logger.info("Skipping rewrite for single-word query")
        return RewriteResponse(rewritten_query=question, original=question)

    prompt = build_rewrite_prompt(question)

    result = GroqClient.generate(prompt=prompt, temperature=0)
    rewritten = clean_rewrite(result["content"])

    if not validate_rewrite(rewritten):
        logger.warning("Unsafe rewrite detected, using original")
        return RewriteResponse(rewritten_query=question, original=question)

    logger.info(f"Rewritten: '{question}' -> '{rewritten}'")
    return RewriteResponse(rewritten_query=rewritten, original=question)
