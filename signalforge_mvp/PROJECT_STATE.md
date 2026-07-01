# SignalForge — Project State Summary

> **Last updated:** Day 49 (July 2026)  
> **Current phase:** Documentation updates and resume polish complete. All project docs updated for auto-discovery feature. New docs: ENVIRONMENTS.md, RESUME_BULLETS.md, INTERVIEW_AUTO_DISCOVERY.md.

---

## 1. Architecture Decisions

### Ingestion Decoupling: API Publishes, Worker Processes (Day 21)
- **Before:** The `/ingest` endpoint returned `200 OK` after either publishing to Kafka (`mode="kafka"`) or processing synchronously (`mode="sync"`). The synchronous path blocked the HTTP request until DB write, Redis update, anomaly detection, and incident creation completed. The worker called `ingest_telemetry_event()` from `telemetry_service.py`, which was a thin wrapper that did everything.
- **After:** The `/ingest` endpoint returns `202 Accepted` when publishing to Kafka (`mode="async"`), signaling the client that processing is asynchronous. A new `EventProcessor` class in `app/services/event_processor.py` owns the full pipeline: DB persistence, Redis hot state, anomaly detection, incident creation. The API only publishes; the worker only calls `EventProcessor.process()`. The `telemetry_service.py` is reduced to query orchestration and a sync fallback wrapper.
- **Why:** In production, the API must accept thousands of events per second without blocking. By separating the fast API path from the heavy processing path, we get backpressure (queue grows when workers are slow, API stays fast) and horizontal scaling (run N workers across machines, Kafka rebalances partitions automatically).
- **How:** `POST /ingest` uses `status_code=status.HTTP_202_ACCEPTED` from FastAPI. The `EventProcessor` class is a single, well-documented owner of the pipeline. The worker consumer imports `event_processor` directly, not through the `telemetry_service` wrapper, making the ownership boundary explicit.
### Storage: In-Memory → SQLAlchemy Database (Day 9)
- **Before:** Python lists, sets, and deques. Data lost on restart.
- **After:** SQLAlchemy with SQLite file (default) or PostgreSQL (via Docker). Tables auto-created on startup. Data survives restarts.
- **Why:** Production systems need durable storage. SQLite allows testing without Docker. PostgreSQL is the target for production.

### Schema Management: Alembic Migrations (Day 10)
- **Before:** `Base.metadata.create_all()` on every startup. No schema versioning, no rollback, no change history.
- **After:** Alembic manages schema versions in `backend/alembic/versions/`. `app/main.py` runs `alembic upgrade head` on startup. Each schema change generates a migration script with upgrade/downgrade.
- **Why:** Production systems need reproducible, version-controlled schema changes. Autogenerate + review + commit is the standard pattern.

### Hot Operational State: PostgreSQL → Redis Rolling Windows (Day 11)
- **Before:** `get_recent_events()` queried PostgreSQL every time a new event arrived. With 500+ events per service, this was a full SELECT with ORDER BY and LIMIT on every ingest.
- **After:** Redis stores the last 50 events per `(tenant_id, service_name)` as a rolling window list. `add_event()` writes to PostgreSQL (durability) AND pushes to Redis (speed). `get_recent_events()` reads from Redis first; falls back to PostgreSQL if Redis is unavailable. Redis keys have a 1-hour TTL for auto-cleanup.
- **Why:** Anomaly detection runs on every single ingested event. Redis list operations (LPUSH, LTRIM, LRANGE) are O(1) and sub-millisecond. PostgreSQL SELECT is O(n log n) with disk I/O. Separating hot operational state (Redis) from durable source of truth (PostgreSQL) is a standard production pattern.
- **Graceful degradation:** If Redis is down, the system falls back to PostgreSQL queries. No data loss. The anomaly detector still works.

### Service Graph: Trace-Based Dependency Extraction (Day 12)
- **Before:** No visibility into which services call which. Trace events were stored but never analyzed for topology.
- **After:** `GET /graph` endpoint queries `event_type="trace"` and `name="service_call"` events, extracts `caller` and `callee` from `attributes`, and returns a directed graph of nodes (services) and edges (call dependencies). The frontend renders this as an SVG topology diagram with circular layout.
- **Why:** Understanding service dependencies is critical for root-cause analysis. When checkout-service fails, the graph immediately shows it calls notification-service, pointing to the cascading failure source.
- **How:** The simulator already emits `service_call` trace events with `caller` and `callee`. The backend aggregates these into unique edges with counts. The frontend arranges nodes in a circle and draws curved arrows between them.

### Deployment Correlation: Change-Based Root Cause Analysis (Day 13)
- **Before:** Incidents showed anomaly stats and evidence, but had no connection to deployments. A service could fail right after a bad deploy and the system would not surface this.
- **After:** `get_recent_deployments()` queries deployment events within a 30-minute window of the same service. When an incident is created, any recent deployment is added to the timeline as evidence with version, timestamp, and deployment count. The frontend highlights deployment timeline entries with a yellow badge and border.
- **Why:** "What changed?" is the first question engineers ask when something breaks. Correlating incidents with deployments surfaces change-based root cause without manual cross-referencing.
- **How:** Deployment events are already stored with `event_type="deployment"` and `name="service_deployed"` (Day 6 simulator). The incident engine queries them at incident creation time and adds a timeline entry. No schema migration needed.

### Runbooks: Operational Memory (Day 14)
- **Before:** No way to capture and share operational knowledge. Each incident response required tribal knowledge or external docs.
- **After:** Full CRUD API for runbooks linked to specific services. Runbooks have title, description, and ordered steps. The frontend has a dedicated tab for viewing and creating runbooks. Future incidents can reference the runbook for remediation steps.
- **Why:** Runbooks are the operational memory of a system. They capture "how to fix this" knowledge so teams don't relearn procedures. Linking runbooks to services means the right knowledge is available when an incident hits.
- **How:** New `runbooks` table with `service_name` index. REST API with POST/GET/PATCH/DELETE. Frontend `RunbookPanel` component with create form and list view. Alembic migration auto-generated from the SQLAlchemy model.

