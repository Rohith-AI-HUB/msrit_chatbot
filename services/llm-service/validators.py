INVALID_PATTERNS = [
    "select ", "drop table", "delete from",
    "{", "}", "<script", "assistant:", "answer:",
]


def validate_rewrite(rewritten_query: str) -> bool:
    lowered = rewritten_query.lower()
    return not any(p in lowered for p in INVALID_PATTERNS)


def clean_rewrite(raw: str) -> str:
    """Clean LLM rewrite output to a single clean query string."""
    cleaned = (
        raw.strip()
        .replace('"', '')
        .replace("'", "")
        .split("\n")[0]
    )
    return cleaned
