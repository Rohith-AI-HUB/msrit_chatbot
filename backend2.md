# MSRIT Chatbot — Backend v2 Architecture Plan

> **Stack: Docker + Minikube (local). Cost: $0. No cloud, no DNS, no TLS, no registry.**

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Target Architecture Overview](#2-target-architecture-overview)
3. [Microservices Breakdown](#3-microservices-breakdown)
4. [Database Layer](#4-database-layer)
5. [Docker Strategy](#5-docker-strategy)
6. [Kubernetes Deployment (Minikube)](#6-kubernetes-deployment-minikube)
7. [CI/CD Pipeline](#7-cicd-pipeline)
8. [Observability Stack](#8-observability-stack)
9. [Security](#9-security)
10. [Migration Plan](#10-migration-plan)
11. [Directory Structure](#11-directory-structure)

---

## 1. Current State Assessment

### What exists today (monolith)

```
backend/
  app/
    main.py                         # FastAPI app, lifespan, CORS, health check
    api/routes/chat.py              # Single POST /api/chat endpoint (sync)
    core/config.py                  # Pydantic Settings (env-based)
    core/logging.py                 # Logger setup
    db/vector_store.py              # ChromaDB singleton (file-based)
    schemas/chat.py                 # ChatRequest (question, session_id, debug)
    schemas/response.py             # ChatResponse, ErrorResponse, RetrievedChunk
    services/
      llm_service.py                # Groq API client (Llama-4-Scout-17B)
      query_rewriter_service.py     # LLM-based query rewriting
      retrieval_service.py          # Intent detection + similarity/MMR search + reranking
      session_service.py            # In-memory dict of session histories
    utils/prompts.py                # Prompt templates
  ingestion/
    crawler.py                      # Web crawler for msrit.edu
    build_vector_db.py              # Parse raw text -> chunk -> embed -> ChromaDB
  data/
    msrit_full.txt                  # Crawled raw text
    chroma_db/                      # Persisted ChromaDB files
  tests/
    test_all.py                     # Test suite
```

### Problems that microservices solve

| Problem | Impact | Microservice Fix |
|---|---|---|
| Single process — LLM call blocks retrieval | High latency under concurrent users | Separate LLM service scales independently |
| In-memory sessions — lost on restart | Data loss | Dedicated session service with Redis/Postgres |
| ChromaDB file lock — single writer | Can't scale horizontally | Retrieval service owns the vector DB exclusively |
| Embedding model loaded per-process (500MB+) | Wasteful memory if multiple replicas | Dedicated retrieval service, model loaded once |
| Ingestion coupled to app config | Can't re-index without restarting app | Separate ingestion worker |
| No rate limiting | Abuse risk | Nginx Ingress handles rate limiting |

---

## 2. Target Architecture Overview

```
┌───────────────────────────────────────────────────────────┐
│  Your Machine (Docker Desktop + Minikube)                 │
│                                                           │
│  ┌─────────────────────────────────────────────────┐      │
│  │  Minikube Cluster                               │      │
│  │                                                 │      │
│  │  ┌──────────────────────────┐                   │      │
│  │  │  Nginx Ingress           │                   │      │
│  │  │  (minikube addon)        │                   │      │
│  │  │  http://localhost        │                   │      │
│  │  └────────────┬─────────────┘                   │      │
│  │               │                                 │      │
│  │      ┌────────▼─────────┐                       │      │
│  │      │ Chat Orchestrator │◄── Only public svc   │      │
│  │      │ (FastAPI :8000)   │                       │      │
│  │      └──┬────┬────┬─────┘                       │      │
│  │         │    │    │                              │      │
│  │    ┌────▼┐ ┌▼───┐ ┌▼──────┐                    │      │
│  │    │Retr.│ │LLM │ │Session│                     │      │
│  │    │:8001│ │:8002│ │:8003  │                     │      │
│  │    └──┬──┘ └────┘ └──┬──┬─┘                     │      │
│  │       │               │  │                       │      │
│  │    ┌──▼──────┐  ┌────▼┐ ┌▼────────┐            │      │
│  │    │ChromaDB │  │Redis│ │PostgreSQL│            │      │
│  │    │(volume) │  │     │ │          │            │      │
│  │    └─────────┘  └─────┘ └──────────┘            │      │
│  │                                                 │      │
│  │    ┌─────────────────────┐                      │      │
│  │    │ Ingestion Worker    │  (K8s CronJob)       │      │
│  │    └─────────────────────┘                      │      │
│  │                                                 │      │
│  │    ┌──────────────────────────────┐             │      │
│  │    │ Prometheus + Grafana         │             │      │
│  │    │ (self-hosted, optional)      │             │      │
│  │    └──────────────────────────────┘             │      │
│  └─────────────────────────────────────────────────┘      │
└───────────────────────────────────────────────────────────┘

Access: http://localhost/api/chat  (via minikube tunnel)
```

### How images get into Minikube (no registry needed)

```bash
# Build locally with Docker
docker build -t msrit/chat-orchestrator:latest -f services/chat-orchestrator/Dockerfile .

# Load directly into Minikube's internal Docker daemon
minikube image load msrit/chat-orchestrator:latest

# Or: point your shell at Minikube's Docker daemon (even simpler)
eval $(minikube docker-env)
docker build -t msrit/chat-orchestrator:latest -f services/chat-orchestrator/Dockerfile .
# Now Minikube sees the image directly — no load step needed
```

**No GHCR, no Docker Hub, no registry.** Images go straight from your machine into Minikube.

### Service Communication

- All inter-service calls use Kubernetes internal DNS
- Short form within the same namespace: `http://retrieval-service:8001/search`
- External access: `minikube tunnel` exposes the Ingress on `http://localhost`

---

## 3. Microservices Breakdown

### 3.1 Chat Orchestrator Service

**Owner of**: Request lifecycle, prompt assembly, response formatting
**Port**: 8000
**Current code mapping**: `api/routes/chat.py`, `utils/prompts.py`

```
Responsibilities:
  - Receive user question + session_id from frontend
  - Call LLM Service to rewrite the query
  - Call Retrieval Service for relevant documents
  - Call Session Service for conversation history
  - Assemble prompt from template + context + history
  - Call LLM Service for final answer
  - Save conversation turn to Session Service
  - Return structured ChatResponse
```

**API Contract**:

```
POST /api/chat
Request:  { question: str, session_id: str, debug: bool }
Response: { answer: str, sources: [str], rewritten_query: str,
            retrieved_documents_count: int, debug_chunks: [...] }

GET /health
Response: { status: "healthy", services: { retrieval: bool, llm: bool, session: bool } }
```

**Key design decisions**:
- Only service exposed externally via Ingress
- Uses `httpx.AsyncClient` with connection pooling for inter-service calls
- Timeout budget: 30s total (3s rewrite + 5s retrieval + 20s LLM + 2s overhead)
- If retrieval fails -> graceful "no context" response
- If LLM fails -> return cached/fallback response

**Dependencies**: Retrieval Service, LLM Service, Session Service

---

### 3.2 Retrieval Service

**Owner of**: Vector database, embeddings, search strategies
**Port**: 8001
**Current code mapping**: `services/retrieval_service.py`, `db/vector_store.py`

```
Responsibilities:
  - Own the ChromaDB instance (sole reader/writer)
  - Expose search endpoints (similarity, MMR)
  - Intent detection (factual, PG, faculty queries)
  - Reranking, keyword boosting, source diversification
  - Health check on vector DB
  - Accept re-index triggers from Ingestion Worker
```

**API Contract**:

```
POST /search
Request:  { question: str, rewritten_query: str, top_k: int, strategy: "similarity"|"mmr" }
Response: { documents: [{ content: str, source: str, page_type: str, score: float }] }

GET /health
Response: { status: "healthy", document_count: int, last_indexed: str }

POST /reindex   (internal only — called by Ingestion Worker)
Request:  { source: "crawl" | "manual" }
Response: { status: "ok", chunks_indexed: int }
```

**Key design decisions**:
- Single replica only (ChromaDB file lock prevents multiple writers)
- Embedding model (`BAAI/bge-small-en-v1.5`) loaded once at startup (~400MB RAM)
- ChromaDB data stored on a Kubernetes PersistentVolume (survives pod restarts)

**Dependencies**: ChromaDB (PersistentVolume)

---

### 3.3 LLM Service

**Owner of**: All LLM API calls (Groq/Llama)
**Port**: 8002
**Current code mapping**: `services/llm_service.py`, `services/query_rewriter_service.py`

```
Responsibilities:
  - Proxy all LLM calls through a single service
  - Query rewriting (short prompts, temperature=0)
  - Chat response generation (long prompts, temperature=0)
  - Rate limit management against Groq free tier limits
  - Response validation (strip injection patterns)
  - Redis-based response cache (critical for Groq free tier)
  - Token usage tracking
```

**API Contract**:

```
POST /generate
Request:  { prompt: str, temperature: float, model: str, max_tokens: int, task: "rewrite"|"chat" }
Response: { content: str, model: str, tokens_used: int, latency_ms: int }

POST /rewrite
Request:  { question: str }
Response: { rewritten_query: str, original: str }

GET /health
Response: { status: "healthy", groq_reachable: bool, model: str }
```

**Groq Free Tier Limits**:

```
  - 30 requests/minute
  - 14,400 requests/day
  - Each chat = 2 Groq calls (1 rewrite + 1 answer)
  - Max: 7,200 user queries/day without cache
  - With Redis cache (~65% hit rate): ~20,000 effective queries/day
  - University chatbot will see maybe 500-1000 queries/day peak — plenty of room
```

**Key design decisions**:
- Centralizing LLM calls means you can swap Groq for any other provider in one place
- Redis response cache: repeated questions ("what are the fees?") skip Groq entirely
- Retry logic with exponential backoff for rate limits
- Horizontally scalable (no local state, just outbound API calls)

**Dependencies**: Groq API (external, free tier), Redis (for response cache)

---

### 3.4 Session Service

**Owner of**: Conversation history, user sessions
**Port**: 8003
**Current code mapping**: `services/session_service.py`

```
Responsibilities:
  - Store and retrieve conversation history per session
  - Enforce MAX_CHAT_HISTORY limit (3 turns)
  - Session creation, expiry (TTL-based, 30 min)
  - Write to Redis (fast, hot data) + PostgreSQL (durable, cold data)
```

**API Contract**:

```
POST /sessions/{session_id}/messages
Request:  { question: str, answer: str }
Response: { status: "ok" }

GET /sessions/{session_id}/history?limit=3
Response: { messages: [{ question: str, answer: str, timestamp: str }] }

DELETE /sessions/{session_id}
Response: { status: "ok" }

GET /health
Response: { status: "healthy", active_sessions: int }
```

**Key design decisions**:
- Redis as primary store (fast reads, TTL-based expiry at 30 min)
- PostgreSQL as durable backup (for analytics and audit trail)
- Replaces the current in-memory dict that loses data on restart

**Dependencies**: Redis, PostgreSQL

---

### 3.5 Admin Service

**Owner of**: Ingestion triggers, analytics, feedback collection
**Port**: 8004
**Not in current code** — new service

```
Responsibilities:
  - Trigger re-crawl + re-index
  - View ingestion status and logs
  - Collect user feedback (thumbs up/down per answer)
  - Dashboard data: query volume, avg latency, top questions
```

**API Contract**:

```
POST /admin/ingest/trigger
Request:  { url: "https://www.msrit.edu", max_pages: 50 }
Response: { job_id: str, status: "queued" }

GET /admin/ingest/status/{job_id}
Response: { status: "running"|"completed"|"failed", pages_crawled: int, chunks_indexed: int }

POST /admin/feedback
Request:  { session_id: str, question: str, answer: str, rating: "up"|"down", comment: str }
Response: { status: "ok" }

GET /admin/analytics/summary?days=7
Response: { total_queries: int, avg_latency_ms: int, top_questions: [...] }
```

**Dependencies**: PostgreSQL, Ingestion Worker

---

### 3.6 Ingestion Worker

**Owner of**: Web crawling, text processing, vector DB population
**Port**: None (runs as a Kubernetes CronJob)
**Current code mapping**: `ingestion/crawler.py`, `ingestion/build_vector_db.py`

```
Responsibilities:
  - Crawl msrit.edu (or configured URLs)
  - Parse HTML -> clean text
  - Chunk text (800 chars, 150 overlap)
  - Infer page_type metadata
  - Embed chunks using BAAI/bge-small-en-v1.5
  - Write to ChromaDB via Retrieval Service /reindex endpoint
  - Report status back to Admin Service
```

**Key design decisions**:
- Runs as a Kubernetes CronJob (weekly, Sunday 2 AM) or triggered manually via Admin Service
- Calls Retrieval Service's `/reindex` endpoint instead of writing directly to ChromaDB volume
- This avoids shared volume conflicts between Retrieval and Ingestion

---

## 4. Database Layer

### 4.1 Redis (Self-Hosted Container)

Runs as a pod in Minikube. Uses ~30MB RAM for this workload.

```
Session data:
  Key:    session:{session_id}
  Value:  JSON list of {question, answer, timestamp}
  TTL:    1800s (30 min)

LLM response cache:
  Key:    llm_cache:{sha256(prompt)}
  Value:  {content, model, tokens_used}
  TTL:    3600s (1 hour)

  Critical for staying within Groq free tier:
  - "what are the fees?" asked 50 times = 1 Groq call + 49 cache hits
  - Expected cache hit rate for university chatbot: 60-70%
```

### 4.2 PostgreSQL (Self-Hosted Container)

Runs as a pod in Minikube. Uses ~100MB RAM.

```sql
-- Sessions (cold storage, written async from Redis)
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(100) NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    sources         JSONB,
    rewritten_query TEXT,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sessions_session_id ON sessions(session_id);
CREATE INDEX idx_sessions_created_at ON sessions(created_at);

-- Feedback
CREATE TABLE feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  VARCHAR(100) NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    rating      VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
    comment     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Ingestion runs
CREATE TABLE ingestion_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    pages_crawled   INTEGER DEFAULT 0,
    chunks_indexed  INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.3 ChromaDB (Self-Hosted, unchanged)

- Persisted on a Minikube PersistentVolume (survives pod restarts)
- Owned exclusively by the Retrieval Service pod
- ~50MB disk for the MSRIT dataset

---

## 5. Docker Strategy

### 5.1 Service Dockerfiles

```dockerfile
# services/chat-orchestrator/Dockerfile
FROM python:3.11-slim

RUN useradd -m appuser
WORKDIR /app

COPY requirements/base.txt requirements/chat-orchestrator.txt ./
RUN pip install --no-cache-dir -r base.txt -r chat-orchestrator.txt

COPY shared/ shared/
COPY services/chat-orchestrator/ app/

USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

```dockerfile
# services/retrieval/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m appuser
WORKDIR /app

COPY requirements/base.txt requirements/retrieval.txt ./
RUN pip install --no-cache-dir -r base.txt -r retrieval.txt

# Pre-download embedding model during build (avoids ~500MB download on first startup)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY shared/ shared/
COPY services/retrieval/ app/

USER appuser
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
```

```dockerfile
# services/llm/Dockerfile
FROM python:3.11-slim

RUN useradd -m appuser
WORKDIR /app

COPY requirements/base.txt requirements/llm.txt ./
RUN pip install --no-cache-dir -r base.txt -r llm.txt

COPY shared/ shared/
COPY services/llm/ app/

USER appuser
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
```

```dockerfile
# services/session/Dockerfile
FROM python:3.11-slim

RUN useradd -m appuser
WORKDIR /app

COPY requirements/base.txt requirements/session.txt ./
RUN pip install --no-cache-dir -r base.txt -r session.txt

COPY shared/ shared/
COPY services/session/ app/

USER appuser
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]
```

```dockerfile
# services/ingestion-worker/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m appuser
WORKDIR /app

COPY requirements/base.txt requirements/ingestion.txt ./
RUN pip install --no-cache-dir -r base.txt -r ingestion.txt

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY shared/ shared/
COPY services/ingestion-worker/ app/

USER appuser
CMD ["python", "-m", "app.main"]
```

### 5.2 Docker Compose (Local Dev Without Kubernetes)

Use this for quick local testing before deploying to Minikube:

```yaml
# docker-compose.yml
version: "3.9"

services:
  chat-orchestrator:
    build:
      context: .
      dockerfile: services/chat-orchestrator/Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      - RETRIEVAL_SERVICE_URL=http://retrieval:8001
      - LLM_SERVICE_URL=http://llm:8002
      - SESSION_SERVICE_URL=http://session:8003
    depends_on:
      - retrieval
      - llm
      - session

  retrieval:
    build:
      context: .
      dockerfile: services/retrieval/Dockerfile
    ports:
      - "8001:8001"
    volumes:
      - chroma_data:/app/data/chroma_db
    environment:
      - VECTOR_DB_DIR=/app/data/chroma_db

  llm:
    build:
      context: .
      dockerfile: services/llm/Dockerfile
    ports:
      - "8002:8002"
    env_file: .env

  session:
    build:
      context: .
      dockerfile: services/session/Dockerfile
    ports:
      - "8003:8003"
    depends_on:
      - redis
      - postgres
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://chatbot:chatbot@postgres:5432/msrit_chatbot

  admin:
    build:
      context: .
      dockerfile: services/admin/Dockerfile
    ports:
      - "8004:8004"
    depends_on:
      - postgres
    environment:
      - DATABASE_URL=postgresql://chatbot:chatbot@postgres:5432/msrit_chatbot

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: chatbot
      POSTGRES_PASSWORD: chatbot
      POSTGRES_DB: msrit_chatbot
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  chroma_data:
  redis_data:
  pg_data:
```

### 5.3 Building Images for Minikube

```bash
# Option A: Build inside Minikube's Docker daemon (recommended)
eval $(minikube docker-env)
docker build -t msrit/chat-orchestrator:latest -f services/chat-orchestrator/Dockerfile .
docker build -t msrit/retrieval:latest -f services/retrieval/Dockerfile .
docker build -t msrit/llm:latest -f services/llm/Dockerfile .
docker build -t msrit/session:latest -f services/session/Dockerfile .
docker build -t msrit/admin:latest -f services/admin/Dockerfile .
docker build -t msrit/ingestion-worker:latest -f services/ingestion-worker/Dockerfile .

# Option B: Build locally then load into Minikube
docker build -t msrit/chat-orchestrator:latest -f services/chat-orchestrator/Dockerfile .
minikube image load msrit/chat-orchestrator:latest
# Repeat for each service...
```

**Important**: In K8s manifests, set `imagePullPolicy: Never` so Minikube uses the local image instead of trying to pull from a registry:

```yaml
containers:
  - name: chat-orchestrator
    image: msrit/chat-orchestrator:latest
    imagePullPolicy: Never   # <-- Use local image, don't pull
```

### 5.4 .dockerignore

```
venv/
__pycache__/
*.pyc
.git/
.pytest_cache/
data/
*.egg-info/
.env
```

### 5.5 Image Optimization

| Technique | Impact |
|---|---|
| `python:3.11-slim` base | ~150MB vs ~900MB for full image |
| Pre-download embedding model in build | No 500MB download on first startup |
| `.dockerignore` | Smaller build context, faster builds |
| Non-root user | Security best practice |

---

## 6. Kubernetes Deployment (Minikube)

### 6.0 Minikube Setup (One-Time)

```bash
# Install Minikube (if not already installed)
# Windows: winget install minikube
# Or: choco install minikube

# Start Minikube with enough resources
minikube start --cpus=4 --memory=8192 --disk-size=30g --driver=docker

# Enable the Nginx Ingress addon (built-in, free)
minikube addons enable ingress

# Enable metrics-server (needed for monitoring)
minikube addons enable metrics-server

# Verify
kubectl get nodes
# NAME       STATUS   ROLES           AGE   VERSION
# minikube   Ready    control-plane   30s   v1.28.x
```

### 6.1 Namespace

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: msrit-chatbot
  labels:
    app.kubernetes.io/part-of: msrit-chatbot
```

### 6.2 Chat Orchestrator Deployment

```yaml
# k8s/chat-orchestrator/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chat-orchestrator
  namespace: msrit-chatbot
spec:
  replicas: 2
  selector:
    matchLabels:
      app: chat-orchestrator
  template:
    metadata:
      labels:
        app: chat-orchestrator
    spec:
      containers:
        - name: chat-orchestrator
          image: msrit/chat-orchestrator:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8000
          env:
            - name: RETRIEVAL_SERVICE_URL
              value: "http://retrieval-service:8001"
            - name: LLM_SERVICE_URL
              value: "http://llm-service:8002"
            - name: SESSION_SERVICE_URL
              value: "http://session-service:8003"
          envFrom:
            - secretRef:
                name: chatbot-secrets
          resources:
            requests:
              cpu: "200m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
---
# k8s/chat-orchestrator/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: chat-orchestrator
  namespace: msrit-chatbot
spec:
  selector:
    app: chat-orchestrator
  ports:
    - port: 8000
      targetPort: 8000
```

### 6.3 Retrieval Service Deployment

```yaml
# k8s/retrieval/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: retrieval-service
  namespace: msrit-chatbot
spec:
  replicas: 1              # Single replica — ChromaDB file lock
  strategy:
    type: Recreate          # Not RollingUpdate — volume can't be shared
  selector:
    matchLabels:
      app: retrieval-service
  template:
    metadata:
      labels:
        app: retrieval-service
    spec:
      containers:
        - name: retrieval
          image: msrit/retrieval:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8001
          volumeMounts:
            - name: chroma-storage
              mountPath: /app/data/chroma_db
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"       # Embedding model (~400MB) + ChromaDB
            limits:
              cpu: "1000m"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 60     # Slow startup (model loading)
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 45
            periodSeconds: 10
      volumes:
        - name: chroma-storage
          persistentVolumeClaim:
            claimName: chroma-pvc
---
# k8s/retrieval/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: chroma-pvc
  namespace: msrit-chatbot
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard    # Minikube default provisioner
  resources:
    requests:
      storage: 2Gi
---
# k8s/retrieval/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: retrieval-service
  namespace: msrit-chatbot
spec:
  selector:
    app: retrieval-service
  ports:
    - port: 8001
      targetPort: 8001
```

### 6.4 LLM Service Deployment

```yaml
# k8s/llm/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-service
  namespace: msrit-chatbot
spec:
  replicas: 2               # Handle concurrent Groq API calls
  selector:
    matchLabels:
      app: llm-service
  template:
    metadata:
      labels:
        app: llm-service
    spec:
      containers:
        - name: llm
          image: msrit/llm:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8002
          envFrom:
            - secretRef:
                name: chatbot-secrets
          resources:
            requests:
              cpu: "100m"
              memory: "64Mi"    # Lightweight — just API calls to Groq
            limits:
              cpu: "250m"
              memory: "128Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8002
            periodSeconds: 30
---
# k8s/llm/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: llm-service
  namespace: msrit-chatbot
spec:
  selector:
    app: llm-service
  ports:
    - port: 8002
      targetPort: 8002
```

### 6.5 Session Service Deployment

```yaml
# k8s/session/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: session-service
  namespace: msrit-chatbot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: session-service
  template:
    metadata:
      labels:
        app: session-service
    spec:
      containers:
        - name: session
          image: msrit/session:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8003
          env:
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: chatbot-secrets
                  key: REDIS_URL
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: chatbot-secrets
                  key: DATABASE_URL
          resources:
            requests:
              cpu: "100m"
              memory: "64Mi"
            limits:
              cpu: "250m"
              memory: "128Mi"
---
# k8s/session/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: session-service
  namespace: msrit-chatbot
spec:
  selector:
    app: session-service
  ports:
    - port: 8003
      targetPort: 8003
```

### 6.6 Redis & PostgreSQL (StatefulSets)

```yaml
# k8s/redis/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: msrit-chatbot
spec:
  serviceName: redis
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          args: ["--maxmemory", "128mb", "--maxmemory-policy", "allkeys-lru"]
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "200m"
              memory: "192Mi"
          volumeMounts:
            - name: redis-data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: redis-data
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 1Gi
---
# k8s/redis/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: msrit-chatbot
spec:
  selector:
    app: redis
  ports:
    - port: 6379
---
# k8s/postgres/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: msrit-chatbot
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: chatbot-secrets
                  key: POSTGRES_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: chatbot-secrets
                  key: POSTGRES_PASSWORD
            - name: POSTGRES_DB
              value: msrit_chatbot
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
          volumeMounts:
            - name: pg-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pg-data
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 5Gi
---
# k8s/postgres/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: msrit-chatbot
spec:
  selector:
    app: postgres
  ports:
    - port: 5432
```

### 6.7 Ingestion CronJob

```yaml
# k8s/ingestion/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ingestion-worker
  namespace: msrit-chatbot
spec:
  schedule: "0 2 * * 0"      # Every Sunday at 2 AM
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: ingestion
              image: msrit/ingestion-worker:latest
              imagePullPolicy: Never
              env:
                - name: RETRIEVAL_SERVICE_URL
                  value: "http://retrieval-service:8001"
              resources:
                requests:
                  cpu: "500m"
                  memory: "1Gi"
                limits:
                  cpu: "1000m"
                  memory: "2Gi"
          restartPolicy: OnFailure
```

### 6.8 Secrets

```yaml
# k8s/secrets.yaml  (DO NOT commit to git — add to .gitignore)
apiVersion: v1
kind: Secret
metadata:
  name: chatbot-secrets
  namespace: msrit-chatbot
type: Opaque
stringData:
  GROQ_API_KEY: "your-groq-api-key"
  REDIS_URL: "redis://redis:6379/0"
  DATABASE_URL: "postgresql://chatbot:chatbot@postgres:5432/msrit_chatbot"
  POSTGRES_USER: "chatbot"
  POSTGRES_PASSWORD: "chatbot"
```

### 6.9 Ingress (Nginx — Minikube Addon)

```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: msrit-chatbot-ingress
  namespace: msrit-chatbot
  annotations:
    nginx.ingress.kubernetes.io/rate-limit: "30"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: chat-orchestrator
                port:
                  number: 8000
          - path: /admin
            pathType: Prefix
            backend:
              service:
                name: admin-service
                port:
                  number: 8004
```

### 6.10 Accessing the App

```bash
# Start the tunnel (run in a separate terminal, keep it open)
minikube tunnel

# Now access the chatbot at:
# http://localhost/api/chat     (Chat endpoint)
# http://localhost/admin        (Admin endpoint)
# http://localhost/health       (Health check)

# Alternative: use minikube service to open a specific service
minikube service chat-orchestrator -n msrit-chatbot
```

### 6.11 Deploying Everything (One-Shot)

```bash
# 1. Start Minikube
minikube start --cpus=4 --memory=8192 --disk-size=30g
minikube addons enable ingress
minikube addons enable metrics-server

# 2. Build all images inside Minikube's Docker
eval $(minikube docker-env)
docker build -t msrit/chat-orchestrator:latest -f services/chat-orchestrator/Dockerfile .
docker build -t msrit/retrieval:latest -f services/retrieval/Dockerfile .
docker build -t msrit/llm:latest -f services/llm/Dockerfile .
docker build -t msrit/session:latest -f services/session/Dockerfile .
docker build -t msrit/admin:latest -f services/admin/Dockerfile .
docker build -t msrit/ingestion-worker:latest -f services/ingestion-worker/Dockerfile .

# 3. Deploy all K8s resources
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/redis/
kubectl apply -f k8s/postgres/
kubectl apply -f k8s/retrieval/
kubectl apply -f k8s/llm/
kubectl apply -f k8s/session/
kubectl apply -f k8s/chat-orchestrator/
kubectl apply -f k8s/ingestion/
kubectl apply -f k8s/ingress.yaml

# 4. Wait for everything to be ready
kubectl get pods -n msrit-chatbot -w

# 5. Access
minikube tunnel    # In a separate terminal
curl http://localhost/api/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "what are the fees?", "session_id": "test-123"}'
```

### 6.12 Useful Minikube Commands

```bash
# Check pod status
kubectl get pods -n msrit-chatbot

# Check logs for a service
kubectl logs -f deployment/chat-orchestrator -n msrit-chatbot

# Restart a deployment (after rebuilding image)
kubectl rollout restart deployment/chat-orchestrator -n msrit-chatbot

# Scale a service
kubectl scale deployment/llm-service --replicas=3 -n msrit-chatbot

# Open Minikube dashboard (GUI)
minikube dashboard

# Check resource usage
kubectl top pods -n msrit-chatbot

# Delete everything and start fresh
kubectl delete namespace msrit-chatbot
```

### 6.13 Resource Budget (Fits in Minikube 4CPU/8GB)

```
Minikube: 4 CPUs, 8GB RAM (allocated from your machine)

Service                  CPU (req/lim)    RAM (req/lim)     Replicas
─────────────────────────────────────────────────────────────────────
Minikube system          ~500m            ~512Mi            -
Nginx Ingress            ~100m            ~64Mi             1
Chat Orchestrator        200m/500m        128Mi/256Mi       2
Retrieval Service        500m/1000m       1Gi/2Gi           1
LLM Service              100m/250m        64Mi/128Mi        2
Session Service          100m/250m        64Mi/128Mi        1
Redis                    50m/200m         64Mi/192Mi        1
PostgreSQL               100m/500m        128Mi/256Mi       1
─────────────────────────────────────────────────────────────────────
TOTAL REQUESTED          ~1.75 CPU        ~2.1Gi
TOTAL LIMITS             ~3.5 CPU         ~3.5Gi
AVAILABLE                4 CPU            8Gi

Headroom: ~2.25 CPU and ~4.5Gi free
```

---

## 7. CI/CD Pipeline

### GitHub Actions (Free — Unlimited for Public Repos)

Since you're running locally, CI/CD focuses on **testing on push** rather than deploying to a remote server. Deployment is a manual `kubectl` command on your machine.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install ruff
      - run: ruff check .

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install -r requirements/base.txt -r requirements/test.txt
      - run: pytest tests/ -v --tb=short

  build-check:
    runs-on: ubuntu-latest
    needs: test
    strategy:
      matrix:
        service: [chat-orchestrator, retrieval, llm, session, admin, ingestion-worker]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: services/${{ matrix.service }}/Dockerfile
          push: false       # Just build, don't push anywhere
          tags: msrit/${{ matrix.service }}:ci-test
```

### Local Deploy Workflow

After CI passes, deploy on your machine:

```bash
# Pull latest code
git pull origin main

# Rebuild images inside Minikube
eval $(minikube docker-env)
docker build -t msrit/chat-orchestrator:v2 -f services/chat-orchestrator/Dockerfile .
docker build -t msrit/retrieval:v2 -f services/retrieval/Dockerfile .
# ... repeat for changed services

# Rolling update
kubectl set image deployment/chat-orchestrator \
  chat-orchestrator=msrit/chat-orchestrator:v2 -n msrit-chatbot
kubectl rollout status deployment/chat-orchestrator -n msrit-chatbot
```

### Optional: Local Deploy Script

```bash
#!/bin/bash
# deploy.sh — Build and deploy all services to Minikube

set -e

echo "Switching to Minikube Docker..."
eval $(minikube docker-env)

VERSION=$(git rev-parse --short HEAD)

SERVICES=("chat-orchestrator" "retrieval" "llm" "session" "admin" "ingestion-worker")

for svc in "${SERVICES[@]}"; do
  echo "Building msrit/$svc:$VERSION..."
  docker build -t "msrit/$svc:$VERSION" -f "services/$svc/Dockerfile" .
done

echo "Updating deployments..."
kubectl set image deployment/chat-orchestrator chat-orchestrator="msrit/chat-orchestrator:$VERSION" -n msrit-chatbot
kubectl set image deployment/retrieval-service retrieval="msrit/retrieval:$VERSION" -n msrit-chatbot
kubectl set image deployment/llm-service llm="msrit/llm:$VERSION" -n msrit-chatbot
kubectl set image deployment/session-service session="msrit/session:$VERSION" -n msrit-chatbot

echo "Waiting for rollout..."
kubectl rollout status deployment/chat-orchestrator -n msrit-chatbot --timeout=120s

echo "Deploy complete!"
kubectl get pods -n msrit-chatbot
```

---

## 8. Observability Stack

### 8.1 Structured Logging

All services emit structured JSON logs:

```python
# shared/logging.py
import structlog

def setup_logger(service_name: str):
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )
    return structlog.get_logger(service=service_name)
```

View logs directly with kubectl:

```bash
# Follow logs from all pods
kubectl logs -f -l app=chat-orchestrator -n msrit-chatbot

# Follow all logs in the namespace
kubectl logs -f --all-containers -n msrit-chatbot --prefix
```

### 8.2 Prometheus + Grafana (Optional, Self-Hosted)

Only set this up if you want dashboards. `kubectl logs` is enough to start.

```bash
# Install via Helm (free, open source)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin \
  --set prometheus.prometheusSpec.retention=3d \
  --set prometheus.prometheusSpec.resources.requests.memory=256Mi \
  --set grafana.resources.requests.memory=128Mi

# Access Grafana
kubectl port-forward svc/monitoring-grafana 3000:80 -n monitoring
# Open http://localhost:3000 (admin/admin)
```

### 8.3 Application Metrics

Each service exposes `/metrics` via `prometheus-fastapi-instrumentator`:

```
# Chat Orchestrator
chatbot_requests_total{status="success|error"}
chatbot_request_duration_seconds{phase="rewrite|retrieval|llm|total"}

# Retrieval Service
retrieval_search_duration_seconds{strategy="similarity|mmr"}
retrieval_documents_returned{query_type="factual|faculty|pg|general"}

# LLM Service
llm_requests_total{task="rewrite|chat"}
llm_latency_seconds{task="rewrite|chat"}
llm_groq_rate_limit_remaining      # Track Groq free tier usage
```

### 8.4 Minikube Dashboard (Easiest Option)

```bash
minikube dashboard
# Opens a web UI showing all pods, deployments, logs, resource usage
# This is free and built into Minikube — no extra install needed
```

---

## 9. Security

### 9.1 Container Security

- All containers run as non-root user (already in Dockerfiles above)
- `imagePullPolicy: Never` — images only come from local builds, not the internet

### 9.2 API Security

- CORS restricted to frontend domain only (replace `allow_origins=["*"]`)
- Input validation on all endpoints (Pydantic models — already in place)
- Query rewriter validates against injection patterns (already in place)
- Admin endpoints behind API key header

### 9.3 Secrets

- K8s Secrets for API keys and DB credentials
- `k8s/secrets.yaml` added to `.gitignore` — never committed
- In production, consider SOPS (free) for encrypted secrets in git

### 9.4 Network (Minikube)

- Only the Ingress is exposed externally
- All internal services (Retrieval, LLM, Session, Redis, PostgreSQL) are ClusterIP only
- Not accessible from outside the cluster

---

## 10. Migration Plan

### Phase 1: Containerize the Monolith (Week 1)

```
Goal: Current app runs in Docker Compose with no code changes

Tasks:
  [ ] Write Dockerfile for current monolith
  [ ] Write docker-compose.yml with app + Redis + PostgreSQL
  [ ] Write .dockerignore
  [ ] Migrate SessionService from in-memory dict to Redis
  [ ] Create PostgreSQL schema
  [ ] Test: docker-compose up -> POST /api/chat -> get answer
```

### Phase 2: Extract Services (Weeks 2-3)

```
Goal: Split monolith into services communicating over HTTP

Tasks:
  [ ] Create shared/ directory (schemas, logging, config, HTTP client)
  [ ] Extract Retrieval Service (owns ChromaDB + search logic)
  [ ] Extract LLM Service (owns Groq client + query rewriting + response cache)
  [ ] Extract Session Service (owns Redis + PostgreSQL sessions)
  [ ] Chat Orchestrator = remaining orchestration logic
  [ ] Each service gets its own Dockerfile
  [ ] Update docker-compose.yml with all 7 containers
  [ ] Add Redis-based LLM response caching (critical for Groq free tier)
  [ ] Integration test: full chat flow across all services
```

### Phase 3: Minikube Kubernetes Setup (Week 4)

```
Goal: All services running on Minikube

Tasks:
  [ ] Install Minikube (minikube start --cpus=4 --memory=8192)
  [ ] Enable ingress and metrics-server addons
  [ ] Build all Docker images inside Minikube
  [ ] Write K8s manifests (deployments, services, PVCs, secrets)
  [ ] Deploy Redis and PostgreSQL as StatefulSets
  [ ] Deploy application services as Deployments
  [ ] Configure Nginx Ingress
  [ ] Test: minikube tunnel -> curl http://localhost/api/chat -> get answer
  [ ] Write deploy.sh script for quick rebuilds
```

### Phase 4: CI + Observability (Week 5)

```
Goal: Automated testing and basic monitoring

Tasks:
  [ ] Write GitHub Actions CI workflow (lint + test + build-check)
  [ ] Add structured logging (structlog) to all services
  [ ] Add prometheus-fastapi-instrumentator to each service
  [ ] Optionally install Prometheus + Grafana via Helm
  [ ] Use Minikube dashboard for quick pod monitoring
  [ ] Add Groq rate limit tracking in LLM Service
```

### Phase 5: Admin Service + Ingestion (Week 6)

```
Goal: Admin dashboard and automated re-indexing

Tasks:
  [ ] Build Admin Service (FastAPI)
  [ ] Set up Ingestion Worker as K8s CronJob
  [ ] Build feedback collection endpoint
  [ ] Build analytics query endpoints
  [ ] Wire up ingestion trigger: Admin -> Worker -> Retrieval /reindex
  [ ] Test full re-index cycle
```

---

## 11. Directory Structure

```
msrit_chatbot/
├── backend2.md                         # This document
├── docker-compose.yml                  # Local dev (no K8s)
├── deploy.sh                           # Build + deploy to Minikube
├── .dockerignore
├── .github/
│   └── workflows/
│       └── ci.yml                      # Lint + test + build-check
├── shared/                             # Code shared across all services
│   ├── __init__.py
│   ├── schemas/
│   │   ├── chat.py                     # ChatRequest, ChatResponse
│   │   └── response.py                # ErrorResponse, RetrievedChunk
│   ├── logging.py                      # Structured logger (structlog)
│   ├── config.py                       # Shared config base class
│   └── http_client.py                  # httpx async client with retries
├── requirements/
│   ├── base.txt                        # fastapi, uvicorn, pydantic, structlog, httpx
│   ├── chat-orchestrator.txt           # (mostly covered by base)
│   ├── retrieval.txt                   # langchain, chromadb, sentence-transformers
│   ├── llm.txt                         # groq
│   ├── session.txt                     # redis, asyncpg, sqlalchemy
│   ├── ingestion.txt                   # beautifulsoup4, requests, langchain
│   └── test.txt                        # pytest, httpx, pytest-asyncio
├── services/
│   ├── chat-orchestrator/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── chat.py                 # POST /api/chat
│   │   ├── clients/
│   │   │   ├── retrieval_client.py     # HTTP calls to Retrieval Service
│   │   │   ├── llm_client.py           # HTTP calls to LLM Service
│   │   │   └── session_client.py       # HTTP calls to Session Service
│   │   ├── prompts.py
│   │   └── config.py
│   ├── retrieval/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── search.py               # POST /search, POST /reindex
│   │   ├── vector_store.py
│   │   ├── search_strategies.py
│   │   └── config.py
│   ├── llm/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── generate.py             # POST /generate, POST /rewrite
│   │   ├── groq_client.py
│   │   ├── cache.py                    # Redis LLM response cache
│   │   ├── validators.py
│   │   └── config.py
│   ├── session/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── sessions.py
│   │   ├── redis_store.py
│   │   ├── pg_store.py
│   │   └── config.py
│   ├── admin/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/
│   │   │   ├── ingestion.py
│   │   │   ├── feedback.py
│   │   │   └── analytics.py
│   │   └── config.py
│   └── ingestion-worker/
│       ├── Dockerfile
│       ├── main.py
│       ├── crawler.py
│       ├── chunker.py
│       └── config.py
├── k8s/
│   ├── namespace.yaml
│   ├── secrets.yaml                    # .gitignored
│   ├── ingress.yaml
│   ├── chat-orchestrator/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── retrieval/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── pvc.yaml
│   ├── llm/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── session/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── admin/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── redis/
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── postgres/
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   └── ingestion/
│       └── cronjob.yaml
└── tests/
    ├── unit/
    │   ├── test_chat_orchestrator.py
    │   ├── test_retrieval.py
    │   ├── test_llm.py
    │   └── test_session.py
    ├── integration/
    │   └── test_full_chat_flow.py
    └── conftest.py
```

---

## Quick Reference

### Service Ports

| Service | Port | Access |
|---|---|---|
| Chat Orchestrator | 8000 | `http://localhost/api` (via Ingress + minikube tunnel) |
| Retrieval Service | 8001 | Internal only (ClusterIP) |
| LLM Service | 8002 | Internal only (ClusterIP) |
| Session Service | 8003 | Internal only (ClusterIP) |
| Admin Service | 8004 | `http://localhost/admin` (via Ingress) |
| Redis | 6379 | Internal only (ClusterIP) |
| PostgreSQL | 5432 | Internal only (ClusterIP) |

### Total Cost

```
Docker Desktop:       Free (personal use)
Minikube:             Free (open source)
Groq API:             Free tier (14,400 req/day)
Redis:                Free (self-hosted container)
PostgreSQL:           Free (self-hosted container)
ChromaDB:             Free (self-hosted container)
Embedding model:      Free (runs locally on CPU)
GitHub Actions CI:    Free (public repos unlimited, private 2000 min/month)
───────────────────────────────────
TOTAL:                $0/month
```

### Groq Free Tier Budget

```
Groq limit:              14,400 requests/day
Each user chat:          2 Groq calls (1 rewrite + 1 answer)
Max without cache:       7,200 chats/day
With Redis cache (~65%): ~20,000 effective chats/day
Expected university load: 500-1000 chats/day

You have 20x headroom. No risk of hitting limits.
```