### Keyword Search: Incident + Runbook Memory (Day 15)
- **Before:** No way to search historical incidents or runbooks. Users had to scroll through lists manually. Incident detail pages had no connection to operational knowledge.
- **After:** `GET /search?q=keyword` performs case-insensitive ILIKE search across incident title, summary, service_name and runbook title, description, service_name. Results are merged and sorted by recency. The frontend has a dedicated Search tab with a search form and unified results grid. Incident detail panels now show related runbooks for the same service.
- **Why:** Engineers need to find past incidents and associated runbooks quickly. Connecting runbooks to incidents in the detail view surfaces operational knowledge without manual cross-referencing.
- **How:** SQLAlchemy `ilike()` on existing tables — no schema migration needed. The frontend fetches related runbooks via `fetchRunbooks(serviceName)` when an incident detail is opened.

### Semantic Search: pgvector + Embeddings (Day 16)
- **Before:** Keyword search only finds exact substring matches. Searching for "checkout timeout" won't find an incident titled "checkout latency spike" even though they're semantically related.
- **After:** PostgreSQL + pgvector extension stores 1536-dimension embeddings for incidents and runbooks. The `GET /search?semantic=true` endpoint converts the query to an embedding vector and uses pgvector cosine similarity (`<=>` operator) to find semantically related results. OpenAI API is tried first, then a local sentence-transformers model. If neither is available, the search transparently falls back to keyword search. The frontend has a "Semantic search" checkbox toggle.
- **Why:** Semantic search finds conceptually similar results even when wording differs. This is critical for incident memory — engineers might search "slow" but the incident is titled "latency degradation."
- **How:** New `embeddings` table with `vector(1536)` column (PostgreSQL only). Alembic migration is dialect-aware: creates the table on PostgreSQL, silently skips on SQLite. The `EmbeddingService` class tries OpenAI `text-embedding-3-small`, then `all-MiniLM-L6-v2`, then marks itself unavailable. Incident and runbook creation hooks automatically generate and store embeddings when the service is available.
- **Fallback:** If no embedding service is available, `semantic=true` behaves exactly like keyword search. No error, no broken UI.

### Root Cause Ranking: Rule-Based Evidence Scoring (Day 17)
- **Before:** When an incident fired, the dashboard showed the incident details but offered no guidance on what caused it. Engineers had to manually piece together evidence from deployments, logs, traces, and runbooks.
- **After:** `GET /services/{service_name}/root-cause` analyzes five dimensions of evidence and returns ranked hypotheses with scores, confidence levels, and recommended actions. The frontend shows a root cause panel inside the incident detail with a score bar, confidence badge, evidence breakdown, and alternative hypotheses for downstream services. No LLM required.
- **Why:** "What caused it?" is the first question in every incident. Automating the evidence gathering and ranking saves precious minutes during outages. Rule-based scoring is transparent and explainable — perfect for interviews and post-mortems.
- **How:** The `RootCauseEngine` scores each service across 5 dimensions: deployment recency (0-25), anomaly severity (0-25), error log frequency (0-25), trace dependency impact (0-15), and runbook similarity (0-10). Total score 0-100. Confidence: high ≥70, medium 40-69, low <40. The engine analyzes the primary service AND its downstream callees (from the graph), then ranks by total score. The `Storage` layer provides evidence-gathering methods that query existing tables. No new schema needed.

### Anomaly Detection: Rolling Window (Day 4)
- Analyzes latest 20 `metric` / `http_request` events per service.
- Minimum 20 samples before detection.
- Warning thresholds: error rate ≥ 20%, avg latency ≥ 1000 ms, p95 ≥ 1500 ms.
- Critical thresholds: error rate ≥ 50%, avg latency ≥ 1800 ms, p95 ≥ 2500 ms.
- Only `metric`/`http_request` events trigger detection. Logs, traces, deployments are stored but ignored for anomaly scoring.

### Incident Engine: Duplicate Prevention + Timeline (Day 5)
- Open incident per `(tenant, service)` pair. No duplicate spam.
- Status lifecycle: `investigating` → `mitigated` → `resolved`.
- `resolved` removes the open-incident lock, allowing future incidents.
- Timeline entries: `created`, `evidence_added`, `status_changed` with actor attribution.
- Anomaly stats (sample_count, error_rate, avg_latency, p95_latency) embedded in evidence metadata.
- Deployment correlation (Day 13): recent deployments added to timeline as evidence.

### Simulator: 5-Service Microservice Story (Day 6)
- Services: checkout, payment, inventory, fraud, notification.
- Dependency graph: checkout → payment/inventory/notification; payment → fraud.
- Phase 1 (0-49): normal traffic. Phase 2 (50): bad deploy (notification v42). Phase 3 (50+): cascading failure.
- Emits metrics, logs, traces, and deployment events.

### Dashboard: React + TanStack Query (Day 7)
- Incident cards with severity colors (critical=red, warning=yellow, info=blue).
- Click-to-expand detail panel with timeline, evidence, status actions.
- Auto-refresh every 3 seconds.
- Loading, error, and empty states.
- Responsive layout for desktop and mobile.
- Status update via PATCH API with auto-refresh.
- Service Graph tab (Day 12): SVG topology visualization.
- Runbooks tab (Day 14): CRUD for operational memory.

### Infrastructure: Docker Compose (Day 8)
- PostgreSQL 16 (port 5432) with named volume and health check.
- Redis 7 (port 6379) with AOF and health check.
- Backend Dockerfile ready for containerization.
- Redis and PostgreSQL are fully used by the backend (Day 11 Redis, Day 9 PostgreSQL).

