# MSRIT Chatbot — Feature Plan

> Features to implement on top of the existing RAG chatbot + microservices + Docker + Kubernetes stack.

---

## Tier 1 — High Impact, Very Demonstrable

### 1. Streaming Responses (SSE)

**What**: Tokens stream to the frontend in real-time instead of waiting 8-10s for a full response.

**Why it impresses**: Every teacher has used ChatGPT. They'll instantly recognize the streaming behavior.

**How it works**:

```
Current:  User asks -> waits 8s -> full answer appears
New:      User asks -> tokens appear word by word in ~100ms intervals
```

**Technical approach**:
- Chat Orchestrator exposes a new `POST /api/chat/stream` endpoint
- Uses Server-Sent Events (SSE) via FastAPI's `StreamingResponse`
- LLM Service calls Groq API with `stream=True`
- Tokens forwarded to Chat Orchestrator -> frontend as they arrive
- Non-streaming `/api/chat` endpoint remains for backward compatibility

**Services affected**: Chat Orchestrator, LLM Service

---

### 2. Distributed Tracing (Jaeger)

**What**: Click any request in the Jaeger UI and see it flow through all microservices with timing bars.

**Why it impresses**: Visual proof that microservices actually communicate. Shows production-grade observability.

**What it looks like**:

```
Request (total: 4.2s)
├── Chat Orchestrator                          ████████████████████████  4.2s
│   ├── LLM Service /rewrite                  ███                       0.8s
│   ├── Retrieval Service /search              █████                     1.1s
│   ├── Session Service /history               █                         0.1s
│   ├── LLM Service /generate                 ████████████              2.1s
│   └── Session Service /messages              █                         0.1s
```

**Technical approach**:
- Add `opentelemetry-instrumentation-fastapi` to each service
- Deploy Jaeger (all-in-one) as a pod in Minikube — free, open source
- Each service propagates `trace_id` in HTTP headers automatically
- Access Jaeger UI at `http://localhost:16686`

**Services affected**: All services (add OpenTelemetry SDK), + new Jaeger pod

---

### 3. Live Grafana Dashboard

**What**: Real-time graphs showing queries/sec, latency, Groq API usage, cache hit rate.

**Why it impresses**: Open it during demo, ask a chatbot question, watch the metrics spike live.

**Key panels**:
- Requests per second (with success/error split)
- p50 / p95 / p99 response latency
- Groq API calls remaining today (out of 14,400)
- Redis cache hit rate (%)
- Active sessions count
- Per-service CPU and memory usage

**Technical approach**:
- Add `prometheus-fastapi-instrumentator` to each service (auto-exposes `/metrics`)
- Install Prometheus + Grafana via Helm on Minikube (one command)
- Import a pre-built dashboard JSON
- Access at `http://localhost:3000`

**Services affected**: All services (add metrics library), + Prometheus/Grafana pods

---

### 4. Load Test + Auto-Scaling Demo

**What**: Run 100 simulated users hitting the chatbot. Show pods scaling from 2 to 5 in real-time.

**Why it impresses**: Proves the Kubernetes HPA (Horizontal Pod Autoscaler) actually works. Very visual.

**Demo script**:

```bash
# Terminal 1: Watch pods
kubectl get pods -n msrit-chatbot -w

# Terminal 2: Run load test
locust -f loadtest.py --headless -u 100 -r 10 --host http://localhost

# Show: pods scaling up from 2 -> 5
# Show: Grafana latency graph spiking then stabilizing
# Stop load test -> pods scale back down
```

**Technical approach**:
- Write a Locust load test file (`loadtest.py`) — ~20 lines of Python
- Add HPA manifests for Chat Orchestrator and LLM Service
- HPA triggers at 70% CPU utilization
- Minikube metrics-server addon (already enabled) provides CPU data

**Files needed**: `loadtest.py`, `k8s/chat-orchestrator/hpa.yaml`, `k8s/llm/hpa.yaml`

**HPA manifest**:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: chat-orchestrator-hpa
  namespace: msrit-chatbot
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: chat-orchestrator
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

### 5. Semantic Cache

**What**: Cache LLM responses by meaning, not just exact string match.

**Why it impresses**: Most students (and many professionals) don't know this exists. Genuinely novel.

**How it works**:

