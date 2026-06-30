# SignalForge

**Production-ready incident management platform for microservices**

Built in 31 days. FastAPI + React + PostgreSQL + Redis + Kafka. 57 tests. Load-tested at 47.7 RPS.

---

SignalForge ingests telemetry events (metrics, logs, traces, deployments), detects anomalies using rolling-window analysis, creates incidents with structured evidence, and provides a React dashboard for triage, root-cause analysis, and operational memory.

> **Demo ready:** See [`DEMO.md`](DEMO.md) for a 5-minute walkthrough with seed data and talking points.
> **Interview prep:** See [`INTERVIEW_GUIDE.md`](INTERVIEW_GUIDE.md) for explanation from 30-second pitch to FAANG-level deep dive.
> **Quick reference:** See [`ARCHITECTURE_SUMMARY.md`](ARCHITECTURE_SUMMARY.md) for one-page architecture overview.

**What makes it different:** Every architectural decision has a clear justification. No magic — just production patterns applied to a focused domain.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Traffic Simulator                            │
│  (5 services: checkout, payment, inventory, fraud, notification)       │
│  Sends: metrics, logs, traces, deployments                              │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              API (FastAPI)                                │
│  POST /ingest → validates → publishes to Kafka (202 Accepted)           │
│  OR sync fallback (200 OK) when Kafka is down                             │
│  Auth: X-API-Key header → tenant isolation enforced on every query      │
│  Rate limit: 100 RPS per IP (sliding window)                             │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
                    ▼                                   ▼
        ┌──────────────────┐                  ┌──────────────────┐
        │  Kafka/Redpanda  │                  │  Sync Fallback   │
        │  (telemetry)     │                  │  (Kafka down)    │
        │  Buffer: 7 days   │                  │  Inline processing│
        └────────┬─────────┘                  └────────┬─────────┘
                 │                                    │
                 ▼                                    │
        ┌──────────────────┐                         │
        │  Consumer Worker │                         │
        │  (background)    │◄────────────────────────┘
        │  Retry 3x, then  │
        │  dead-letter     │
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────────────┐
        │              EventProcessor (owned by worker)     │
        │  1. Store in PostgreSQL (durable source of truth) │
        │  2. Push to Redis rolling window (hot state)       │
        │  3. Run anomaly detection on rolling window          │
        │  4. Create incident if unhealthy                   │
        │  5. Broadcast via WebSocket                        │
        └──────────────────────────────────────────────────┘
                 │
        ┌────────┴────────┬──────────────┐
        │                 │              │
        ▼                 ▼              ▼
  ┌──────────┐    ┌──────────┐   ┌──────────────┐
  │ PostgreSQL│    │  Redis   │   │  WebSocket   │
  │ (events, │    │ (rolling │   │  (live UI     │
  │ incidents,│   │  window, │   │   updates)    │
  │ runbooks) │   │  pub/sub)│   └──────────────┘
  └──────────┘    └──────────┘
        │
        ▼
  ┌────────────────────────────────────────┐
  │            React Dashboard (Vite)        │
  │  Incidents | Service Graph | Runbooks     │
  │  Root Cause | AI Triage | Search       │
  └────────────────────────────────────────┘
```

**Data flow (one event, end-to-end):**

1. **Simulator** sends a `metric` event: `checkout-service`, `status_code=500`, `latency_ms=1800`
2. **API** validates the payload, extracts tenant from `X-API-Key`, overrides `tenant_id` (prevents injection), publishes to Kafka, returns `202 Accepted` in ~15ms
3. **Consumer worker** pulls the event from the topic, calls `EventProcessor.process()`
4. **EventProcessor** stores the event in PostgreSQL (durable), pushes it to Redis rolling window (last 50 events per service, 1h TTL)
5. **Anomaly detector** reads the rolling window from Redis (sub-millisecond), computes error rate and p95 latency. If 20+ events and error rate ≥ 50%, flags **critical**
6. **Incident engine** creates an incident with structured evidence (sample count, error count, error rate, avg latency, p95 latency, breached thresholds). Appends to timeline. Broadcasts via WebSocket. Stores embedding for semantic search.
7. **Dashboard** receives the WebSocket update and flashes the new incident card in real time. The engineer clicks it, sees root-cause analysis, and finds the related runbook.

---

## Quick Start (Docker Compose — Full Stack)

> **Prerequisite:** Docker Desktop installed and running.

```powershell
cd signalforge_mvp