### Auto-Discovery: Pluggable Provider Engine (Days 32–35)
- **Before:** Services had to be manually registered or hardcoded. No visibility into runtime topology, health, or dependencies. Telemetry events required explicit `service_name`.
- **After:** The `DiscoveryEngine` orchestrates multiple `ServiceDiscoveryProvider` implementations concurrently. Discovered services are stored in PostgreSQL via `ServiceRegistry` with an in-memory cache for fast lookups. The `EventServiceCorrelator` matches telemetry events to discovered services using 7 strategies with confidence scoring. The `ServiceProber` runs HTTP/TCP health checks and classifies service type via 7-layer heuristics.
- **Why:** In a microservices environment, services are ephemeral. Manual registration doesn't scale. Auto-discovery enables zero-configuration monitoring and automatic event correlation.
- **How:** `EnvironmentDetector` checks the runtime (Docker, K8s, AWS, Azure, GCP, VM) and configures the right providers. Providers run via `asyncio.gather` with individual error isolation. The registry deduplicates by `(service_name, host)` and marks stale services inactive after 90s.

### Health Probing and Auto-Classification (Days 39–40)
- **Before:** No way to know if a discovered service was healthy or what type it was.
- **After:** `ServiceProber` tries 8 common HTTP health endpoints (`/health`, `/healthz`, `/actuator/health`, etc.) and falls back to TCP connect. Classification uses 7 layers: K8s labels → Docker image → process name → framework detection → port mapping → content-type inference → fallback.
- **Why:** Health status is critical for incident severity. Service type classification enables the correlation engine to disambiguate multiple candidates.

### Event Correlation: 7-Strategy Matching (Days 41–43)
- **Before:** Telemetry events required a pre-configured `service_name`. Events from unknown sources were orphaned.
- **After:** The `EventServiceCorrelator` tries exact name, source IP+port, hostname, container ID, pod name, process ID, and trace context. Each match has a confidence score (0.85–1.0). Disambiguation prefers the most recent heartbeat and matching service type.
- **Why:** Not all telemetry sources label their events clearly. A log from Fluent Bit might have a container ID. A metric from kube-state-metrics might have a pod name. By trying all 7 strategies, we maximize match coverage.

### Service Dependency Detection (Days 44–45)
- **Before:** The service graph only showed trace-based dependencies. No visibility into network topology or traffic patterns.
- **After:** `DependencyGraphBuilder` combines three analyzers: `TraceAnalyzer` (Jaeger/Zipkin/mock), `TrafficAnalyzer` (nginx/Envoy/JSON access logs), and `NetworkScanner` (port scanning). Dependencies are scored by severity (frequency + error rate) and exposed via REST + WebSocket.
- **Why:** Dependencies are critical for root-cause analysis. When checkout-service fails, the graph shows it calls notification-service, pointing to the cascading failure source. Multiple detection strategies increase coverage.

### Multi-Environment Integration Tests (Days 46–48)
- **Before:** No tests for discovery providers. No validation that Docker, K8s, or bare metal environments worked correctly.
- **After:** 46 integration tests across Docker (mocked SDK), Kubernetes (mocked client), bare metal (mocked psutil), and mixed environments. 19 performance benchmarks with deterministic mock data (seed=42), `tracemalloc` memory profiling, and 100-run repeats. All run in CI with zero external dependencies.
- **Why:** Discovery depends on external APIs (Docker daemon, K8s API, cloud metadata). Mocked integration tests guarantee the logic works without requiring the actual infrastructure. Performance benchmarks ensure we can detect regressions.

---

## 2. Files Modified (Days 1–14)

### Backend Core
| File | Day | What it does now |
|------|-----|------------------|
| `backend/app/main.py` | 1, 9, 10, 12, 15, 17, 18, 26 | FastAPI app factory, CORS, router registration, structured logging, request logging middleware, exception handlers, rate limiting, docs hidden in production |
| `backend/app/schemas.py` | 3, 12, 14, 15, 17, 18 | Pydantic models: TelemetryEvent, Incident, IncidentTimelineEntry, ServiceGraphNode, ServiceGraphEdge, ServiceGraphResponse, Runbook, RunbookCreate, RunbookUpdate, SearchResultItem, SearchResponse, RootCauseEvidence, RootCauseHypothesis, RootCauseResponse |
| `backend/app/database.py` | 9, 10, 26 | SQLAlchemy engine, session factory, declarative base, `init_db()` (legacy), uses centralized config |
| `backend/app/models.py` | 9, 14 | SQLAlchemy table definitions: TelemetryEventModel, IncidentModel, RunbookModel with indexes |
| `backend/app/storage.py` | 1, 9, 11, 12, 13, 14, 15, 16, 17 | Database access layer: `DatabaseStore` with SQLAlchemy sessions + Redis rolling windows + `get_service_graph()` + `get_recent_deployments()` + runbook CRUD + keyword search + semantic search + root-cause evidence gathering |
| `backend/app/redis_client.py` | 11, 26 | Redis rolling window: `RedisWindowStore` with LPUSH, LTRIM, LRANGE, TTL per service, uses centralized config |
| `backend/app/anomaly.py` | 4, 11 | Rolling-window anomaly detection with stats and p95 (now reads from Redis) |
| `backend/app/incident_engine.py` | 3, 5, 13, 16 | Incident creation with timeline, evidence, stats metadata, deployment correlation, embedding generation |
| `backend/app/embeddings.py` | 16, 26 | `EmbeddingService`: OpenAI → local model → None fallback, uses centralized config |
| `backend/app/routers/ingest.py` | 1, 3, 21, 25, 26 | POST /ingest with validation, duplicate protection, auth, rate limiting (100 RPS), returns 202 Accepted, structured logging |
| `backend/app/routers/events.py` | 1 | GET /events |
| `backend/app/routers/incidents.py` | 1, 5, 25 | GET /incidents, GET /incidents/{id}, PATCH /incidents/{id}/status with auth-enforced tenant isolation |
| `backend/app/routers/graph.py` | 12 | GET /graph — returns service dependency graph from trace events |
| `backend/app/routers/deployments.py` | 13 | GET /deployments — lists recent deployment events |
| `backend/app/routers/runbooks.py` | 14, 16 | POST/GET/PATCH/DELETE /runbooks — CRUD for operational runbooks + embedding generation |
| `backend/app/routers/search.py` | 15, 16, 25 | GET /search — keyword search + semantic search via pgvector with fallback, auth-enforced tenant isolation |
 | `backend/app/routers/ai_triage.py` | 18, 25 | GET /incidents/{id}/ai-triage — AI analysis with OpenAI + mock fallback, auth-enforced tenant isolation |
