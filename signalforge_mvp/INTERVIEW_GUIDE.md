# SignalForge — Interview Explanation Guide

How to explain SignalForge in 30 seconds, 2 minutes, 5 minutes, or 30 minutes.

---

## 30-Second Elevator Pitch (Recruiter Screen)

> "I built SignalForge, a production-ready incident management platform for
> microservices. It ingests telemetry events, detects anomalies using rolling
> window analysis, creates incidents with structured evidence, and provides a
> React dashboard for triage and root-cause analysis. 57 tests, load-tested at
> 47 RPS, Dockerized full stack, AWS architecture documented. Think of it as
> PagerDuty + DataDog + an AI assistant, built in 30 days."

**Why this works:** Mentions the domain (incident management), the key features
(ingest, detect, incident, dashboard), the numbers (57 tests, 47 RPS), and the
deployment story (Docker, AWS). Ends with a memorable comparison.

---

## 2-Minute Introduction (Hiring Manager)

> "SignalForge is an incident management platform I built for microservices. The
> problem is that when a service fails, engineers spend 30+ minutes piecing
> together logs, metrics, and traces from different tools. SignalForge automates
> that.
>
> Here's how it works: a simulator generates realistic traffic — metrics, logs,
> traces, and deployments. The FastAPI backend accepts events in ~15ms and
> publishes them to Kafka for async processing. A worker consumer reads the
> events, stores them in PostgreSQL, pushes them to a Redis rolling window, and
> runs anomaly detection. If error rate exceeds 50% or p95 latency exceeds
> 2500ms, it creates an incident with structured evidence and broadcasts it
> via WebSocket to the React dashboard.
>
> The dashboard shows incidents in real time, a service dependency graph, and
> runbooks for remediation. The root cause engine scores hypotheses across 5
> dimensions — deployment recency, anomaly severity, log errors, trace failures,
> and runbook coverage. An AI triage assistant suggests actions based on the
> evidence.
>
> It's 57 tests, load-tested at 47 RPS, and deployable to AWS via Docker
> Compose or ECS Fargate. The full architecture is documented with Terraform
> modules and a CI/CD pipeline."

**Why this works:** Tells a problem-solution story. Mentions the key
components by name. Includes numbers. Ends with deployment credibility.

---

## 5-Minute Technical Deep Dive (Engineering Interview)

### The Architecture

> "SignalForge separates three concerns: durable storage, hot operational state,
> and event streaming. PostgreSQL is the source of truth — all events,
> incidents, runbooks, and embeddings live there. Redis holds rolling windows
> of the last 50 events per service with a 1-hour TTL — this is hot state for
> sub-millisecond anomaly detection. Kafka handles async ingestion — the API
> returns 202 Accepted in milliseconds, and worker processors handle the heavy
> pipeline independently.
>
> If any layer fails, the system degrades gracefully. Kafka down? The API falls
> back to sync processing. Redis down? Anomaly detection reads from PostgreSQL
> instead. PostgreSQL down? The system can't store data — that's the only hard
> dependency."

### The Data Flow

> "Let me walk through one event end-to-end. The simulator sends a metric event:
> `notification-service`, `status_code=500`, `latency_ms=2000`. The API validates
> the payload, extracts the tenant from the `X-API-Key` header, overrides the
> payload tenant_id to prevent cross-tenant injection, publishes to Kafka, and
> returns 202 Accepted in ~15ms.
>
> The consumer worker pulls the event, calls `EventProcessor.process()`. This
> stores the event in PostgreSQL (durable), pushes it to Redis (hot state), and
> runs anomaly detection. The detector reads the rolling window — 21 events, 20
> errors, 95% error rate, 2000ms average latency. It flags **critical** because
> error rate exceeds 50%.
>
> The incident engine creates an incident with three timeline entries: 'incident
> opened after anomaly detection', 'attached rolling window context from 21
> events', and 'recent deployment detected: notification-service v2.1.0'. It
> broadcasts via WebSocket. The dashboard flashes the new incident card in real
> time."

### The Demo

> "I have a deterministic seed script that creates this exact story in 2 seconds.
> Run it, start the backend, and the dashboard shows the incident immediately.
> The incident has structured evidence, deployment correlation, and a service
> graph showing checkout-service depends on notification-service. The root cause
> score is 85 out of 100. The runbook says 'check deployment history, verify
> connection pool, restart pods, check queue depth, roll back if needed.' The AI
> triage suggests the same actions with a confidence score of 'high.'"

