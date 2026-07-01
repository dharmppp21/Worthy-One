# SignalForge — Auto-Discovery Interview Deep Dive

How to explain SignalForge's auto-discovery, health probing, event correlation, and dependency detection in a technical interview.

---

## 30-Second Pitch (Recruiter Screen)

> "SignalForge has an auto-discovery engine that detects services across Docker, Kubernetes, and cloud environments without any manual configuration. It scans containers, pods, and processes, probes their health, classifies their type, and automatically correlates telemetry events to them. It also detects service dependencies in real time and pushes everything to a live dashboard via WebSocket."

---

## 2-Minute Introduction (Hiring Manager)

> "SignalForge's auto-discovery feature solves the problem of manually registering services in a monitoring system. In a microservices environment, services come and go — containers restart, pods scale, new versions deploy. Manual registration doesn't work at scale.
>
> The discovery engine auto-detects the runtime environment — Docker, Kubernetes, AWS, Azure, or bare metal — and configures the right providers. It scans containers, pods, listening processes, and cloud metadata concurrently. Each discovered service is probed for health on common endpoints like `/health` and `/healthz`. The prober also classifies the service type — database, cache, API, web — using 7 layers of heuristics.
>
> When telemetry events arrive, the correlation engine automatically links them to discovered services by name, IP, container ID, or pod name. This means you don't need to manually tag every event with a service name.
>
> The dashboard shows a live feed of discovery events — new services, health changes, dependency detection — all in real time."

---

## 5-Minute Technical Deep Dive (Engineering Interview)

### The Discovery Engine Architecture

> "The discovery engine has three main components: providers, the engine, and the registry.
>
> **Providers** are pluggable. We have five: Docker, Kubernetes, Process, Config, and Cloud. Each implements the `ServiceDiscoveryProvider` interface with two methods: `health_check()` and `discover()`. Providers run concurrently via `asyncio.gather` so a slow Docker scan doesn't block a fast config read.
>
> **The engine** (`DiscoveryEngine`) orchestrates providers, deduplicates results by `(service_name, host)`, and publishes events to a WebSocket publisher. It also runs a background loop every 30 seconds and removes stale services after 120 seconds.
>
> **The registry** (`ServiceRegistry`) persists discovered services to PostgreSQL and keeps an in-memory cache. When a service is discovered, it either creates a new row or updates the existing one based on `(service_name, host)`. The cache syncs with the DB on every read."

### Health Probing and Auto-Classification

> "The `ServiceProber` probes every discovered service. For services on HTTP ports (80, 443, 8080, 3000, 5000, 8000), it tries 8 common health endpoints: `/health`, `/healthz`, `/ready`, `/alive`, `/status`, `/actuator/health`, `/api/health`, `/health/check`. It parses JSON responses for a `status` field — `up`, `healthy`, `ok` mean up; `down`, `unhealthy` mean down.
>
> For non-HTTP services, it does a TCP connect with a 3-second timeout. All probes run concurrently.
>
> **Classification** uses 7 layers of heuristics, in priority order:
> 1. Kubernetes `app.kubernetes.io/component` label
> 2. Docker image keyword (e.g., `postgres` → `database`)
> 3. Process name keyword (e.g., `nginx` → `web`)
> 4. HTTP framework detection from response body (e.g., `FastAPI` in body → `python_api`)
> 5. Known port mapping (e.g., 5432 → `database`, 6379 → `cache`)
> 6. Content-Type inference (HTML → `web`, JSON → `api`)
> 7. Fallback to `unknown`
>
> This classification is important because the correlation engine uses `service_type` to disambiguate multiple candidates."

### Event-to-Service Correlation

> "The `EventServiceCorrelator` matches telemetry events to discovered services. It tries 7 strategies in order:
>
> 1. **Exact name match** — `event.service_name` matches a discovered service. Confidence = 1.0.
> 2. **Source IP + port** — `event.attributes.source_ip` and `source_port` match a service endpoint. Confidence = 0.95 (or 0.8 if disambiguation needed).
> 3. **Hostname** — `event.attributes.hostname` matches `service.host`. Confidence = 0.9.
> 4. **Container ID** — `event.attributes.container_id` matches `service.metadata.container_id`. Confidence = 0.95.
> 5. **Pod name** — `event.attributes.pod_name` matches `service.metadata.pod_name`. Confidence = 0.95.
> 6. **Process ID** — `event.attributes.process_id` matches `service.metadata.pid`. Confidence = 0.9.
> 7. **Trace context** — `event.attributes.parent_span_service` matches a service name. Confidence = 0.85.
>
> If multiple candidates match, the disambiguator prefers the service with the most recent heartbeat, then the one whose `service_type` matches the event type. The result is a `CorrelationResult` with `service_id`, `confidence`, `strategy`, and `matched_field`."

