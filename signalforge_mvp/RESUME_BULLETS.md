# SignalForge — Resume Bullet Points

Copy-paste ready bullet points for your resume, LinkedIn, or portfolio. Each bullet is designed to pass ATS screening and impress technical interviewers.

---

## Full-Stack / Backend Engineer

- **Built a production-ready incident management platform** (SignalForge) in 49 days using FastAPI, React, PostgreSQL, Redis, and Kafka — 341 tests, load-tested at 47.7 RPS, deployable to AWS via ECS Fargate or Kubernetes.

- **Designed a multi-provider auto-discovery engine** that detects services across Docker, Kubernetes, AWS, Azure, and GCP without manual configuration. Uses environment auto-detection, concurrent provider execution, and deduplication by `(service_name, host)`.

- **Implemented health probing and auto-classification** with HTTP/TCP probes, 8 common health endpoint patterns, and 7-layer heuristic classification (K8s labels → Docker image → process name → framework detection → port mapping → content-type inference → fallback).

- **Built an event-to-service correlation engine** with 7 strategies (exact name, source IP/port, hostname, container ID, pod name, process ID, trace context) that automatically links telemetry events to discovered services without client-side `service_name`.

- **Implemented decoupled ingestion architecture** where the API returns `202 Accepted` in ~15ms and worker processors handle DB writes, Redis hot state, anomaly detection, and incident creation asynchronously via Kafka — supports backpressure and horizontal scaling.

- **Created a 3-layer consistency model** with PostgreSQL (strongly consistent, source of truth), Redis (eventually consistent hot state for sub-millisecond rolling windows), and Kafka (at-least-once delivery with idempotent consumer processing).

- **Built rule-based anomaly detection** on rolling windows with configurable thresholds (20 samples, 50% error rate = critical), producing structured evidence with sample count, error rate, avg/p95 latency, and breached thresholds.

- **Implemented 5-dimension root-cause scoring** (deployment recency, anomaly severity, error logs, trace failures, runbook coverage) that ranks hypotheses 0–100 with explainable evidence per dimension — no LLM required.

- **Designed AI triage with structured output** and graceful fallback: OpenAI API → local sentence-transformers model → deterministic mock provider. Produces summary, likely causes, evidence points, suggested actions, and confidence score.

- **Built semantic search via pgvector** with 1536-dimension embeddings, cosine similarity (`<=>` operator), and transparent fallback to keyword search when embedding services are unavailable.

- **Implemented real-time WebSocket updates** for both incident feeds and discovery events using Redis pub/sub, decoupling the incident engine from the WebSocket handler — they never need to know about each other.

- **Wrote 341 tests** covering anomaly detection, event processor pipeline, incident lifecycle, auth, integration (ingest-to-incident, graph, runbooks, search), multi-environment discovery (Docker, K8s, bare metal, mixed), performance benchmarks, and health probing — all passing in <3 seconds.

- **Load-tested the system** at 47.7 RPS ingest throughput with 0 errors (20 concurrent), 784ms incident detection delay, and 13–17ms API read latency. Identified SQLite single-writer bottleneck and documented PostgreSQL upgrade path to 500+ RPS.

- **Containerized the full stack** with Docker Compose (dev + prod overrides), Helm charts for Kubernetes (with RBAC, optional subcharts, HPA), and Terraform modules for AWS (EKS + ECS, RDS, ElastiCache, MSK, ALB, CloudFront).

- **Implemented production hardening** including API key auth with tenant isolation, in-memory sliding-window rate limiting (100 RPS), structured key=value logging, safe 500 responses (no stack traces), deep health checks, and centralized environment configuration.

---

## SRE / Platform Engineer

- **Built an auto-discovery platform** that detects services across Docker, Kubernetes, and cloud environments without manual registration. Uses concurrent provider execution, health probing, and 7-layer service classification.

- **Designed health probing infrastructure** with HTTP/TCP probes, protocol detection (HTTP/2, gRPC, raw TCP), and auto-classification. Probes run concurrently every 15s with configurable intervals and stale service cleanup.

- **Implemented environment-aware discovery** that auto-detects Docker, Kubernetes, AWS ECS/EKS, Azure, and GCP, then configures the appropriate providers. Supports override via `SIGNALFORGE_DISCOVERY_PROVIDERS`.

- **Built real-time service dependency detection** using trace analysis, traffic log parsing, and network scanning. Dependencies are stored in PostgreSQL with severity scoring and exposed via REST API and WebSocket events.