| `backend/app/routers/root_cause.py` | 17, 25 | GET /services/{service_name}/root-cause — rule-based evidence scoring, auth-enforced tenant isolation |
| `backend/app/routers/runbooks.py` | 14, 16, 25 | POST/GET/PATCH/DELETE /runbooks — CRUD for operational runbooks + embedding generation + auth-enforced tenant isolation |
| `backend/app/routers/deployments.py` | 13, 25 | GET /deployments — lists recent deployment events, auth-enforced tenant isolation |
| `backend/app/routers/graph.py` | 12, 25 | GET /graph — returns service dependency graph from trace events, auth-enforced tenant isolation |
| `backend/app/routers/websocket.py` | 19 | WebSocket endpoint for live incident updates |
| `backend/app/routers/health.py` | 1, 26 | Health check with DB connectivity test, dependency status (database, redis, kafka), environment field |
| `backend/app/config.py` | 26 | Centralized configuration: `Config` class reads DATABASE_URL, REDIS_URL, KAFKA_BROKERS, OPENAI_API_KEY, ENVIRONMENT, LOG_LEVEL, RATE_LIMIT from env vars |
| `backend/app/logging_config.py` | 26 | Structured logging with `timestamp= level= logger= message=` format, JSON-safe extra fields, suppresses noisy third-party logs in production |
| `backend/app/middleware/error_handler.py` | 26 | Global exception handlers: safe 500 responses (no stack traces in production), 422 validation with sanitized errors, request_id tracking |
| `backend/app/middleware/request_logging.py` | 26 | `RequestLoggingMiddleware`: logs every request with method, path, status_code, duration_ms, client_ip, request_id |
| `backend/app/middleware/rate_limit.py` | 26 | In-memory sliding-window rate limiter (100 RPS default per IP), returns 429 Too Many Requests, `reset()` for testing |
| `backend/app/auth.py` | 25 | `get_current_tenant` dependency: validates `X-API-Key` header, maps key → tenant_id, returns 401 on missing/invalid key |
| `backend/app/services/event_processor.py` | 21 | Worker-owned pipeline: DB + Redis + anomaly + incident. API never calls this directly. |
| `backend/app/services/telemetry_service.py` | 1, 5, 21 | Sync fallback wrapper + query orchestration. Delegates to EventProcessor for ingestion. |
| `backend/app/services/kafka_consumer_worker.py` | 20, 21 | Consumes Kafka events and calls EventProcessor directly (not telemetry_service). Updated docs for backpressure and horizontal scaling. |
| `backend/app/root_cause_engine.py` | 17 | Rule-based root-cause ranking: 5-dimension scoring engine |
| `backend/requirements.txt` | 1, 8, 9, 10, 22 | FastAPI, uvicorn, pydantic, pytest, SQLAlchemy, psycopg2, asyncpg, redis, alembic, httpx (Day 22) |
| `backend/Dockerfile` | 8, 21 | Python 3.12 container image with alembic support |
| `backend/.env.example` | 8, 9, 20 | DATABASE_URL, REDIS_URL, KAFKA_BROKERS, LOG_LEVEL, ENVIRONMENT |

### Tests
| File | Day | Coverage |
|------|-----|----------|
| `backend/tests/conftest.py` | 9, 22 | In-memory SQLite fixture + FastAPI TestClient + reset_store (Day 22) |
| `backend/tests/test_anomaly.py` | 4 | 8 tests: healthy, warning, critical for error rate, avg latency, p95 |
| `backend/tests/test_event_processor.py` | 21 | 6 tests: duplicate detection, healthy no-incident, anomaly creates incident, single open incident per service, DB storage, Redis hot state |
| `backend/tests/test_incidents.py` | 5 | 6 tests: duplicate prevention, resolved allows new, status update, no-op, mitigated blocks duplicate, timeline structure |
| `backend/tests/test_integration_ingest.py` | 22 | 10 tests: healthy→no incident, bad→incident, detail, status update, events persisted, duplicate, resolved allows new, mitigated blocks, validation (3×) |
| `backend/tests/test_integration_graph.py` | 22 | 4 tests: empty graph, single trace, aggregate counts, multiple edges |
| `backend/tests/test_integration_runbooks.py` | 22 | 12 tests: create, list, filter, get, get 404, update, update 404, delete, delete 404, search by title, search by description, search by service |
| `backend/tests/test_integration_search.py` | 22 | 6 tests: search incident by title, search by service, mixed results, no results, empty query 422, health check |
| `backend/tests/test_auth.py` | 25 | 3 tests: missing API key returns 401, invalid API key returns 401, valid API key returns data |
| `backend/tests/conftest.py` | 9, 22, 25, 26 | In-memory SQLite fixture + FastAPI TestClient with `X-API-Key` header + reset_store + rate limiter reset (Day 22, 25, 26) |
| `backend/tests/load/locustfile.py` | 24 | Locust load test: TelemetryUser (ingest metrics/traces/logs, read endpoints) + ReadOnlyUser (dashboard polling) |
| `backend/tests/load/run_load_tests.py` | 24 | Orchestrates backend startup, API latency test, ingest throughput test (10s burst + 1000 fixed), incident detection delay test; outputs JSON report |
| `backend/tests/load/debug_detection.py` | 24 | Debug script for incident detection delay; isolated 20-event anomaly trigger test |
| `backend/tests/discovery/` | 46–48 | 26 unit tests: correlation, WebSocket, Docker provider, environment, models, probing, process provider, registry, dependency analyzers |
| `backend/tests/integration/` | 46–48 | 46 integration tests: Docker, K8s, bare metal, mixed — all with mocked SDKs |
| `backend/tests/performance/` | 48 | 19 benchmarks: discovery latency, correlation accuracy, memory, graph queries — deterministic seed=42, tracemalloc profiling |
| `.github/workflows/ci.yml` | 46–48 | GitHub Actions: pytest on push, Python 3.12 |
| `.github/workflows/performance-tests.yml` | 48 | GitHub Actions: performance benchmarks on push, artifact upload |