### Dependency Detection

> "We detect dependencies in three ways:
>
> 1. **Trace analysis** — Parse trace events (Jaeger, Zipkin, or mock) to extract parent-child span relationships. If `checkout-service` calls `payment-service`, we create a dependency edge.
> 2. **Traffic log analysis** — Parse HTTP access logs (nginx, Envoy, or JSON) to extract caller-callee relationships from request paths and status codes.
> 3. **Network scanning** — Scan open ports and correlate them with discovered services to build a network topology.
>
> Dependencies are stored in PostgreSQL with a `severity` score (based on call frequency and error rate) and exposed via `GET /services/dependencies`. The dashboard renders them as a D3 force-directed graph."

### Real-Time WebSocket Feed

> "The `DiscoveryEventPublisher` is a singleton that maintains up to 100 WebSocket connections. When a discovery event occurs — new service, health change, dependency detected, service removed — it broadcasts a JSON message to all clients. The frontend `DiscoveryEventFeed` component shows these events with color-coded severity, event type filtering, and pause/resume."

---

## 15-Minute System Design Deep Dive (Senior/Staff Interview)

### Why Pluggable Providers?

> "The provider pattern decouples the discovery engine from environment-specific logic. Each provider is a single responsibility: Docker provider knows the Docker API, Kubernetes provider knows the K8s API, Process provider knows `psutil`. The engine doesn't care how services are found — it just calls `discover()` and gets a list of `DiscoveredService` objects.
>
> This means adding a new environment is one file: implement `health_check()` and `discover()`, register it in `EnvironmentDetector`, and the engine picks it up automatically. We could add a Consul provider, an etcd provider, or a Consul Connect mesh provider without touching the engine or registry."

### How Does the Engine Handle Provider Failures?

> "Each provider is wrapped in `_safe_discover()` with a try/except. If Docker is down, the provider returns an empty list and logs an error. The engine continues with other providers. The `health_check()` method is called before registration to skip unavailable providers entirely.
>
> This is important because in a mixed environment, you might have Docker and Kubernetes running but cloud metadata temporarily unreachable. The engine should still discover what it can."

### Why PostgreSQL + In-Memory Cache for the Registry?

> "PostgreSQL is the source of truth for discovered services. It survives restarts, supports queries, and integrates with the existing tenant isolation model. But reading from PostgreSQL on every correlation or probe would be slow. So the registry keeps an in-memory cache that syncs with the DB on every read.
>
> The cache is keyed by `service_id`. When `register_service()` is called, it writes to the DB and updates the cache. When `list_services()` is called, it rebuilds the cache from the query result. This gives us sub-millisecond reads for the hot path (correlation, probing) while keeping durability."

### How Do You Prevent Stale Services?

> "The background discovery loop calls `remove_stale()` with a timeout of `interval * 3` (default 90 seconds). A service whose `last_heartbeat_at` is older than the timeout is marked `is_active = False` in the DB and removed from the cache. A WebSocket event is published so the dashboard knows the service disappeared.
>
> This handles the case where a container crashes, a pod is evicted, or a process is killed. The service doesn't disappear immediately — it has a grace period — but it won't be correlated or probed after that."

### How Do You Scale Discovery?

> "Discovery is designed to be lightweight. Each provider runs once every 30 seconds. Probing runs every 15 seconds. For a typical cluster of 50–100 services, this is negligible load.
>
> If we needed to scale to 10,000 services, I'd:
> 1. Shard discovery by namespace or cluster — each SignalForge instance discovers a subset.
> 2. Cache provider results in Redis instead of memory to share across instances.
> 3. Use a dedicated discovery worker pool instead of the main API process.
> 4. Add a gossip protocol for peer-to-peer service announcement instead of scanning.
>
> But for the current scale, the single-instance engine with background tasks is sufficient."

### Why 7 Correlation Strategies?

> "Each strategy handles a different source of telemetry. A metric from Prometheus might have `pod_name`. A log from Fluent Bit might have `container_id`. A trace from Jaeger might have `parent_span_service`. A metric from StatsD might only have `source_ip`. By trying all 7, we maximize the chance of matching an event to a service without requiring the client to change their telemetry format.
>
> The confidence scores are explicit: exact name = 1.0, container ID = 0.95, trace context = 0.85. This means downstream consumers can decide to trust high-confidence matches and flag low-confidence ones for review."

### What About False Positives in Correlation?