# Start everything: PostgreSQL, Redis, Redpanda, Backend, Frontend
docker-compose up -d

# Wait ~30 seconds for health checks, then verify
docker-compose ps

# Generate realistic traffic (one-off task, 100 events)
docker-compose --profile simulator up simulator
```

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Durable storage |
| Redis | 6379 | Hot state: rolling windows, pub/sub |
| Redpanda (Kafka) | 9092 | Async event streaming |
| Backend API | 8000 | FastAPI + all endpoints |
| Frontend | 80 | React dashboard via nginx |

**Open the dashboard:** `http://localhost`

**API docs:** `http://localhost:8000/docs`

**Health check:** `http://localhost:8000/health`

Stop: `docker-compose down` (add `-v` to wipe data)

---

## Docker Compose with Auto-Discovery

The backend container automatically discovers other services in the same Docker network when `SIGNALFORGE_DISCOVERY_ENABLED=true`.

**What gets discovered:**
- Other containers with `healthcheck` or `com.signforge.service` labels
- Host processes (when `pid: host` is enabled — local dev only)
- Static config files mounted at `/app/config.yaml`

**Verify discovery is working:**
```powershell
# Check discovered services via the API
docker exec signforge-backend curl -s http://localhost:8000/services/discovered

# Or from your host
curl http://localhost:8000/services/discovered
```

**Local development override:**
`docker-compose.override.yml` is automatically picked up by `docker-compose up` when present. It mounts the backend source code for live reloading and disables the nginx frontend container (use `npm run dev` in `./frontend` instead).

```powershell
# Dev mode: hot reload on backend code changes
cd signalforge_mvp
docker-compose up -d          # backend, postgres, redis, redpanda
# In another terminal:
cd backend && uvicorn app.main:app --reload
# In another terminal:
cd frontend && npm run dev
```

**Production override:**
`docker-compose.prod.yml` adds resource limits, read-only filesystems, and disables process discovery (only `config` provider).

```powershell
# Production mode
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Demo Walkthrough

**What to do and what you'll see:**

1. **Start the stack:** `docker-compose up -d` — all 5 services start, migrations run automatically, Kafka consumer worker starts in background
2. **Check health:** `curl http://localhost:8000/health` → `{"status":"ok","dependencies":{"database":"available","redis":"available","kafka":"available"}}`
3. **Generate traffic:** `docker-compose --profile simulator up simulator` — 100 events from 5 services, mix of healthy (200ms, 200 OK) and failing (500, 1500ms+ latency)
4. **Open dashboard:** `http://localhost` — you'll see a "Live Service Incidents" feed. Within 5-10 seconds, an incident appears for `checkout-service` (red, critical severity)
5. **Click the incident:** Opens detail panel with timeline, evidence, and root-cause panel. Root cause shows deployment correlation (if a deployment happened within 30 min), anomaly stats, and service graph
6. **Check runbooks:** Click "Runbooks" tab — create a runbook for `checkout-service`: "Check payment-service health, verify inventory-service connectivity, escalate if p95 > 2000ms"
7. **Search:** Click "Search" tab, type "checkout" — returns both the incident and the runbook
8. **Resolve the incident:** In the detail panel, click "Resolved" — status updates, timeline appends entry, dashboard refreshes. Start simulator again and a new incident appears (resolved allows new, mitigated blocks duplicates)

**What to say in an interview:** "I built the entire pipeline. The simulator generates realistic traffic. The API accepts events in milliseconds. The worker processes them asynchronously. Anomaly detection runs on rolling windows. Incidents are created with structured evidence. The dashboard shows everything in real time."

---

## Design Tradeoffs