### Frontend
| File | Day | What it does now |
|------|-----|------------------|
| `frontend/src/App.tsx` | 7, 12, 13, 14, 15, 16, 17, 18, 23 | Dashboard: cards, detail panel, timeline, status actions, states, tab navigation, ServiceGraph, deployment evidence, RunbookPanel, Search tab, related runbooks, semantic search toggle, root cause panel, AI triage panel, **error states for all tabs (incidents, graph, runbooks, search) with user-facing messages, loading spinners, WebSocket typed message handler** |
| `frontend/src/App.css` | 7, 12, 13, 14, 15, 16, 17, 18 | Full styling: cards, badges, timeline, overlay, tab nav, graph SVG, deployment badge, runbook panel, search panel, related runbooks, semantic toggle, root cause panel, responsive breakpoints |
| `frontend/src/api.ts` | 7, 12, 14, 15, 16, 17, 18, 23 | `ApiError` class with user-facing `userMessage()`, `apiFetch<T>` helper, all API functions using typed fetch with error handling |
| `frontend/src/types.ts` | 7, 12, 14, 15, 17, 18 | Incident, IncidentTimelineEntry, ServiceGraphNode, ServiceGraphEdge, ServiceGraphResponse, Runbook, SearchResultItem, SearchResponse, RootCauseResponse, RootCauseHypothesis, RootCauseEvidence |
| `frontend/src/components/ServiceGraph.tsx` | 12 | SVG circular layout service topology visualization |
| `frontend/package.json` | 1, 23 | Vite + React + TypeScript setup, `build-check` script (tsc --noEmit && vite build) |

### Simulator
| File | Day | What it does now |
|------|-----|------------------|
| `simulator/traffic_simulator.py` | 6 | 5-service simulator with dependency graph, 3-phase cascading failure story |
| `simulator/requirements.txt` | 6 | requests library |

### Infrastructure & Docs
| File | Day | What it does now |
|------|-----|------------------|
| `docker-compose.yml` | 8, 42 | PostgreSQL 16 + Redis 7 + Redpanda + Backend + Frontend + Simulator with health checks, auto-discovery env vars, Docker socket mount, and pid: host for process discovery |
| `docker-compose.override.yml` | 42 | Local dev override: live reload (uvicorn --reload), source code volume mounts, ENVIRONMENT=development, LOG_LEVEL=DEBUG, disables nginx frontend |
| `docker-compose.prod.yml` | 42 | Production override: resource limits (CPU/memory), read-only root filesystem, restart policies, only config discovery provider, no docker socket or pid: host |
| `Dockerfile.discovery` | 42 | Standalone discovery agent placeholder based on python:3.12-slim with psutil, docker, kubernetes dependencies |
| `helm/signforge/Chart.yaml` | 40 | Helm chart metadata with optional Bitnami PostgreSQL, Redis, Kafka subchart dependencies |
| `helm/signforge/values.yaml` | 40 | Comprehensive Helm defaults: discovery, RBAC, resources, scheduling, dependency toggles |
| `helm/signforge/templates/` | 40 | _helpers.tpl, deployment.yaml, service.yaml, configmap.yaml, serviceaccount.yaml, rbac.yaml, ingress.yaml, hpa.yaml, NOTES.txt, test-connection.yaml |
| `terraform/modules/signforge/` | 41 | Root module with conditional sub-modules: VPC, EKS, ECS, RDS, ElastiCache, MSK, ALB, CloudFront, IAM, Security Groups |
| `terraform/examples/` | 41 | eks-complete (production EKS) and ecs-simple (dev Fargate) examples with READMEs |
| `AWS_ARCHITECTURE.md` | 27, 41 | AWS deployment spec: ECS/EKS, RDS, ElastiCache, MSK, ALB, CloudFront, Terraform modules, CI/CD |
| `backend/alembic.ini` | 10 | Alembic configuration file |
| `backend/alembic/` | 10 | Alembic env.py, migration templates, and versioned migration scripts |
| `Days/SignalForge_Day21_Decoupled_Ingestion_Report.txt` | 21 | Day 21 report: decoupled ingestion, EventProcessor, 202 Accepted, backpressure, horizontal scaling |
| `README.md` | 1–28 | Full project README: architecture diagram, data flow, demo walkthrough, design tradeoffs, scalability discussion, setup, backend structure, anomaly policy, simulator phases, Docker commands, migration workflow, service graph, deployment correlation, runbooks, search, root cause, decoupled ingestion architecture, AWS deployment, load testing, testing |
| `DEMO.md` | 29 | 5-minute demo walkthrough with 8-step narrative, seed data script, API commands, and talking points |
| `scripts/seed_demo.py` | 29 | Deterministic seed script: healthy traffic, bad deployment, cascading failure, incident creation, runbooks |
| `ARCHITECTURE_SUMMARY.md` | 31 | One-page architecture reference: 3-layer model, data flow, metrics, scalability path, tech stack, file map |
| `INTERVIEW_GUIDE.md` | 31 | Interview explanation guide: 30-second pitch, 2/5/15/30-minute deep dives, common Q&A, live demo script |
| `Days/SignalForge_DayX_*_Report.txt` | 1–10, 12, 13, 14, 15, 16, 17, 18 | Daily reports per day |
| `backend/app/discovery/engine.py` | 32–35 | Discovery engine: orchestrates providers, deduplication, background loop, stale removal |
| `backend/app/discovery/models.py` | 32–35 | DiscoveredService, HealthProbeResult, ProbeStatus, ProbeType Pydantic models |
| `backend/app/discovery/registry.py` | 32–35 | ServiceRegistry: PostgreSQL persistence + in-memory cache, deduplication by (service_name, host) |
| `backend/app/discovery/probing.py` | 39–40 | ServiceProber: HTTP/TCP health checks, protocol detection, 7-layer classification |
| `backend/app/discovery/correlation.py` | 41–43 | EventServiceCorrelator: 7-strategy matching with confidence scoring and disambiguation |
| `backend/app/discovery/environment.py` | 32–35 | EnvironmentDetector: auto-detects Docker, K8s, AWS, Azure, GCP, VM |
| `backend/app/discovery/base.py` | 32–35 | ServiceDiscoveryProvider abstract base class |
| `backend/app/discovery/providers/docker.py` | 36–38 | DockerDiscoveryProvider: scans containers, images, port mappings, labels |
| `backend/app/discovery/providers/kubernetes.py` | 36–38 | KubernetesDiscoveryProvider: scans pods, services, labels, namespaces |
| `backend/app/discovery/providers/process.py` | 36–38 | ProcessDiscoveryProvider: psutil scanning, listening ports, system process blocklist |
| `backend/app/discovery/providers/config.py` | 36–38 | ConfigDiscoveryProvider: JSON/YAML static config from env var or file |
| `backend/app/discovery/providers/cloud.py` | 36–38 | CloudDiscoveryProvider: AWS, Azure, GCP metadata endpoints |
| `backend/app/discovery/dependencies/graph_builder.py` | 44–45 | DependencyGraphBuilder: combines trace, traffic, and network analyzers |
| `backend/app/discovery/dependencies/trace_analyzer.py` | 44–45 | TraceAnalyzer: parses Jaeger/Zipkin/mock traces for parent-child relationships |
| `backend/app/discovery/dependencies/traffic_analyzer.py` | 44–45 | TrafficAnalyzer: parses nginx/Envoy/JSON access logs for caller-callee |
| `backend/app/discovery/dependencies/network_scanner.py` | 44–45 | NetworkScanner: port scanning, topology inference |
| `backend/app/discovery/dependencies/mesh_analyzer.py` | 44–45 | MeshAnalyzer: service mesh dependency detection |
| `backend/app/routers/discovery.py` | 32–35 | GET /services/discovered, /health, /dependencies, /discovery-status |
| `backend/app/routers/discovery_ws.py` | 32–35 | WebSocket /ws/discovery: real-time discovery event broadcast |
| `frontend/src/components/DiscoveryEventFeed.tsx` | 32–35 | Real-time discovery event feed with filtering and pause/resume |
| `frontend/src/components/ServiceDetailsPanel.tsx` | 32–35 | Service detail panel with tabs: overview, incidents, dependencies, runbooks, metadata |
| `docs/ENVIRONMENTS.md` | 49 | Environment-specific discovery guide: Docker, K8s, AWS, bare metal |
| `RESUME_BULLETS.md` | 49 | Copy-paste ready resume bullet points for backend, SRE, data, frontend roles |
| `INTERVIEW_AUTO_DISCOVERY.md` | 49 | Interview deep dive: 30s pitch, 2min intro, 5min technical, 15min system design, Q&A |