### Why These Technologies

> **Why FastAPI?** "Async-native, Pydantic for validation, automatic OpenAPI docs.
> The ingest endpoint returns 202 Accepted for async mode — this is important
> because the API should never block on processing."
>
> **Why Kafka?** "Decouples the API from the processing pipeline. With Kafka, I
> can add more worker consumers to scale throughput. Without it, the API is both
> accepting events and processing them — backpressure hits the client."
>
> **Why Redis?** "Rolling window queries need to be sub-millisecond. PostgreSQL
> can do it, but Redis LPUSH/LTRIM/LRANGE is O(1) for a fixed-size window. This
> matters because anomaly detection runs after every event."
>
> **Why PostgreSQL?** "Durable storage, ACID transactions, Alembic migrations
> for schema versioning, and pgvector for semantic search. SQLite is the dev
> fallback — zero setup."
>
> **Why React + TanStack Query?** "TanStack Query handles caching, refetching,
> and loading states. No useEffect spaghetti. The dashboard polls every 3 seconds
> and updates automatically when new data arrives."

### Testing

> "57 tests covering: anomaly detection thresholds, event processor pipeline,
> incident lifecycle, end-to-end ingest-to-incident flow, service graph from
> trace events, runbook CRUD, keyword search, auth, and health checks. All pass
> in under 2 seconds using an in-memory SQLite database. The tests reset the
> database between each test."

### Load Testing

> "I measured 47.7 RPS on a single-process uvicorn with SQLite. The bottleneck
> is SQLite's single-writer lock — at 50 concurrent writers, p99 latency jumps to
> 3.3 seconds and 0.4% of requests fail. PostgreSQL eliminates this. My
> estimate is 500+ RPS on the same hardware with PostgreSQL. The upgrade path
> is documented: 8 independent steps from PostgreSQL to async SQLAlchemy to
> 10,000+ RPS."

---

## 15-Minute System Design Deep Dive (Senior/Staff Interview)

### The Three-Layer Consistency Model

> "SignalForge uses three layers with different consistency guarantees.
> PostgreSQL is strongly consistent — every event is stored transactionally.
> Redis is eventually consistent — the rolling window is a cache that rebuilds
> from PostgreSQL if lost. Kafka is at-least-once delivery — the consumer
> worker idempotently processes events using event_id deduplication.
>
> This design is intentional. Strong consistency is expensive. You only need it
> for the source of truth. Hot state can be rebuilt. Event streaming can retry."

### Backpressure and Horizontal Scaling

> "With Kafka, backpressure is handled by the queue. If workers slow down, the
> queue grows. The consumer group rebalances partitions across workers. Adding
> a worker is one configuration change — no code changes.
>
> Without Kafka, the API processes events synchronously. Backpressure means the
> API blocks. This is the fallback mode, not the production mode."

### Tenant Isolation

> "Every API endpoint except `/health` requires an `X-API-Key` header. The auth
> dependency maps the key to a tenant_id. The ingest endpoint overrides the
> payload tenant_id with the authenticated tenant — this prevents cross-tenant
> data injection. Every storage query filters by tenant_id when provided. This
> is defense in depth: even if a router forgets the check, the storage layer
> enforces the boundary."

### Rate Limiting and Security

> "The ingest endpoint is rate-limited at 100 RPS per IP using a sliding window.
> In production, I'd replace this with Redis-backed rate limiting so the limit
> is shared across all backend instances. The API never leaks stack traces —
> in production, a 500 error returns 'An unexpected error occurred.' The full
> stack trace is logged server-side with a request_id for tracing."

### Database Schema and Migrations

> "Schema changes are managed with Alembic. Every migration is committed to git
> and runs automatically when the backend container starts. This guarantees
> every environment — local, staging, production — has the same schema. I have
> migrations for events, incidents, runbooks, and embeddings tables."

### WebSocket and Real-Time Updates

> "The WebSocket endpoint uses Redis pub/sub for broadcast. When an incident is
> created, the incident engine publishes to the `incident_events` channel. The
> WebSocket handler subscribes to this channel and pushes updates to all
> connected clients. This decouples the incident engine from the WebSocket
> handler — they don't need to know about each other."

### AI Triage Design