> "The disambiguator handles ambiguous matches by preferring the most recent heartbeat and matching `service_type` to the event type. If two services share the same IP (e.g., behind a load balancer), the confidence drops to 0.8 and the `candidate_count` is set > 1. The dashboard shows this as a low-confidence match.
>
> In the future, we could add a Bayesian model that weights recent matches, but for now, the heuristic disambiguator handles 95%+ of cases correctly based on the performance benchmarks."

---

## Common Interview Questions

### Q: Why not just use Prometheus service discovery?

> "Prometheus has excellent service discovery for metrics, but it's metrics-only. SignalForge needs to discover services for logs, traces, and deployments too. And we need to classify service types, probe health, and correlate events — not just scrape endpoints. Prometheus discovery is a subset of what we do."

### Q: How do you handle network partitions?

> "If a network partition occurs, the prober will mark services on the other side as `down` or `unknown`. But the service remains in the registry with `is_active = True` until the stale timeout (90s). If the partition heals, the next probe run will mark it `up` again and publish a `health_changed` event.
>
> During the partition, events from the partitioned service won't be correlated by IP/port because the source IP may be unreachable. But they might still match by name or trace context if the event reaches the API via a different path."

### Q: How do you secure the Docker socket mount?

> "In production, we disable `process` discovery and use a read-only Docker socket where possible. The Docker provider only needs `list` and `inspect` permissions, not `exec` or `run`. In Kubernetes, we use a dedicated `ServiceAccount` with a minimal `Role` (pods/services get/list only). In ECS, we don't mount the socket at all — we use the cloud metadata API."

### Q: How do you test discovery across environments?

> "We have mocked integration tests for each provider: Docker SDK is mocked with `MagicMock`, Kubernetes client is mocked with a custom `MockApiClient`, psutil is mocked with synthetic process data. We also have mixed-environment tests that simulate a cluster with both Docker and Kubernetes services. All tests run in CI with zero external dependencies."

### Q: What's the performance of the correlation engine?

> "The correlation engine averages <5ms per event in our benchmarks (1000 events, 100 services). The registry cache is the key — without it, each correlation would query PostgreSQL. With the cache, it's an in-memory dictionary lookup. The performance tests use deterministic mock data with `seed=42` and repeat each benchmark 100 times for stability."

### Q: How would you add a Consul provider?

> "I'd create a `ConsulDiscoveryProvider` class that implements `health_check()` (check Consul agent HTTP endpoint) and `discover()` (query Consul's `/v1/catalog/services` and `/v1/health/service/{name}`). The provider would return `DiscoveredService` objects with `discovery_source='consul'`. Then I'd register it in `EnvironmentDetector` if `CONSUL_HTTP_ADDR` is present. No changes to the engine or registry."

---

## One-Page Cheat Sheet

| Component | Key Classes | What It Does |
|-----------|------------|--------------|
| Discovery Engine | `DiscoveryEngine` | Orchestrates providers, deduplicates, publishes events |
| Providers | `DockerDiscoveryProvider`, `KubernetesDiscoveryProvider`, `ProcessDiscoveryProvider`, `ConfigDiscoveryProvider`, `CloudDiscoveryProvider` | Environment-specific service scanning |
| Registry | `ServiceRegistry` | Persists to PostgreSQL, caches in memory |
| Prober | `ServiceProber` | HTTP/TCP health checks, protocol detection, classification |
| Correlator | `EventServiceCorrelator` | 7-strategy event-to-service matching |
| Dependencies | `DependencyGraphBuilder`, `TraceAnalyzer`, `TrafficAnalyzer` | Service dependency detection |
| WebSocket | `DiscoveryEventPublisher` | Real-time broadcast of discovery events |
| Frontend | `DiscoveryEventFeed`, `ServiceDetailsPanel` | Live event feed and service detail UI |

| Provider | Prerequisites | Security |
|----------|--------------|----------|
| Docker | `docker` SDK, socket mount | Read-only socket, no `exec` |
| Kubernetes | `kubernetes` SDK, RBAC | `get`/`list` pods/services only |
| Process | `psutil` | Blocklists system processes |
| Config | None | Env var or file — no external access |
| Cloud | `boto3`, `requests` | Instance metadata only |

| Correlation Strategy | Confidence | Typical Source |
|---------------------|------------|---------------|
| Exact name | 1.0 | Metrics with explicit labels |
| Source IP + port | 0.95 | Network logs, Sysdig |
| Hostname | 0.9 | Host-level metrics |
| Container ID | 0.95 | Docker logs, container metrics |
| Pod name | 0.95 | Kubernetes logs, kube-state-metrics |
| Process ID | 0.9 | APM agents, process monitors |
| Trace context | 0.85 | Jaeger, Zipkin traces |
