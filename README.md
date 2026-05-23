# MSRIT AI Chatbot

An intelligent, production-ready RAG (Retrieval-Augmented Generation) chatbot for **Ramaiah Institute of Technology (MSRIT)**. Ask anything about admissions, departments, faculty, fees, rankings, programs, and campus life — and get accurate, source-backed answers.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / Client                         │
│                   React + Vite + Tailwind CSS                   │
│                          (Port 80)                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │  POST /api/chat
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Chat Orchestrator                           │
│                        (Port 8000)                              │
│  1. Rewrites user query for semantic search                     │
│  2. Retrieves relevant documents                                │
│  3. Fetches conversation history                                │
│  4. Generates answer with context                               │
│  5. Saves Q&A to session                                        │
└──────┬──────────────────┬──────────────────┬────────────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────────┐
│  LLM Service │  │   Retrieval   │  │  Session Service │
│  (Port 8002) │  │   Service     │  │   (Port 8003)    │
│              │  │  (Port 8001)  │  │                  │
│  Groq API    │  │  ChromaDB     │  │  Chat History    │
│  (Llama 4)   │  │  Embeddings   │  │  (30 min TTL)    │
│  Redis Cache │  │  (BGE Small)  │  │                  │
└──────┬───────┘  └──────┬────────┘  └────────┬─────────┘
       │                 │                    │
       └────────┬────────┘                   │
                ▼                            ▼
         ┌──────────────────┐        ┌───────────────┐
         │   Redis          │        │   Redis       │
         │  (Port 6379)     │        │  (Port 6379)  │
         │  LLM Cache       │        │  Sessions     │
         │  (1 hr TTL)      │        │  (30 min TTL) │
         └──────────────────┘        └───────────────┘
```

---

## Services

| Service | Port | Responsibility |
|---|---|---|
| **frontend** | 80 | React UI served via Nginx; proxies `/api` to orchestrator |
| **chat-orchestrator** | 8000 | Main entry point; orchestrates the full chat pipeline |
| **retrieval-service** | 8001 | Semantic search over MSRIT knowledge base (ChromaDB) |
| **llm-service** | 8002 | LLM generation via Groq API; Redis-backed prompt cache |
| **session-service** | 8003 | Conversation history; auto-expires after 30 minutes |
| **redis** | 6379 | Shared cache & session store |

---

## Tech Stack

**Backend**
- Python 3.11 · FastAPI · Uvicorn
- ChromaDB — vector store for document embeddings
- Sentence Transformers — `BAAI/bge-small-en-v1.5` embedding model
- Groq API — `meta-llama/llama-4-scout-17b-16e-instruct` LLM
- Redis — LLM response caching + session storage
- LangChain — document processing and retrieval

**Frontend**
- React 18 · Vite 5 · Tailwind CSS
- react-markdown + remark-gfm — markdown rendering
- Nginx — production static file server + API reverse proxy

---

## Prerequisites

- [Docker](https://www.docker.com/) >= 24 with Docker Compose V2
- [Docker BuildKit](https://docs.docker.com/build/buildkit/) enabled (set automatically via `.env`)
- A **Groq API key** — get one free at [console.groq.com](https://console.groq.com)

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Rohith-AI-HUB/msrit-chatbot.git
cd msrit-chatbot
```

### 2. Set your Groq API key

```bash
cp .env.example .env
# Edit .env and set GROQ_API_KEY=gsk_...
```

### 3. Build and run all services

```bash
docker compose up --build
```

> The first build takes 3–5 minutes — the retrieval service downloads the embedding model (~130 MB) at build time and caches it.

### 4. Open the app

```
http://localhost:80
```

The chat UI will be ready once all health checks pass. You can watch the logs with:

```bash
docker compose logs -f chat-orchestrator
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```env
# Required
GROQ_API_KEY=gsk_...           # Your Groq API key

