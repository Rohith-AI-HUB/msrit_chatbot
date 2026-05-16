# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN useradd -m appuser
WORKDIR /app

COPY llm-service/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY shared/ shared/
COPY llm-service/*.py ./

USER appuser
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