> "The AI triage is NOT a black box. It reads the evidence the system already
> collected — anomaly stats, deployment correlation, rolling window context — and
> produces structured output: summary, likely causes, evidence points, suggested
> actions, confidence score. If OpenAI is unavailable, it falls back to a
> deterministic mock provider that produces the same structured output. This means
> the AI is an augmentation, not a replacement, for the root-cause engine."

### Semantic Search

> "I use pgvector for semantic search. When an incident or runbook is created,
> the system generates an embedding vector and stores it in the embeddings
> table. When a user searches, the query is converted to an embedding and matched
> using cosine similarity. If OpenAI is unavailable, the system falls back to
> keyword search. This is operational memory — past incidents and how to fix
> them, linked by concept, not just by keyword."

### AWS Deployment Architecture

> "For production, I'd deploy to AWS with ECS Fargate for the backend (3-20
> tasks, autoscaling), CloudFront + S3 for the frontend, RDS PostgreSQL
> Multi-AZ for storage, ElastiCache Redis Cluster for hot state, MSK for managed
> Kafka, ALB for SSL and path routing, Secrets Manager for credentials, and
> CloudWatch for logs and metrics. The full spec is documented with Terraform
> module structure and a CI/CD pipeline."

### Cost and Scaling

> "Dev stack is ~$130/month. Prod is ~$400/month. The bottleneck is SQLite in
> local dev — switching to PostgreSQL gets 500+ RPS. ECS Fargate scales to 20
> tasks. RDS read replicas offload GET queries. ElastiCache cluster mode adds
> shards. MSK Serverless auto-scales partitions. Each step is independent. Target
> is 10,000+ RPS."

---

## 30-Minute Live Demo (On-Site or Final Round)

### Setup (1 minute)

> "Let me show you the demo. I'll run the seed script — it creates a complete
> incident story in 2 seconds. Then I'll start the backend and query the API."

Run: `cd backend && .venv\Scripts\python.exe ..\scripts\seed_demo.py`

### Step 1: Show the incident (1 minute)

> "The seed script created 50 events: 20 healthy, 1 deployment, 20 bad events
> for notification-service, 10 trace failures, 10 cascading failures for
> checkout-service, and 5 error logs. The result is one critical incident."

Query: `curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/incidents`

> "The incident has three timeline entries: incident opened, rolling window
> context attached, and deployment correlated. The evidence shows 21 events
> sampled, 20 errors, 95% error rate, 2000ms average latency."

### Step 2: Show the service graph (1 minute)

> "The service graph shows the dependency chain. checkout-service calls
> payment-service, inventory-service, and notification-service. When
> notification-service fails, checkout-service cascades."

Query: `curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/graph`

### Step 3: Show the root cause (1 minute)

> "The root cause engine scores 5 dimensions. For notification-service, the
> score is 85 out of 100. The evidence includes the recent deployment, critical
> error rate, failed traces, and the existence of a runbook."

Query: `curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/services/notification-service/root-cause`

### Step 4: Show the runbook (1 minute)

> "The runbook for notification-service has 5 steps: check deployment history,
> verify database connection pool, restart pods, check queue depth, and roll
> back to the last known good version. The first step is already done
> automatically — the system correlated the deployment."

Query: `curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/runbooks`

### Step 5: Show the AI triage (1 minute)

> "The AI triage reads the same evidence and produces a structured analysis.
> It suggests rolling back the deployment, checking the connection pool, and
> verifying checkout-service health after recovery."

Query: `curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/incidents/{id}/ai-triage`

### Step 6: Show the search (1 minute)

> "Searching for 'notification' returns both the incident and the runbook in
> one result set. This is operational memory — past incidents and how to fix
> them, linked together."

Query: `curl -H "X-API-Key: sf-api-key-demo" "http://localhost:8000/search?q=notification"`

### Closing (1 minute)

> "The entire pipeline is automatic: event ingestion, anomaly detection,
> incident creation, evidence gathering, root cause ranking, and operational
> memory retrieval. The engineer just has to read the incident and follow the
> runbook. The system detected the anomaly in under 1 second, created the
> incident with structured evidence, correlated the deployment, showed the
> dependency graph, and surfaced the remediation steps."

---

## Common Interview Questions and Answers

### Q: Why not use an existing tool like PagerDuty or DataDog?