| Decision | What I chose | Why |
|----------|-------------|-----|
| **Database** | PostgreSQL (primary) + SQLite (fallback) | PostgreSQL for concurrent writes and pgvector. SQLite for local dev with zero setup. |
| **Hot state** | Redis rolling window | Sub-millisecond reads for anomaly detection. Falls back to PostgreSQL if Redis is down. |
| **Event streaming** | Kafka (Redpanda) | Decouples API from processing. Enables backpressure and horizontal scaling. Falls back to sync processing. |
| **API framework** | FastAPI + Pydantic | Async-native, automatic OpenAPI docs, strict validation. 202 Accepted for async, 200 for sync fallback. |
| **Frontend** | React + TanStack Query + Vite | TanStack Query handles caching, refetching, loading states. No useEffect spaghetti. |
| **Anomaly detection** | Rule-based thresholds | Explainable, deterministic, no training data needed. Thresholds are configurable per-tenant in the future. |
| **Root cause** | Rule-based scoring (5 dimensions) | No LLM required. Scores deployment recency, anomaly severity, log errors, trace failures, runbook coverage. |
| **AI triage** | LLM augmentation (OpenAI → mock fallback) | LLM analyzes the evidence we already collected. Not a black box — structured output with confidence scores. Falls back to deterministic mock provider. |
| **Auth** | API key (X-API-Key header) | Simpler than JWT for an MVP. Tenant isolation enforced at storage layer. Swappable for OAuth2 without changing routers. |
| **Rate limiting** | In-memory sliding window | 100 RPS per IP, zero external dependency. Upgrade path: Redis-backed rate limiter for multi-instance. |
| **Logging** | Structured key=value format | Queryable by `event_id=xyz` or `request_id=abc`. JSON-ready for CloudWatch/ELK. No stack traces in production. |
| **Health checks** | Deep dependency checks | Not just "process running" — checks DB connectivity, Redis, Kafka. Returns "degraded" if DB is down. |
| **Deployment** | Docker Compose (local) + ECS Fargate (AWS) | Local: one command starts everything. AWS: serverless containers, no EC2 management. |

---

## Scalability

**Current numbers (measured on SQLite, single-process uvicorn, Windows laptop):**

| Metric | Value |
|--------|-------|
| Ingest throughput (20 concurrent, 10s) | **47.7 RPS** |
| Ingest p95 latency | **380 ms** |
| Ingest errors (20 concurrent) | **0** |
| API read latency (all endpoints) | **avg 13–17 ms, p95 16–28 ms** |
| Incident detection delay (20 bad events) | **784 ms** |

**Bottleneck identified:** SQLite single-writer lock. At 50 concurrent writers, p99 latency jumps to 3.3s and 0.4% fail with "database is locked." PostgreSQL eliminates this bottleneck.

**Upgrade path to production scale:**

| Step | Change | Expected impact |
|------|--------|-----------------|
| 1. Switch to PostgreSQL | Docker Compose already provides it | **500+ RPS** on same hardware (connection pooling, row-level locking) |
| 2. Add ECS Fargate tasks | 3 → 20 tasks, target tracking on CPU | Linear throughput scaling |
| 3. Redis cluster mode | ElastiCache with 3 shards | Rolling window queries stay sub-millisecond |
| 4. Kafka partitions | More partitions = more parallel consumers | Horizontal scaling of worker processors |
| 5. Read replicas | RDS read replicas for GET endpoints | Dashboard and search queries offloaded |
| 6. API response caching | CloudFront for static assets, Redis for `/incidents` | Sub-10ms for cached reads |
| 7. Connection pooling | RDS Proxy or PgBouncer | 1000+ concurrent DB connections |
| 8. Async SQLAlchemy | Migrate sync sessions to `sqlalchemy[asyncio]` + `asyncpg` | Eliminates event-loop blocking |