---

## 3. Outstanding Tasks (From Timeline)

| Day | Task | Status |
|-----|------|--------|
| 10 | Alembic migrations for schema versioning | ✅ Done |
| 11 | Redis for hot operational state (real-time windows, not DB) | ✅ Done |
| 12 | Service dependency graph from trace events | ✅ Done |
| 13 | Deployment history endpoint and incident correlation | ✅ Done |
| 14 | Runbook CRUD and operational memory | ✅ Done |
| 15 | Keyword search over runbooks and incidents | ✅ Done |
| 16 | Semantic search via pgvector with fallback | ✅ Done |
| 17 | Rule-based root-cause ranking | ✅ Done |
| 18 | AI triage with OpenAI + mock fallback | ✅ Done |
| 19 | WebSocket live incident updates | ✅ Done |
| 20 | Kafka event-driven telemetry ingestion | ✅ Done |
| 18 | AI triage assistant (context prompt + API) | ⏳ Pending |
| 19 | Real-time streaming via WebSocket or Redis pub/sub | ⏳ Pending |
| 20 | Kafka/Redpanda event bus | ⏳ Pending |
| 21 | Decouple ingestion: API publishes, worker processes via EventProcessor | ✅ Done |
| 22 | Integration tests: ingest-to-incident, graph, runbooks, search | ✅ Done |
| 23 | Frontend build verification, TypeScript fixes, API error states | ✅ Done |
| 24 | Load testing: measured throughput, detection delay, API latency; bottleneck documented | ✅ Done |
| 25 | API key auth + tenant isolation on all endpoints; frontend sends auth headers | ✅ Done |
| 26 | Production hardening: structured logging, rate limiting, safe errors, health checks, config | ✅ Done |
| 27 | Docker Compose full stack (backend, frontend, simulator), AWS architecture, CI/CD, Terraform | ✅ Done |
| 28 | README rewrite: architecture diagram, data flow, demo walkthrough, design tradeoffs, scalability | ✅ Done |
| 29 | Demo seed data script + DEMO.md walkthrough with 8-step narrative and API commands | ✅ Done |
| 30 | Final QA: tests pass, warnings suppressed, stale files removed, ready for demo | ✅ Done |
| 31 | Finalization: demo verified end-to-end, architecture summary, interview guide, all docs complete | ✅ Done |
| 40 | Helm chart for Kubernetes with auto-discovery, optional subcharts, RBAC, and CI | ✅ Done |
| 41 | Terraform modules for AWS: EKS + ECS, RDS, ElastiCache, MSK, ALB, CloudFront, IAM, Security Groups | ✅ Done |
| 42 | Docker Compose auto-discovery: docker socket mount, process discovery, override files, production hardening, deployment checklist | ✅ Done |
| 43–45 | Discovery core: engine, registry, models, base class, environment detector | ✅ Done |
| 46–48 | Discovery providers: Docker, K8s, Process, Config, Cloud | ✅ Done |
| 49 | Health probing, auto-classification, event correlation, dependency detection | ✅ Done |
| 50 | Multi-environment integration tests: Docker, K8s, bare metal, mixed | ✅ Done |
| 51 | Performance benchmarks: discovery latency, correlation accuracy, graph queries | ✅ Done |
| 52 | Documentation: ENVIRONMENTS.md, RESUME_BULLETS.md, INTERVIEW_AUTO_DISCOVERY.md | ✅ Done |
| 53 | PROJECT_STATE.md update: Day 49 status, architecture decisions, file inventory | ✅ Done |