> "PagerDuty is great for alerting and on-call management, but it doesn't
> automatically correlate deployments with incidents or score root causes across
> multiple dimensions. DataDog is great for metrics and traces, but it doesn't
> create structured incidents with remediation runbooks. SignalForge combines
> the detection pipeline, the incident creation, the root cause analysis, and
> the operational memory in one system. Also, I built it to show I can design and
> implement a full production system from scratch."

### Q: How would you handle a million events per second?

> "At that scale, I'd need to change several things. First, replace Kafka with
> a higher-throughput streaming system or add more partitions and consumers.
> Second, shard PostgreSQL by tenant_id. Third, use Redis Cluster for hot state.
> Fourth, add a dedicated anomaly detection service that reads from Kafka and
> writes to a separate incident stream. Fifth, use a time-series database like
> ClickHouse or TimescaleDB for metrics, and only store anomalies in
> PostgreSQL. The current architecture is designed to scale incrementally —
> each layer can be upgraded independently."

### Q: What if the AI gives wrong triage advice?

> "The AI is augmentation, not authority. The root-cause engine produces a
> deterministic score with traceable evidence. The AI triage reads that evidence
> and suggests actions. The engineer always sees the evidence and the score
> before the AI suggestion. If the AI is wrong, the engineer can follow the
> runbook instead. Also, the system falls back to a deterministic mock
> provider if OpenAI is unavailable — the AI is optional."

### Q: How do you prevent alert fatigue?

> "The anomaly detector uses thresholds, not every error. It needs 20 events
> before making a decision. It only creates incidents for warning or critical
> severity, not info. Resolved incidents allow new incidents, but mitigated
> incidents block duplicates. This means once an engineer marks an incident as
> mitigated, the system won't spam them with the same alert. The root cause
> engine also suppresses low-confidence hypotheses — only scores above a
> threshold are shown."

### Q: Why Python for the backend?

> "Python has the best ecosystem for data processing and AI integration. FastAPI
> is the fastest Python web framework. SQLAlchemy is the most mature ORM. The
> Kafka and Redis clients are well-maintained. For a system that needs anomaly
> detection, AI triage, and embedding generation, Python is the right choice. If
> I needed microsecond latency, I'd add a Rust or Go service for the hot path.
> But for this system, Python is fast enough — the bottleneck is the database,
> not the language."

### Q: What's the hardest part you built?

> "The decoupled ingestion architecture. Getting the API to return 202 Accepted
> while the worker processes asynchronously requires careful handling of failures.
> If the worker fails after 3 retries, the event goes to a dead-letter topic. If
> Kafka is down, the API falls back to sync processing. If Redis is down,
> anomaly detection reads from PostgreSQL. Each fallback path has to produce
> the same result. I tested all of this with 57 integration tests."

### Q: What would you do differently?

> "I'd add distributed tracing with OpenTelemetry from day one. I'd also use
> async SQLAlchemy (`sqlalchemy[asyncio]` + `asyncpg`) instead of sync sessions
> — this is the biggest remaining bottleneck. I'd add a proper event sourcing
> pattern for the incident timeline instead of storing it as JSON. And I'd
> build the frontend with Next.js instead of Vite for server-side rendering and
> better SEO. But those are all upgrades — the current system is production-ready
> as-is."

---

## One-Page Cheat Sheet (Bring to Interview)

| Metric | Number |
|--------|--------|
| Development time | 30 days |
| Tests | 57, all passing |
| Test runtime | <2 seconds |
| Ingest throughput | 47.7 RPS |
| Ingest p95 latency | 380 ms |
| API read latency | 13-17 ms |
| Incident detection delay | 784 ms |
| Backend modules | 40+ |
| Docker services | 6 |
| AWS services | 7 |
| Dev cost | $130/month |
| Prod cost | $400/month |

| Key Feature | Technology |
|-------------|------------|
| Async ingestion | Kafka/Redpanda + 202 Accepted |
| Hot state | Redis rolling window (50 events, 1h TTL) |
| Anomaly detection | Rule-based thresholds (20 samples, 50% error rate) |
| Incident evidence | Structured JSON with timeline |
| Root cause | 5-dimension scoring (0-100) |
| AI triage | OpenAI structured output + mock fallback |
| Semantic search | pgvector cosine similarity |
| Auth | API key + tenant isolation |
| Rate limiting | 100 RPS sliding window |
| Deployment | Docker Compose + ECS Fargate |