- **Created multi-environment integration tests** for Docker, Kubernetes, bare metal, and mixed environments with mocked Docker SDK, Kubernetes client, and psutil. All tests run in CI with mocked external dependencies.

- **Implemented performance benchmarks** for discovery (100 services in <10s), correlation (avg <5ms), and graph queries (<100ms) with deterministic mock data and memory profiling via `tracemalloc`.

- **Deployed infrastructure as code** with Terraform modules (VPC, EKS, ECS, RDS, ElastiCache, MSK, ALB, CloudFront, IAM) and Helm charts (Deployment, Service, ConfigMap, RBAC, HPA, Ingress).

- **Designed graceful degradation** for every external dependency: Kafka down → sync processing, Redis down → PostgreSQL fallback, OpenAI down → local model → mock provider, embedding service down → keyword search.

---

## Data / ML Engineer

- **Built an event correlation engine** with 7 matching strategies and confidence scoring (0.0–1.0) that automatically links telemetry events to discovered services by name, IP, container ID, pod name, or process ID.

- **Implemented semantic search** with 1536-dimension embedding vectors stored in PostgreSQL via pgvector, using cosine similarity for concept matching. Falls back to keyword search transparently.

- **Designed rule-based anomaly detection** with rolling-window analysis, configurable thresholds per severity level, and structured evidence generation. No training data required — explainable and deterministic.

- **Built a 5-dimension root-cause scoring engine** (deployment, anomaly, logs, traces, runbooks) that produces ranked hypotheses with traceable evidence. Confidence levels: high ≥70, medium 40–69, low <40.

- **Implemented AI triage with structured output** and cascading fallback: OpenAI → sentence-transformers → deterministic mock. Produces summary, likely causes, evidence points, suggested actions, and confidence score.

- **Created deterministic performance benchmarks** with seeded mock data (seed=42) for discovery latency, correlation accuracy, memory footprint, and graph query performance with repeat-run stability.

---

## Frontend Engineer

- **Built a React dashboard** with real-time incident cards, service graph visualization (D3 force-directed), runbook CRUD, semantic search toggle, root-cause panel, AI triage display, and discovery event feed.

- **Implemented real-time WebSocket feeds** for both incident updates and discovery events using TanStack Query for caching, refetching, and loading states. No `useEffect` spaghetti.

- **Created a discovery event feed component** with pause/resume, event type filtering (service discovered, health changed, dependency detected), color-coded severity, and auto-scroll.

- **Built a service details panel** with tabbed navigation (overview, incidents, dependencies, runbooks, metadata) that fetches related data on-demand via TanStack Query.

- **Designed responsive UI** with severity color coding (critical=red, warning=orange, info=blue), status badges, timeline visualization, and error states for all API tabs.

---

## One-Line Summaries

- **Backend:** "Built a production-ready incident management platform with auto-discovery, health probing, event correlation, and 341 tests — load-tested at 47 RPS."
- **SRE:** "Designed an auto-discovery platform that detects services across Docker, K8s, and cloud with zero manual configuration."
- **Full-Stack:** "Shipped a complete incident management system with React dashboard, FastAPI backend, and auto-discovery in 49 days."
- **Data/ML:** "Implemented event correlation, semantic search, and explainable AI triage with structured output and graceful fallback chains."

---

## Interview Talking Points (30 Seconds Each)

### Auto-Discovery
> "SignalForge auto-discovers services across environments. In Docker, it scans containers. In Kubernetes, it reads pods and services. On bare metal, it checks listening processes. It auto-detects the environment and picks the right providers. No manual config needed."

### Health Probing
> "Once a service is discovered, the prober runs HTTP health checks on common endpoints like `/health`, `/healthz`, `/actuator/health`. If those fail, it falls back to TCP connect. It classifies the service type using 7 layers of heuristics — K8s labels, Docker image, process name, framework detection, port mapping, content-type, and fallback."

### Event Correlation
> "When a telemetry event arrives without a clear service name, the correlation engine tries 7 strategies: exact name match, source IP + port, hostname, container ID, pod name, process ID, and trace context. Each match has a confidence score. This means events from unknown sources can still be linked to the right service."

### Why 341 Tests
> "I wrote 341 tests because the system has many moving parts: anomaly detection, event processing, auth, integration, discovery, health probing, correlation, and performance. Every provider has mocked integration tests. Every scale test uses deterministic data. I treat tests as documentation — they show how the system behaves under every condition."