**Target: 10,000+ RPS** with the above changes. Each step is independent — no big-bang migration required.

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Backend API | FastAPI + Pydantic + Uvicorn | HTTP API, validation, async handlers |
| Database | PostgreSQL 16 / SQLite 3 | Durable storage, Alembic migrations, pgvector |
| Hot State | Redis 7 | Rolling windows, pub/sub, TTL auto-cleanup |
| Event Streaming | Kafka (Redpanda) | Async ingestion, consumer groups, dead-letter |
| Frontend | React 18 + TypeScript + Vite + TanStack Query | Dashboard, real-time updates, caching |
| Frontend Server | Nginx 1.25 | Static serving, gzip, SPA routing, API proxy |
| AI / Embeddings | OpenAI API / sentence-transformers / None | Structured triage, semantic search fallback |
| Auth | Custom API key dependency | Tenant isolation, 401 on missing/invalid key |
| Testing | pytest + FastAPI TestClient | 57 tests: unit, integration, auth, load |
| Load Testing | Locust + custom orchestrator | 47.7 RPS measured, bottleneck identified |
| Local Dev | Docker Compose | One command: PostgreSQL + Redis + Redpanda + Backend + Frontend |
| Cloud Deployment | ECS Fargate + RDS + ElastiCache + MSK + ALB + CloudFront | See `AWS_ARCHITECTURE.md` for full spec |

---

## Project Structure

```text
signalforge_mvp/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI factory, middleware, router registration
│   │   ├── config.py                   # Centralized env vars (no os.environ scattered)
│   │   ├── logging_config.py           # Structured logging with key=value format
│   │   ├── database.py                 # SQLAlchemy engine + session
│   │   ├── models.py                   # SQLAlchemy tables (events, incidents, runbooks, embeddings)
│   │   ├── schemas.py                  # Pydantic request/response models
│   │   ├── storage.py                  # DB access layer with tenant isolation
│   │   ├── redis_client.py             # Redis rolling windows + pub/sub
│   │   ├── kafka_client.py             # Producer + consumer with retry + dead-letter
│   │   ├── anomaly.py                  # Rolling-window anomaly detection
│   │   ├── incident_engine.py          # Incident creation + timeline + WebSocket broadcast
│   │   ├── root_cause_engine.py        # 5-dimension rule-based scoring
│   │   ├── ai_triage.py                # OpenAI / mock structured triage
│   │   ├── embeddings.py               # OpenAI → local model → None fallback
│   │   ├── auth.py                     # API key → tenant_id dependency
│   │   ├── middleware/
│   │   │   ├── rate_limit.py           # Sliding-window rate limiter (100 RPS)
│   │   │   ├── request_logging.py      # Request tracing with X-Request-Id
│   │   │   └── error_handler.py        # Safe 500s (no stack traces in production)
│   │   └── routers/
│   │       ├── health.py               # Deep health: DB + Redis + Kafka
│   │       ├── ingest.py               # POST /ingest — 202 Accepted, rate limited, auth
│   │       ├── events.py               # GET /events
│   │       ├── incidents.py            # GET /incidents, GET /incidents/{id}, PATCH /status
│   │       ├── graph.py                # GET /graph — service dependency graph
│   │       ├── deployments.py          # GET /deployments
│   │       ├── runbooks.py             # CRUD /runbooks
│   │       ├── search.py               # GET /search — keyword + semantic
│   │       ├── root_cause.py           # GET /services/{name}/root-cause
│   │       ├── ai_triage.py            # GET /incidents/{id}/ai-triage
│   │       └── websocket.py            # /ws/incidents — live updates
│   │   └── services/
│   │       ├── event_processor.py      # Worker-owned pipeline: store → detect → incident
│   │       ├── telemetry_service.py    # Query orchestration + sync fallback wrapper
│   │       └── kafka_consumer_worker.py # Background consumer: retries, dead-letter
│   ├── tests/
│   │   ├── conftest.py                 # TestClient with auth headers, reset fixtures
│   │   ├── test_anomaly.py             # 8 tests: thresholds
│   │   ├── test_event_processor.py     # 6 tests: pipeline stages
│   │   ├── test_incidents.py           # 6 tests: lifecycle
│   │   ├── test_auth.py                # 3 tests: 401/200
│   │   ├── test_integration_ingest.py  # 10 tests: end-to-end
│   │   ├── test_integration_graph.py   # 4 tests: trace → graph
│   │   ├── test_integration_runbooks.py # 12 tests: CRUD + search
│   │   ├── test_integration_search.py  # 6 tests: keyword + health
│   │   └── load/
│   │       ├── locustfile.py           # Locust load test
│   │       ├── run_load_tests.py       # Orchestrator: start, measure, report JSON
│   │       └── debug_detection.py      # Isolated detection delay test
│   ├── alembic/                        # Database migrations
│   ├── Dockerfile                      # Python 3.12 multi-stage build
│   ├── .dockerignore                   # Excludes venv, cache, .env, local DB
│   ├── requirements.txt                # FastAPI, SQLAlchemy, Redis, Kafka, pytest, httpx
│   └── .env.example                    # Environment variable template
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx                     # Dashboard: tabs, cards, detail, search
│   │   ├── api.ts                      # Typed fetch with ApiError, auth header, retry
│   │   ├── types.ts                    # TypeScript interfaces matching Pydantic schemas
│   │   ├── components/
│   │   │   ├── RunbookPanel.tsx        # Runbook CRUD form + list
│   │   │   └── ServiceGraph.tsx        # D3 force-directed graph
│   │   └── main.tsx                    # React entry + QueryClientProvider
│   ├── Dockerfile                      # Node build → nginx serve
│   ├── nginx.conf                      # Gzip, cache, SPA routing, /api/* proxy
│   ├── .dockerignore                   # Excludes node_modules, dist, .env
│   ├── package.json                    # React 18, Vite, TanStack Query, D3
│   └── tsconfig.json                   # Strict TypeScript, no implicit any
│
├── simulator/
│   ├── traffic_simulator.py            # 5-service microservice traffic generator
│   ├── Dockerfile                      # Python 3.12 slim
│   └── .dockerignore                   # Excludes cache, .env
│
├── docker-compose.yml                  # Full stack: PostgreSQL + Redis + Redpanda + Backend + Frontend + Simulator
├── docker-compose.override.yml         # Local dev: live reload, hot restart, Vite HMR
├── docker-compose.prod.yml             # Production: resource limits, read-only, security hardening
├── Dockerfile.discovery                # Standalone discovery agent (placeholder)
├── AWS_ARCHITECTURE.md                 # Complete AWS deployment spec (ECS, RDS, ElastiCache, MSK, ALB, CloudFront, Terraform, CI/CD)
├── PROJECT_STATE.md                    # Architecture decisions, file inventory, test counts, known bugs, next steps
└── README.md                           # This file
```