```
Normal cache:
  "what are the fees?"        -> cache HIT
  "how much does it cost?"    -> cache MISS  (different string)

Semantic cache:
  "what are the fees?"        -> cache HIT
  "how much does it cost?"    -> cache HIT   (similar meaning, cosine similarity > 0.92)
```

**Technical approach**:
- Before calling Groq, embed the user question using `BAAI/bge-small-en-v1.5`
- Search a small ChromaDB collection (`llm_cache`) for similar past questions
- If cosine similarity > 0.92 -> return cached answer (skip Groq call entirely)
- If miss -> call Groq, then store (question_embedding, answer) in the cache collection
- TTL: evict entries older than 1 hour

**Services affected**: LLM Service (add semantic cache logic), Retrieval Service (or a shared embedding endpoint)

---

## Tier 2 — Smart Engineering, Shows Depth

### 6. Circuit Breaker

**What**: When Groq API goes down, the chatbot doesn't crash. It degrades gracefully.

**Why it impresses**: Shows understanding of distributed systems failure modes. Production thinking.

**Demo**: Kill Groq connectivity mid-demo. Instead of an error, the user sees:

```
"I'm currently unable to generate a full answer, but based on our database,
here are the most relevant pages for your question:
  - https://www.msrit.edu/fees
  - https://www.msrit.edu/hostel
Please visit these pages for details."
```

**Technical approach**:
- LLM Service tracks consecutive failures
- After 3 failures in 60 seconds -> circuit opens
- While open: skip Groq, return retrieved documents directly as the answer
- After 30 seconds -> try one request (half-open state)
- If it works -> circuit closes, back to normal
- Use `pybreaker` library (free)

**Services affected**: LLM Service, Chat Orchestrator (handle fallback response)

---

### 7. Feedback + Analytics

**What**: Thumbs up/down on every answer. Admin page shows feedback stats and worst-performing queries.

**Why it impresses**: Shows data-driven thinking. Teachers love seeing metrics on quality.

**What the analytics show**:

```
Last 7 days:
  Total queries:     342
  Positive feedback:  85% (291)
  Negative feedback:  15% (51)

  Worst queries (most downvoted):
  1. "library timings"         — 8 downvotes (no library data in DB)
  2. "exam schedule 2025"      — 5 downvotes (stale data)
  3. "scholarship details"     — 4 downvotes (incomplete retrieval)
```

**Technical approach**:
- New endpoint: `POST /api/feedback` with `{ session_id, question, answer, rating: "up"|"down" }`
- Store in PostgreSQL `feedback` table (schema already defined in backend2.md)
- Admin endpoint: `GET /admin/analytics/summary?days=7`
- Frontend: simple thumbs up/down buttons under each answer

**Services affected**: Chat Orchestrator (new endpoint), Admin Service (analytics query)

---

### 8. A/B Testing Prompts

**What**: 50% of users get System Prompt A, 50% get Prompt B. Track which gets better feedback.

**Why it impresses**: This is what real AI companies (OpenAI, Anthropic) do to improve their models. No student does this.

**Example**:

```
Prompt A (current): "You are an official AI assistant for MSRIT..."
Prompt B (new):     "You are a helpful MSRIT student guide. Answer in 2-3 sentences max..."

After 200 queries:
  Prompt A: 82% positive feedback
  Prompt B: 89% positive feedback  <-- winner
```

**Technical approach**:
- Chat Orchestrator assigns variant "A" or "B" randomly (50/50) per session
- Stores variant in session metadata
- Feedback records include the variant
- Admin analytics endpoint: `GET /admin/analytics/ab-test` shows comparison

**Services affected**: Chat Orchestrator, Session Service (store variant), Admin Service

---

### 9. Cache-Hit Indicator

**What**: Response includes metadata showing whether it came from cache or live Groq.

**Why it impresses**: Makes the caching system visible and tangible. Easy to demo.

**Response example**:

```json
{
  "answer": "The fees for B.E. Computer Science are...",
  "sources": ["https://www.msrit.edu/fees"],
  "cache_hit": true,
  "response_time_ms": 47,
  "source_label": "Answered from semantic cache (47ms)"
}
```

vs.