---

## 4. Known Bugs / Limitations

| Issue | Severity | Notes |
|-------|----------|-------|
| Semantic search only works on PostgreSQL, not SQLite | Low | pgvector extension is PostgreSQL-only. SQLite dev environments fall back to keyword search transparently. |
| Docker Desktop not installed on dev machine | Low | Backend falls back to SQLite. PostgreSQL and Redis containers not running. Not a blocker for Days 1–9. |
| Frontend `node_modules` missing | Low | React dashboard code is written but never built/ran in this environment. `npm install` + `npm run dev` required locally. |
| No alembic migrations | None | Fixed on Day 10. Alembic is now fully configured with auto-generated migrations. |
| `update_incident_status` no-op check is string-based | Low | Compares `status != status.value` which is a type mismatch, but works because SQL stores strings. Should be consistent. |
| Simulator does not have its own `.env` | Low | `API_URL` and `TENANT_ID` are hardcoded constants. Could be parameterized. |
| Frontend detail panel `useQuery` does not refetch on interval | Low | List refetches every 3s, but detail panel only fetches once. Opening a stale incident card may show outdated data until re-opened. |
| `recent_by_service` no longer exists in storage | None | Anomaly detection still uses `get_recent_events()` which queries the DB. No functional change. |
| `anomaly.py` still hardcodes thresholds | Low | Thresholds are module-level constants. Could be configurable per-tenant in the future. |
| No authentication or authorization | Medium | **FIXED on Day 25.** API key auth with tenant isolation is now enforced on all endpoints except `/health`. |
| Redis port out of range in test conftest | None | Fixed on Day 21. Changed `redis://localhost:99999/0` to `redis://localhost:12345/0` and widened exception handling in `RedisWindowStore.__init__`. |
| `storage.py` uses sync SQLAlchemy | Medium | FastAPI endpoints are async but storage blocks the event loop. `sqlalchemy[asyncio]` + `asyncpg` configured but not used. Day 10+ should migrate to async sessions. |
| No rate limiting on /ingest | Medium | **FIXED on Day 26.** In-memory sliding-window rate limiter (100 RPS) is active. Upgrade path to Redis-backed for multi-instance. |
| Backend `GET /events` returns only last 50 | Low | By design. In-memory `events` list was unlimited but capped at 50. Database query also caps at 50. Good for performance, bad for deep analysis. |
| `IncidentTimelineEntry.metadata` uses `Record<string, any>` | Low | TypeScript `any` type in `types.ts` is loose. Could be tightened with a union type for known metadata shapes. |
| Frontend `service_call` traces not displayed | Low | Trace events are emitted by simulator but dashboard only shows incidents and basic events. Trace visualization on Day 12. |
| No `PATCH /incidents/{id}/status` body validation in router | Low | `IncidentStatusUpdate` schema validates, but the endpoint does not explicitly validate `note` length or `actor` format. |
| PostgreSQL `asyncpg` driver installed but unused | None | Sync `psycopg2` is used instead. `asyncpg` is ready for Day 10+ async migration. |

---

## 5. Next Steps

### Completed: Days 21–31 (Decoupled Ingestion + Auth + Hardening + Docs)
- **Day 21:** Refactored ingestion to 202 Accepted with EventProcessor pipeline. Backpressure and horizontal scaling supported.
- **Day 22:** Integration tests for ingest-to-incident, graph, runbooks, search (53 tests total).
- **Day 23:** Frontend build verification, TypeScript fixes, user-facing API error states.
- **Day 24:** Load tests: 47.7 RPS, 784ms detection delay, 13–17ms API read latency. SQLite bottleneck identified.
- **Day 25:** API key auth + tenant isolation on all endpoints.
- **Day 26:** Production hardening: structured logging, rate limiting, safe errors, health checks, config.
- **Day 27:** Docker Compose full stack, AWS architecture, CI/CD, Terraform.
- **Day 28:** README rewrite with architecture, data flow, demo, tradeoffs, scalability.
- **Day 29:** Demo seed data script + DEMO.md walkthrough.
- **Day 30:** Final QA: tests pass, warnings suppressed, stale files removed.
- **Day 31:** Finalization: architecture summary, interview guide, all docs complete.

### Completed: Days 32–49 (Auto-Discovery + Health Probing + Correlation + Dependencies + Tests + Docs)
- **Days 32–35:** Discovery engine, registry, models, base class, environment detector.
- **Days 36–38:** Docker, Kubernetes, Process, Config, Cloud providers.
- **Days 39–40:** Health probing and auto-classification with HTTP/TCP probes and 7-layer heuristics.
- **Days 41–43:** Event correlation with 7-strategy matching and confidence scoring.
- **Days 44–45:** Service dependency detection via trace analysis, traffic log parsing, and network scanning.
- **Days 46–48:** Multi-environment integration tests (46 tests) and performance benchmarks (19 tests) with deterministic data.
- **Day 49:** Documentation updates: README, ARCHITECTURE_SUMMARY, INTERVIEW_GUIDE, DEMO, AWS_ARCHITECTURE, ENVIRONMENTS, RESUME_BULLETS, INTERVIEW_AUTO_DISCOVERY, PROJECT_STATE.