---

## Testing

```powershell
cd signalforge_mvp\backend
.venv\Scripts\python.exe -m pytest tests -v
```

**57 tests, 1.46 seconds, all passing:**
- 8 anomaly detection tests (thresholds: healthy, warning, critical)
- 6 event processor tests (pipeline, duplicates, DB + Redis)
- 6 incident lifecycle tests (create, resolve, mitigated, status update, deduplication)
- 3 auth tests (missing key → 401, invalid key → 401, valid key → 200)
- 10 integration ingest tests (end-to-end: ingest → incident → status update)
- 4 integration graph tests (trace events → nodes + edges)
- 12 integration runbook tests (CRUD + search by title, description, service)
- 6 integration search tests (keyword search + mixed results + health check)
- 2 load test scripts (measured throughput, detection delay, API latency)

---

## Load Testing

```powershell
cd signalforge_mvp\backend
.venv\Scripts\python.exe tests\load\run_load_tests.py
```

Measures:
- Ingest throughput (RPS, avg/p95/p99 latency, errors)
- API read latency (all endpoints, 10 samples each)
- Incident detection delay (time from first bad event to incident creation)

Results saved to `tests/load/load_test_results.json`.

**Measured results (SQLite backend, single-process uvicorn, Windows laptop):**

| Metric | Value |
|--------|-------|
| Ingest throughput (20 concurrent, 10s) | **47.7 RPS** |
| Ingest avg latency | 155 ms |
| Ingest p95 latency | 380 ms |
| Ingest p99 latency | 522 ms |
| Ingest errors (20 concurrent) | **0** |
| Ingest throughput (50 concurrent, 1000 requests) | **74.8 RPS** |
| Ingest p99 latency (50 concurrent) | **3,361 ms** |
| Ingest errors (50 concurrent) | 4 (0.4%) |
| API read latency (all endpoints) | avg 13–17 ms, p95 16–28 ms |
| Incident detection delay (20 bad events) | **784 ms** |