```json
{
  "answer": "The fees for B.E. Computer Science are...",
  "sources": ["https://www.msrit.edu/fees"],
  "cache_hit": false,
  "response_time_ms": 3200,
  "source_label": "Answered from Groq LLM (3.2s)"
}
```

**Technical approach**:
- LLM Service returns `cache_hit: bool` and `response_time_ms: int` in every response
- Chat Orchestrator passes it through to the frontend
- Add `cache_hit` and `response_time_ms` fields to `ChatResponse` schema

**Services affected**: LLM Service, Chat Orchestrator, schemas

---

### 10. Request Replay / Debug Mode

**What**: Admin panel shows every question step-by-step: original query -> rewritten query -> retrieved docs -> LLM prompt -> final answer.

**Why it impresses**: Like a debugger for the RAG pipeline. Makes the entire system transparent.

**What it shows**:

```
Request #342 | 2026-05-16 10:23:14 | Session: abc-123

Step 1 — Original Query:
  "hostel fees"

Step 2 — Rewritten Query (LLM, 0.8s):
  "MSRIT hostel fee structure and charges"

Step 3 — Retrieved Documents (Retrieval, 1.1s):
  [DOC 1] source=msrit.edu/hostel | score=0.91 | "Hostel fees are Rs. 65,000..."
  [DOC 2] source=msrit.edu/fees   | score=0.87 | "Fee structure for academic..."
  [DOC 3] source=msrit.edu/hostel | score=0.85 | "Accommodation includes..."

Step 4 — LLM Prompt (sent to Groq):
  "You are an official AI assistant for MSRIT... CONTEXT: [docs] QUESTION: hostel fees"

Step 5 — Final Answer (Groq, 2.1s):
  "Hostel fees at MSRIT are Rs. 65,000 per semester..."

Total time: 4.2s | Cache hit: No | Feedback: thumbs up
```

**Technical approach**:
- Chat Orchestrator already has the `debug` flag in `ChatRequest`
- Expand it: log every step (query, rewritten query, docs, prompt, answer, timings) to PostgreSQL
- Admin endpoint: `GET /admin/requests/{id}` returns the full trace
- This complements Jaeger tracing (Jaeger shows timing, this shows content)

**Services affected**: Chat Orchestrator (log full pipeline), Admin Service (query endpoint)

---

## Tier 3 — Bonus Polish

### 11. Multilingual (Kannada/Hindi)

**What**: Ask in Kannada or Hindi, get answer in the same language.

**How**: Groq/Llama handles translation natively. Add one line to the system prompt:

```
"If the user asks in a non-English language, respond in that same language."
```

**Effort**: ~5 minutes. High demo value for a Karnataka-based university.

---

### 12. Voice Input

**What**: Click mic button, speak question, get text answer.

**How**: Browser's built-in Web Speech API (free, no backend changes).

**Effort**: ~20 lines of frontend JavaScript. No backend changes.

---

### 13. PDF Export

**What**: "Export this conversation as PDF" button.

**How**: Frontend generates PDF using jsPDF or similar library.

**Effort**: Frontend only. No backend changes.

---

## Implementation Priority

```
Week 1:  Streaming (SSE) + Cache-Hit Indicator + Feedback
         These are the fastest to implement and most visible in a demo.

Week 2:  Circuit Breaker + Semantic Cache
         These show distributed systems depth.

Week 3:  Distributed Tracing (Jaeger) + Grafana Dashboard
         These make the system observable and demo-ready.

Week 4:  Load Test + Auto-Scaling + Request Replay + A/B Testing
         These are the "wow" features for the final demo.

Bonus:   Multilingual + Voice + PDF Export
         Add if time permits. Low effort, high polish.
```

---

## What to Say During Demo

```
"We built a RAG chatbot with 6 microservices running on Kubernetes.
 But what makes it production-grade is:

 1. Responses stream in real-time, like ChatGPT         [show streaming]
 2. We can trace any request across all services         [open Jaeger]
 3. We monitor everything live                           [open Grafana]
 4. If the AI service goes down, it degrades gracefully  [kill Groq, show fallback]
 5. It caches by meaning, not just exact match           [ask similar question, show cache hit]
 6. It auto-scales under load                            [run Locust, show pods scaling]
 7. Users give feedback, we track quality                [show analytics]
 8. We A/B test our prompts to find the best one         [show comparison chart]"
```
