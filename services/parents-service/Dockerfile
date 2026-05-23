# syntax=docker/dockerfile:1
FROM python:3.11-slim

# System deps for Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY parents-service/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Install Chromium browser + its system deps (playwright handles this)
RUN playwright install chromium --with-deps

COPY shared/ shared/
COPY parents-service/*.py ./

EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