# Docker BuildKit (already set — speeds up builds)
DOCKER_BUILDKIT=1
COMPOSE_DOCKER_CLI_BUILD=1
```

All other service configuration (Redis URLs, model names, timeouts, TTLs) has sensible defaults baked into each service's `config.py` and can be overridden via `docker-compose.yml` environment blocks.

| Variable | Service | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | llm-service | — | **Required.** Groq API key |
| `LLM_MODEL` | llm-service | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq model ID |
| `LLM_TEMPERATURE` | llm-service | `0.0` | Response randomness (0 = deterministic) |
| `CACHE_TTL` | llm-service | `3600` | LLM response cache TTL in seconds |
| `REDIS_URL` | llm-service, session-service | `redis://redis:6379/0` | Redis connection string |
| `EMBEDDING_MODEL` | retrieval-service | `BAAI/bge-small-en-v1.5` | HuggingFace embedding model |
| `VECTOR_DB_DIR` | retrieval-service | `/app/data/chroma_db` | Path to ChromaDB data directory |
| `RETRIEVAL_TOP_K` | retrieval-service | `6` | Number of final documents returned |
| `RETRIEVAL_FETCH_K` | retrieval-service | `20` | Documents fetched before re-ranking |
| `MAX_CHAT_HISTORY` | session-service | `3` | Message pairs retained per session |
| `SESSION_TTL` | session-service | `1800` | Session expiry in seconds |
| `REQUEST_TIMEOUT` | chat-orchestrator | `30` | HTTP timeout to downstream services |

---

## API Reference

All requests go through the Chat Orchestrator at `http://localhost:8000`.

### `POST /api/chat`

Send a question and receive a sourced answer.

**Request**
```json
{
  "question": "What are the B.E. programs offered at MSRIT?",
  "session_id": "session-1716480000000",
  "debug": false
}
```

**Response**
```json
{
  "answer": "MSRIT offers the following B.E. programs: ...",
  "sources": ["msrit_ug_brochure.pdf", "departments.html"],
  "rewritten_query": "Undergraduate B.E. programs offered at MSRIT",
  "retrieved_documents_count": 6
}
```

### `GET /health` (all services)

Returns service status and metadata.

```json
{ "status": "healthy", "documents": 1842 }
```

---

## Data Ingestion

The knowledge base is stored as vector embeddings in ChromaDB at `./backend/data/chroma_db`. The retrieval service mounts this directory at startup.

To re-ingest data from MSRIT's website, use the scrapers in the project root:

```bash
# Install scraper dependencies
pip install playwright requests beautifulsoup4
playwright install chromium

# Crawl the full MSRIT site (BFS)
python intelligent_crawler.py

# Scrape PDFs, result pages, and handle CAPTCHAs
python playwright_scraper.py
```

After scraping, run the ingestion pipeline to populate ChromaDB:

```bash
cd backend
pip install -r requirements.txt
python ingestion/ingest.py
```

---

## Project Structure

```
msrit_chatbot/
├── services/
│   ├── chat-orchestrator/   # Main API gateway & pipeline orchestrator
│   ├── retrieval-service/   # Vector search & re-ranking (ChromaDB)
│   ├── llm-service/         # Groq LLM + Redis cache
│   ├── session-service/     # Conversation history (Redis)
│   └── shared/              # Pydantic schemas & logging shared across services
├── frontend/                # React + Vite + Tailwind chat UI
│   └── nginx.conf           # Nginx config (static files + /api proxy)
├── backend/
│   ├── data/
│   │   ├── chroma_db/       # Persistent vector database (mounted into retrieval-service)
│   │   └── pdfs/            # Source PDFs
│   └── ingestion/           # Scripts to embed and store documents
├── docker-compose.yml
├── .env                     # Local secrets (not committed)
├── .env.example             # Template for required environment variables
└── README.md
```

---

## Development

To run services individually without Docker:

```bash
# Start Redis
docker run -p 6379:6379 redis:7-alpine

# Start each service (from the services/ directory)
cd services
uvicorn retrieval-service.main:app --port 8001 --reload
uvicorn llm-service.main:app --port 8002 --reload
uvicorn session-service.main:app --port 8003 --reload
uvicorn chat-orchestrator.main:app --port 8000 --reload

# Start the frontend dev server (with hot reload)
cd frontend
npm install
npm run dev   # http://localhost:3000
```

The Vite dev server proxies `/api` to `http://localhost:8000` automatically.

---

## Useful Commands

```bash
# Start all services in the background
docker compose up -d

# View logs for a specific service
docker compose logs -f retrieval-service

# Rebuild a single service after code changes
docker compose up --build chat-orchestrator

# Stop all services
docker compose down

# Stop and remove all volumes (clears Redis & vector DB)
docker compose down -v

# Check health of all services
docker compose ps
```

---

## License

MIT