**Bottleneck:** SQLite is the limiting factor. At 50 concurrent writers, p99 latency jumps to 3.3s and 0.4% of requests fail with "database is locked." Switching to PostgreSQL (which the Docker Compose stack provides) would eliminate this bottleneck and likely scale to 500+ RPS on the same hardware.

---

## AWS Deployment

See [`AWS_ARCHITECTURE.md`](AWS_ARCHITECTURE.md) for the complete production deployment spec and Terraform modules:
- ECS Fargate or EKS (3-20 tasks, autoscaling)
- RDS PostgreSQL Multi-AZ
- ElastiCache Redis Cluster
- Amazon MSK (managed Kafka)
- ALB with SSL + path routing
- CloudFront CDN
- Secrets Manager
- CloudWatch monitoring + alerting
- Terraform modules in `terraform/modules/signforge/` with EKS and ECS examples

**Estimated cost:** Dev ~$130/month, Prod ~$400/month.

**Deploy with Terraform:**
```bash
cd terraform/examples/eks-complete
terraform init
terraform plan
terraform apply
```

---

## Kubernetes Deployment

Deploy SignalForge on Kubernetes using the Helm chart in `helm/signforge/`.

**Quick install:**
```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace
```

The chart includes:
- SignalForge backend Deployment with init container for Alembic migrations
- Optional PostgreSQL, Redis, and Kafka subcharts (Bitnami)
- RBAC (ClusterRole or Role) for service discovery
- ConfigMap-generated `config.yaml` from `values.yaml`
- ServiceAccount, Ingress (optional), HPA (optional)

**With external PostgreSQL:**
```bash
helm install signforge ./helm/signforge \
  --set postgresql.enabled=false \
  --set env.DATABASE_URL=postgresql://user:pass@host:5432/signforge
```

See `helm/signforge/README.md` for full configuration reference.

---

## Production Deployment Checklist

Before deploying SignalForge to production, verify the following:

| Item | Why | How |
|------|-----|-----|
| **PostgreSQL (not SQLite)** | SQLite cannot handle concurrent writes. PostgreSQL with connection pooling is required for production load. | Use RDS or the PostgreSQL subchart. |
| **Redis enabled** | Rolling window queries must be sub-millisecond. Without Redis, anomaly detection falls back to PostgreSQL SELECTs. | Use ElastiCache or the Redis subchart. |
| **Kafka (optional)** | Enables async ingestion and horizontal scaling of workers. Without Kafka, the API processes events synchronously. | Use MSK or the Kafka subchart. |
| **Disable process discovery** | Scanning host processes from a container is a security risk. In production, use `config` or `kubernetes` providers only. | Set `SIGNALFORGE_DISCOVERY_PROVIDERS=config` or use the Helm chart defaults. |
| **Secrets management** | Database passwords and API keys must not be in source control or environment files. | Use AWS Secrets Manager, Kubernetes Secrets, or HashiCorp Vault. |
| **TLS/SSL** | All external traffic must be encrypted. | Configure ACM certificates on ALB/CloudFront or cert-manager in Kubernetes. |
| **Monitoring** | You need visibility into latency, errors, and resource usage. | CloudWatch, Prometheus + Grafana, or Datadog. |
| **Backups** | Incident data is critical. Losing it means losing operational history. | RDS automated snapshots (7-day retention minimum). |
| **Rate limiting** | Prevents abuse and protects downstream services. | The backend has a built-in 100 RPS limit. Upgrade to Redis-backed for multi-instance. |
| **RBAC / IAM review** | Least-privilege access prevents lateral movement. | Review the IAM roles in `terraform/modules/signforge/modules/iam/`. |
| **Health checks** | Kubernetes and ALB need to know when a pod is unhealthy. | The backend exposes `/health` with deep dependency checks. |
| **Resource limits** | Prevents a single pod from consuming all node resources. | Set CPU and memory requests/limits in Kubernetes or Docker Compose. |
| **Read-only root filesystem** | Reduces attack surface by preventing runtime file modifications. | Enable `read_only: true` in Docker Compose or Kubernetes security context. |

---

## What Makes This Production-Ready