### Next Steps (If You Want to Extend)
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
- **Service mesh:** Istio/Linkerd integration for mesh-level discovery

---

## 6. How to Resume Work

1. Open the project at `C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp`
2. Check the `Days/` folder for the latest completed day report.
3. Read `README.md` for current setup instructions.
4. Start Docker: `docker-compose up -d`
5. Set environment variables:
   ```powershell
   $env:DATABASE_URL="postgresql+psycopg2://signforge:signforge@localhost:5432/signforge"
   $env:REDIS_URL="redis://localhost:6379/0"
   $env:PYTHONUTF8="1"
   ```
6. Start the backend: `uvicorn app.main:app --reload`
7. Start the simulator: `python traffic_simulator.py`
8. Start the frontend: `npm run dev`
9. Open the browser: `http://127.0.0.1:8000/docs` and `http://localhost:5173`

If the backend was modified, run tests first:
```powershell
cd .\signalforge_mvp\backend
.\.venv\Scripts\activate
$env:PYTHONUTF8='1'
python -m pytest tests -v
```

For first-time setup on a fresh database, the backend runs Alembic migrations automatically on startup. If PostgreSQL already has tables from `init_db()`, run `alembic stamp head` once to mark the schema as migrated.

---

## 7. Interview Talking Points

- **Why SQLite default?** "SQLite lets you run the project without installing Docker. For production, switch DATABASE_URL to PostgreSQL."
- **Why 202 Accepted?** "202 signals the client that the event was accepted but processing is asynchronous. The client doesn't need to wait for anomaly detection or incident creation. This is the standard pattern for high-throughput ingestion systems."
- **Why a separate EventProcessor class?** "It makes the ownership boundary explicit. The API publishes; the worker processes. This shows separation of concerns and enables explaining backpressure and horizontal scaling in an interview."
- **What happens if the worker crashes?** "Kafka retains messages for a configured retention period. When the worker restarts, it resumes from its last committed offset. Unprocessed events are not lost."
- **How would you scale this?** "Run more worker containers. Kafka rebalances topic partitions across consumers in the same group automatically. No code changes needed."
- **Why separate database and Redis?** "PostgreSQL is the durable source of truth. Redis is the hot operational state for fast rolling window queries."
- **Why p95 latency?** "Average latency can hide tail latency. A few very slow requests (p95) often indicate a real problem even if the average looks fine."
- **Why duplicate incident prevention?** "Without it, a failing service would create 50 incidents per minute. One open incident per service is the right operational pattern."
- **Why the simulator has 5 services?** "Real microservices have dependencies. A failing notification service cascades to checkout. This is a realistic failure story."
- **Why TanStack Query?** "It handles caching, refetching, and loading states automatically. Less boilerplate than useEffect + fetch."
- **Why keyword search before vector search?** "Basic ILIKE search is fast, requires no new infrastructure, and solves 80% of the problem. Vector search is a future upgrade, not a Day 1 requirement."
- **Why show related runbooks in incident detail?** "When an incident fires, the engineer's first question is 'how do I fix this?' Surfacing runbooks in the same view eliminates context switching and speeds up remediation."
- **What did load testing reveal?** "On SQLite, the backend handles ~48 RPS with 0 errors at 20 concurrent workers. At 50 workers, p99 latency jumps to 3.3s and 0.4% of requests fail with 'database is locked.' This proves SQLite is the bottleneck, not the API or anomaly detection logic. With PostgreSQL (already in the Docker stack), I'd expect 500+ RPS. The test also measured 784 ms incident detection delay from the first bad event — well within the SLA for a monitoring system."
- **Why measure detection delay?** "It's not enough to say 'we detect anomalies.' You need to know how fast. 784 ms from the 20th bad event to incident creation is a concrete number I can put on a resume and discuss in an interview."
- **Why auto-discovery?** "In a microservices environment, services are ephemeral. Containers restart, pods scale, new versions deploy. Manual registration doesn't work at scale. The discovery engine auto-detects the environment and configures the right providers — Docker, Kubernetes, or cloud. No manual config."
- **Why 7 correlation strategies?** "Each strategy handles a different source of telemetry. A metric from Prometheus might have a pod name. A log from Fluent Bit might have a container ID. A trace from Jaeger might have a parent span service. By trying all 7, we maximize the chance of matching an event to a service without requiring the client to change their telemetry format."
- **Why pluggable providers?** "The provider pattern decouples the discovery engine from environment-specific logic. Each provider is a single responsibility. Adding a new environment is one file: implement `health_check()` and `discover()`, register it in `EnvironmentDetector`, and the engine picks it up automatically. We could add Consul, etcd, or Consul Connect without touching the engine or registry."
- **Why PostgreSQL + cache for the registry?** "PostgreSQL is the source of truth — it survives restarts and supports queries. But reading from PostgreSQL on every correlation or probe would be slow. The in-memory cache syncs with the DB on every read, giving us sub-millisecond lookups for the hot path while keeping durability."
- **What did performance benchmarks reveal?** "Discovery latency for 100 services is <10s. Event correlation averages <5ms. Graph queries for all dependencies are <100ms. Memory footprint for 100 services is <50MB. All benchmarks use deterministic mock data with seed=42 and 100-run repeats for stability. This proves the discovery engine is lightweight enough to run continuously in the background."

---

## 8. Commit Style

Commits should look natural and human-written. Short, lowercase, casual. No conventional commit prefixes (`feat:`, `docs:`, `chore:`) and no multi-line bullet-point bodies.

Good examples:
- `add runbook crud backend`
- `link incidents to recent deployments`
- `add runbooks tab to dashboard`
- `update readme and project state`
- `add runbook migration`

Bad examples (too structured, looks AI-generated):
- `feat(backend): add runbook model, schema, and storage CRUD`
- `feat(frontend): integrate runbooks into dashboard with tab navigation`
- `docs: update PROJECT_STATE, README, and add EXPLAIN_TO_FRIEND`

Rule: single line, imperative mood, lowercase, like you'd type quickly in a terminal.