- **Durable storage:** PostgreSQL with Alembic migrations for schema versioning
- **Hot state:** Redis rolling windows for sub-millisecond anomaly detection
- **Event streaming:** Kafka/Redpanda for async, scalable ingestion with backpressure
- **Decoupled processing:** API accepts events in milliseconds; worker processors handle the heavy pipeline independently
- **Graceful degradation:** Every external dependency (Kafka, Redis, OpenAI) has a fallback
- **Real-time updates:** WebSocket for live incident notifications
- **Explainable AI:** Rule-based root-cause scoring with clear evidence per dimension
- **AI augmentation:** LLM triage with structured output, not black-box predictions
- **Semantic memory:** pgvector embeddings for concept search across incidents and runbooks
- **Operational memory:** Runbooks linked to incidents for rapid remediation
- **Containerized:** Docker Compose with health checks and proper startup ordering
- **Tested:** 57 tests covering anomaly detection, event processing, incident lifecycle, integration, auth, and load testing
- **Load tested:** 47.7 RPS ingest throughput, 784 ms incident detection delay, 13–17 ms API read latency
- **Frontend reliability:** TypeScript strict mode, build verification, user-facing error states for all API tabs
- **Security:** API key authentication with tenant isolation enforced on all endpoints
- **Production hardening:** Structured logging, rate limiting, safe error handling, enhanced health checks, centralized config, request tracing
- **Deployment-ready:** Dockerfiles for all components, full Docker Compose stack, AWS architecture documented with Terraform and CI/CD

---

## Next Steps (If You Want to Extend)

- **Alerting:** PagerDuty/OpsGenie webhook integration for critical incidents
- **Metrics:** Prometheus metrics export from FastAPI
- **Auth:** OAuth2/JWT with refresh tokens for multi-tenant SSO
- **Multi-region:** Deploy backend to multiple regions with Kafka replication
- **ML model:** Train custom anomaly detection on historical incident data
- **Log aggregation:** ELK/Loki integration for centralized log search
- **SLO tracking:** Burn rate alerting dashboards
- **ChatOps:** Slack bot for incident notifications and status updates
- **Audit log:** Immutable API action log for compliance
- **Circuit breaker:** Resilience pattern for downstream service calls
- **OpenTelemetry:** Distributed tracing across all components
- **Feature flags:** LaunchDarkly or Unleash for gradual rollouts
- **Auto-remediation:** Runbook automation with step execution and rollback

---

## Project Timeline

| Day | Milestone | Status |
|-----|-----------|--------|
| 1–7 | Core API: ingest, detect, incidents, anomaly, graph, deployments | ✅ Done |
| 8–10 | PostgreSQL + Redis + Alembic migrations | ✅ Done |
| 11–12 | Service graph visualization + Redis pub/sub | ✅ Done |
| 13–14 | Deployments correlation + Runbook CRUD | ✅ Done |
| 15–16 | Keyword search + Semantic search via pgvector | ✅ Done |
| 17–18 | Root cause scoring + AI triage | ✅ Done |
| 19–20 | WebSocket live updates + Kafka event streaming | ✅ Done |
| 21 | Decoupled ingestion: API publishes, worker processes | ✅ Done |
| 22 | Integration tests: ingest-to-incident, graph, runbooks, search | ✅ Done |
| 23 | Frontend build verification, TypeScript fixes, API error states | ✅ Done |
| 24 | Load testing: 47.7 RPS, 784ms detection delay, bottleneck identified | ✅ Done |
| 25 | API key auth + tenant isolation on all endpoints | ✅ Done |
| 26 | Production hardening: logging, rate limiting, safe errors, health checks | ✅ Done |
| 27 | Docker Compose full stack, AWS architecture, CI/CD, Terraform | ✅ Done |
| 28 | README rewrite: architecture, data flow, demo, tradeoffs, scalability | ✅ Done |
| 29 | Demo seed data script + DEMO.md walkthrough with 8-step narrative and API commands | ✅ Done |
| 30 | Final QA: tests pass, warnings suppressed, stale files removed, ready for demo | ✅ Done |
| 31 | Finalization: demo verified end-to-end, architecture summary, interview guide, all docs complete | ✅ Done |

---

Built in 31 days. Every commit is in the repo. Every decision is documented. Every test passes.
