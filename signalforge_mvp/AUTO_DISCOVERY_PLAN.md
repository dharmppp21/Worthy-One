# SignalForge Auto-Discovery Enhancement Plan

## Overview

Transform SignalForge from a hardcoded 5-service demo into a **generic, auto-discovering incident management platform** that can be deployed on any system or application without requiring manual configuration of service names, dependencies, or topology.

**Resume impact:** "Built an auto-discovering, zero-config incident management platform that detects services and their dependencies across bare metal, VMs, containers, and Kubernetes — no manual configuration required."

---

## Phase 1: Service Discovery Architecture (Day 32-34)

### 1.1 Service Discovery Abstraction Layer

**Goal:** Create a pluggable service discovery system that can detect services from multiple sources.

**Components:**
- `ServiceDiscoveryProvider` (abstract base class)
- `ProcessDiscoveryProvider` (scan system processes, ports, network connections)
- `DockerDiscoveryProvider` (query Docker daemon for containers)
- `KubernetesDiscoveryProvider` (query Kubernetes API for pods/services)
- `CloudDiscoveryProvider` (query AWS ECS/EKS, Azure AKS, GCP GKE APIs)
- `ConfigDiscoveryProvider` (fallback: read from config file or environment variables)
- `ManualDiscoveryProvider` (fallback: admin-defined static list)

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Service Discovery Engine                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │   Process   │ │   Docker    │ │ Kubernetes  │               │
│  │   Scanner   │ │   Scanner   │ │   Scanner   │               │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘               │
│         │               │               │                      │
│         └───────────────┼───────────────┘                      │
│                         ▼                                        │
│              ┌─────────────────┐                              │
│              │  Service Registry  │                              │
│              │  (in-memory +     │                              │
│              │   PostgreSQL)     │                              │
│              └─────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

**What it discovers per service:**
- `service_id` (auto-generated UUID)
- `service_name` (derived from process name, container image, k8s service name, or hostname)
- `service_type` (web, api, database, cache, queue, worker, etc.)
- `endpoints` (HTTP ports, gRPC ports, exposed URLs)
- `host` (IP address, hostname, container ID, pod name)
- `metadata` (version, environment, labels, annotations)
- `health_check_url` (auto-detected or inferred)
- `discovery_source` (process/docker/kubernetes/cloud/config/manual)
- `first_seen_at`, `last_seen_at`, `last_heartbeat_at`

**Implementation Prompt:**

> "Create a pluggable service discovery system in `backend/app/discovery/`.
> 
> 1. Create `backend/app/discovery/base.py` with an abstract `ServiceDiscoveryProvider` class that has `async def discover(self) -> List[DiscoveredService]` and `async def health_check(self) -> bool` methods.
> 
> 2. Create `backend/app/discovery/models.py` with `DiscoveredService` Pydantic model containing: service_id, service_name, service_type, endpoints, host, metadata, health_check_url, discovery_source, timestamps.
> 
> 3. Create `backend/app/discovery/registry.py` with `ServiceRegistry` class that stores discovered services in PostgreSQL (with an `discovered_services` table) and provides in-memory caching for fast lookups. Include methods: `register_service()`, `get_service()`, `list_services()`, `update_heartbeat()`, `remove_stale_services(timeout_seconds)`.
> 
> 4. Create `backend/app/discovery/providers/process.py` that scans the local system for processes listening on network ports. Use `psutil` library. Map process names to service names (e.g., 'python app.py' -> 'python-app', 'nginx' -> 'nginx', 'postgres' -> 'postgres'). Detect ports using `psutil.process_connections()`. Include process PID, command line, and listening ports in metadata.
> 
> 5. Create `backend/app/discovery/providers/docker.py` that queries the Docker daemon via the Docker SDK for Python. Discover containers, their names, images, exposed ports, networks, and labels. Map container names to service names.
> 
> 6. Create `backend/app/discovery/providers/kubernetes.py` that queries the Kubernetes API using `kubernetes` Python client. Discover pods, services, deployments. Extract service names from pod labels (e.g., `app=checkout-service`), service names from k8s Service objects, and endpoints from container ports. Include namespace, cluster name, and pod labels in metadata.
> 
> 7. Create `backend/app/discovery/providers/config.py` that reads from a YAML/JSON config file or environment variables. This is the fallback when no auto-discovery source is available. Support `SIGNALFORGE_SERVICES` env var as a JSON string.
> 
> 8. Create `backend/app/discovery/engine.py` with `DiscoveryEngine` that runs all configured providers in parallel (asyncio.gather), merges results (deduplicates by service_name + host), and updates the registry. Include a background task that runs discovery every 30 seconds.
> 
> 9. Add a `discovered_services` table to SQLAlchemy models with: id, service_id, service_name, service_type, endpoints (JSON), host, metadata (JSON), health_check_url, discovery_source, is_active, first_seen_at, last_seen_at, last_heartbeat_at, tenant_id.
> 
> 10. Add `GET /services/discovered` endpoint that returns all auto-discovered services with their health status.
> 
> 11. Add `POST /services/discover` endpoint that triggers an on-demand discovery run.
> 
> 12. Write tests for each provider using mocks (mock psutil, mock docker client, mock kubernetes client). Test deduplication logic. Test registry CRUD operations."

---

### 1.2 Environment Detection & Auto-Configuration

**Goal:** Automatically detect the deployment environment and configure the appropriate discovery providers.

**Environment Detection:**
- Detect if running in Docker (check `/proc/1/cgroup` for 'docker')
- Detect if running in Kubernetes (check for `KUBERNETES_SERVICE_HOST` env var)
- Detect if running in ECS (check for `AWS_EXECUTION_ENV` env var)
- Detect if running in EKS (check for `KUBERNETES_SERVICE_HOST` + AWS metadata)
- Detect if running in VM/bare metal (default to process discovery)
- Detect cloud provider (AWS: check metadata endpoint; Azure: check `AZURE_*` env vars; GCP: check `GOOGLE_*` env vars)

**Implementation Prompt:**

> "Create `backend/app/discovery/environment.py` that auto-detects the deployment environment.
> 
> 1. Create `EnvironmentDetector` class with methods:
>    - `is_docker()`: Check `/proc/1/cgroup` for 'docker' or '.docker'
>    - `is_kubernetes()`: Check for `KUBERNETES_SERVICE_HOST` env var
>    - `is_aws_ecs()`: Check for `AWS_EXECUTION_ENV` containing 'AWS_ECS'
>    - `is_aws_eks()`: Check `is_kubernetes()` + AWS metadata endpoint (`http://169.254.169.254/latest/meta-data/`) OR check for `AWS_WEB_IDENTITY_TOKEN_FILE` (IRSA)
>    - `is_azure()`: Check for `AZURE_*` env vars or Azure metadata endpoint
>    - `is_gcp()`: Check for `GOOGLE_*` env vars or GCP metadata endpoint
>    - `is_vm()`: Default fallback when none of the above
>    - `get_cloud_provider()`: Returns 'aws', 'azure', 'gcp', or None
>    - `get_discovery_providers()`: Returns list of provider class names based on environment (e.g., ['kubernetes', 'docker', 'process'] for EKS; ['process', 'config'] for bare metal)
> 
> 2. Create `AutoConfigurator` class that configures the discovery engine based on detected environment. It should:
>    - Read `SIGNALFORGE_DISCOVERY_ENABLED` env var (default: true)
>    - Read `SIGNALFORGE_DISCOVERY_INTERVAL` env var (default: 30 seconds)
>    - Read `SIGNALFORGE_DISCOVERY_PROVIDERS` env var (override auto-detection)
>    - Instantiate the correct providers based on environment
>    - Configure provider-specific settings (e.g., k8s namespace, docker socket path)
> 
> 3. Write tests for environment detection using monkeypatch for env vars and mock filesystem for cgroup files."

---

## Phase 2: Dependency Auto-Discovery (Day 35-38)

### 2.1 Network Dependency Detection

**Goal:** Automatically detect which services talk to which other services by analyzing network connections.

**Techniques:**
- **Active:** Network connection scanning (who connects to whom)
- **Passive:** Traffic analysis (DNS requests, HTTP host headers, connection logs)
- **Trace-based:** Distributed tracing headers (traceparent, x-request-id)
- **Log-based:** Parse application logs for outgoing HTTP/gRPC/DB calls
- **Proxy-based:** Service mesh sidecar (Envoy/Istio) telemetry
- **eBPF:** Kernel-level network tracing (advanced, Linux-only)

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                 Dependency Detection Engine                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │   Network   │ │   Traffic   │ │   Trace     │               │
│  │   Scanner   │ │   Analyzer  │ │   Analyzer  │               │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘               │
│         │               │               │                      │
│         └───────────────┼───────────────┘                      │
│                         ▼                                        │
│              ┌─────────────────┐                              │
│              │ Dependency Graph  │                              │
│              │ Builder          │                              │
│              └─────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation Prompt:**

> "Create `backend/app/discovery/dependencies/` for automatic dependency detection.
> 
> 1. Create `backend/app/discovery/dependencies/models.py` with:
>    - `ServiceDependency` Pydantic model: source_service_id, target_service_id, dependency_type (http, grpc, database, cache, message_queue, unknown), connection_count, avg_latency_ms, error_rate, last_seen_at, confidence_score (0.0-1.0)
>    - `DependencyGraph` model: nodes (services), edges (dependencies with metadata)
> 
> 2. Create `backend/app/discovery/dependencies/network_scanner.py`:
>    - `NetworkConnectionScanner` class that uses `psutil.net_connections()` to find established connections between processes
>    - Map source process (PID) to service via ServiceRegistry
>    - Map target IP:port to service via ServiceRegistry (match by endpoint)
>    - Record dependency with type inference (port 5432 -> PostgreSQL, port 6379 -> Redis, port 9092 -> Kafka, port 80/443 -> HTTP)
>    - Run as background task every 30 seconds
>    - Include connection count and direction (outgoing vs incoming)
> 
> 3. Create `backend/app/discovery/dependencies/traffic_analyzer.py`:
>    - `TrafficAnalyzer` class that reads application logs or HTTP access logs
>    - Parse HTTP access logs for outgoing requests (e.g., 'GET http://payment-service:8080/api')
>    - Parse DNS query logs for service name resolution (e.g., 'payment-service.svc.cluster.local')
>    - Extract target service names from URLs, host headers, connection strings
>    - Support log formats: nginx, apache, application JSON logs, Kubernetes DNS logs
>    - Configurable log file paths via env var `SIGNALFORGE_LOG_PATHS`
> 
> 4. Create `backend/app/discovery/dependencies/trace_analyzer.py`:
>    - `TraceAnalyzer` class that reads distributed tracing data
>    - Parse `traceparent` and `tracestate` headers from HTTP logs or tracing backend (Jaeger, Zipkin, Tempo)
>    - Extract service names from span metadata (e.g., 'service.name' tag in OpenTelemetry)
>    - Build parent-child relationships from span references
>    - Support OpenTelemetry format, Jaeger Thrift, Zipkin JSON
>    - Configurable tracing backend URL via `SIGNALFORGE_TRACING_BACKEND_URL`
> 
> 5. Create `backend/app/discovery/dependencies/mesh_analyzer.py`:
>    - `ServiceMeshAnalyzer` class that reads Istio/Envoy metrics
>    - Query Prometheus for Istio metrics (e.g., `istio_requests_total` with source_app and destination_app labels)
>    - Query Envoy admin endpoint (`/stats/prometheus`) for cluster metrics
>    - Extract source_service and destination_service from metric labels
>    - Include request count, error rate, latency from metrics
>    - Configurable Prometheus URL via `SIGNALFORGE_PROMETHEUS_URL`
> 
> 6. Create `backend/app/discovery/dependencies/graph_builder.py`:
>    - `DependencyGraphBuilder` class that merges data from all analyzers
>    - Deduplicate edges: if multiple analyzers detect the same dependency, merge and take highest confidence
>    - Calculate confidence score based on: number of analyzers that detected it, connection count, recency
>    - Store in `service_dependencies` table: id, source_service_id, target_service_id, dependency_type, connection_count, avg_latency_ms, error_rate, last_seen_at, confidence_score, discovery_sources (JSON), tenant_id
>    - Build `DependencyGraph` with methods: `get_upstream(service_id)`, `get_downstream(service_id)`, `get_critical_path()`, `detect_cycles()`
>    - Update graph every 60 seconds in background
> 
> 7. Add `GET /graph/auto` endpoint that returns the auto-discovered dependency graph (with confidence scores and filtering options: min_confidence, dependency_type)
> 
> 8. Add `GET /services/{service_id}/dependencies` endpoint that returns upstream and downstream dependencies for a specific service
> 
> 9. Write tests for each analyzer using mock data. Test graph builder deduplication and confidence scoring."

---

### 2.2 Telemetry Auto-Tagging & Service Correlation

**Goal:** When telemetry events are ingested, automatically correlate them to discovered services without requiring the client to specify `service_name`.

**Techniques:**
- **IP/Port matching:** Match event source IP to discovered service endpoints
- **Hostname matching:** Match event hostname to discovered service hostnames
- **Container ID matching:** Match Docker container ID to discovered container
- **Pod name matching:** Match Kubernetes pod name to discovered pod
- **Process ID matching:** Match process ID to discovered process
- **Trace context matching:** Use distributed trace IDs to correlate spans across services

**Implementation Prompt:**

> "Create `backend/app/discovery/correlation.py` for automatic event-to-service correlation.
> 
> 1. Create `EventServiceCorrelator` class that takes a `TelemetryEvent` and returns the best matching `service_id` from the ServiceRegistry.
> 
> 2. Matching strategies (in order of priority):
>    - Exact match on `service_name` field in event (if provided by client)
>    - Match on source IP + port from event metadata (if event contains `source_ip` and `source_port`)
>    - Match on hostname from event metadata (if event contains `hostname` or `host`)
>    - Match on container ID from event metadata (if event contains `container_id`)
>    - Match on pod name from event metadata (if event contains `pod_name`)
>    - Match on process ID from event metadata (if event contains `process_id`)
>    - Match on trace context: if event contains `trace_id`, look up other spans with same trace_id and infer service from parent/child spans
>    - Fallback: create an 'unknown-service' placeholder and queue for manual review
> 
> 3. Implement `correlate_event(event: TelemetryEvent) -> Optional[str]` that tries all strategies and returns the best match. Include a `confidence_score` for each match.
> 
> 4. Add `correlation_metadata` field to `TelemetryEvent` model: stores which strategy was used, the matched field, and the confidence score.
> 
> 5. Modify the `ingest.py` router to auto-correlate events if `service_name` is not provided or if `service_name` doesn't match any known service. Log a warning if correlation confidence is low.
> 
> 6. Add `GET /events/uncorrelated` endpoint that returns events that couldn't be correlated to any known service (for admin review).
> 
> 7. Write tests for each matching strategy using mock ServiceRegistry data."

---

## Phase 3: Zero-Config Deployment (Day 39-42)

### 3.1 Auto-Config Installation & Helm Chart

**Goal:** Provide a one-command installation that auto-detects the environment and configures everything.

**Deliverables:**
- `install.sh` — one-command installer for Linux/macOS
- `install.ps1` — one-command installer for Windows
- Helm chart for Kubernetes deployment
- Terraform module for AWS deployment (EKS + ECS)
- Docker Compose with auto-discovery enabled
- Kubernetes Operator (advanced, optional)

**Implementation Prompt:**

> "Create zero-config installation and deployment packages.
> 
> 1. Create `install/install.sh` (Linux/macOS installer):
>    - Detect OS and architecture (Linux x64, macOS arm64/x64)
>    - Detect environment (Docker, Kubernetes, bare metal, cloud)
>    - Install SignalForge binary or Docker image
>    - Generate auto-configuration based on detected environment
>    - Create systemd service or launchd plist for bare metal
>    - Output summary of detected services and configuration
>    - Support flags: `--version`, `--backend-only`, `--with-frontend`, `--discovery-only`, `--uninstall`
> 
> 2. Create `install/install.ps1` (Windows installer):
>    - Similar functionality for Windows
>    - Create Windows service using sc.exe or New-Service
>    - Support `--version`, `--backend-only`, `--with-frontend`, `--discovery-only`, `--uninstall`
> 
> 3. Create `helm/signforge/` Helm chart for Kubernetes:
>    - `Chart.yaml` with dependencies (optional PostgreSQL, Redis, Kafka subcharts)
>    - `values.yaml` with sensible defaults and auto-discovery enabled
>    - Templates: deployment, service, ingress, configmap, serviceaccount, rbac (for k8s API access), secret
>    - RBAC: ServiceAccount with permissions to read pods, services, endpoints, nodes, deployments
>    - ConfigMap: auto-generated discovery configuration based on namespace
>    - Support values: `discovery.enabled`, `discovery.kubernetes.namespace`, `discovery.kubernetes.clusterRole`, `persistence.enabled`, `postgresql.enabled`, `redis.enabled`, `kafka.enabled`
>    - `helm install signforge ./helm/signforge --namespace monitoring` should work out of the box
> 
> 4. Create `terraform/modules/signforge/` Terraform module for AWS:
>    - EKS deployment with IRSA (IAM Roles for Service Accounts) for k8s API access
>    - ECS deployment with service discovery
>    - RDS PostgreSQL instance
>    - ElastiCache Redis cluster
>    - MSK Kafka cluster (optional)
>    - ALB with path routing
>    - CloudWatch log group and metrics
>    - Outputs: service URL, database endpoint, Redis endpoint
>    - Variables: `cluster_name`, `vpc_id`, `subnet_ids`, `enable_kafka`, `enable_discovery`
> 
> 5. Update `docker-compose.yml` to include:
>    - `signforge-discovery` service that runs the discovery engine with appropriate volumes (`/var/run/docker.sock` for Docker discovery, host network mode for process discovery)
>    - Environment variables for auto-discovery: `SIGNALFORGE_DISCOVERY_ENABLED=true`, `SIGNALFORGE_DISCOVERY_INTERVAL=30`
>    - Comments explaining how to run on different environments
> 
> 6. Update `README.md` with new installation section: 'One-Command Installation' showing `curl -fsSL https://raw.githubusercontent.com/dharmppp21/signforge/main/install.sh | bash`
> 
> 7. Write installation tests (mock the download and verify generated config files)."

---

### 3.2 Service Health Probing & Auto-Classification

**Goal:** Automatically probe discovered services to classify their type and determine if they're healthy.

**Techniques:**
- **HTTP probing:** Try common health endpoints (`/health`, `/healthz`, `/ready`, `/alive`, `/status`, `/actuator/health`) on discovered HTTP ports
- **TCP probing:** Check if TCP ports are open (for databases, caches, message queues)
- **Protocol detection:** Detect protocol by sending probes and checking response (HTTP vs gRPC vs raw TCP)
- **Service classification:** Classify service type based on port, protocol, response content, and process name
  - Port 5432 + PostgreSQL protocol -> `database`
  - Port 6379 + Redis protocol -> `cache`
  - Port 9092 + Kafka protocol -> `message_queue`
  - Port 80/443 + HTTP -> `web` or `api` (check if HTML response vs JSON response)
  - Port 3000/5173 + HTTP -> `frontend`
  - Process name `nginx` -> `load_balancer`
  - Process name `envoy` -> `service_mesh_proxy`
  - Response contains `Spring Boot` -> `java_api`
  - Response contains `Express` or `Fastify` -> `nodejs_api`
  - Response contains `Django` or `Flask` -> `python_api`

**Implementation Prompt:**

> "Create `backend/app/discovery/probing.py` for automatic service health probing and classification.
> 
> 1. Create `ServiceProber` class with:
>    - `probe_http(service: DiscoveredService) -> HealthProbeResult`: Try common health endpoints (`/health`, `/healthz`, `/ready`, `/alive`, `/status`, `/actuator/health`) on each HTTP port. Return status (up/down), response time, response body (truncated to 1KB), and discovered endpoint path.
>    - `probe_tcp(service: DiscoveredService) -> HealthProbeResult`: Check TCP connection to each port. Return status and connection time.
>    - `detect_protocol(host: str, port: int) -> str`: Send HTTP request, check if response is HTTP. If not, try gRPC (HTTP/2 with specific headers). If not, return `raw_tcp`. Return detected protocol.
>    - `classify_service(service: DiscoveredService, probe_results: List[HealthProbeResult]) -> str`: Return service type based on: port (5432 -> database), protocol (Redis protocol -> cache), process name (nginx -> load_balancer), response content (Spring Boot -> java_api), or fallback to `unknown`.
>    - `probe_all_services()` that probes all discovered services in parallel (asyncio.gather with timeout). Update service health status in registry.
> 
> 2. Create `HealthProbeResult` Pydantic model: status (up/down/unknown), probe_type (http/tcp), endpoint, response_time_ms, response_status_code, response_body_preview, error_message, probed_at.
> 
> 3. Add `service_health` table to PostgreSQL: id, service_id, status (up/down/unknown), probe_results (JSON), last_probed_at, last_up_at, last_down_at, uptime_percentage, tenant_id.
> 
> 4. Add background task that probes all services every 15 seconds.
> 
> 5. Add `GET /services/health` endpoint that returns health status of all discovered services.
> 
> 6. Add `GET /services/{service_id}/health` endpoint that returns detailed health history for a service.
> 
> 7. Modify the incident engine to use auto-discovered health status when determining severity (e.g., if a critical service like database is down, escalate to P0).
> 
> 8. Write tests with mock HTTP server (httptest) and mock TCP sockets."

---

## Phase 4: Dashboard & Visualization (Day 43-45)

### 4.1 Auto-Generated Service Topology Dashboard

**Goal:** Visualize the auto-discovered service topology in real-time.

**Features:**
- Auto-generated service map (no manual configuration)
- Color-coded by health status (green=healthy, yellow=warning, red=critical, gray=unknown)
- Show dependency arrows with latency/error rate labels
- Click on service to see details: health history, incidents, runbooks, dependencies
- Auto-layout using force-directed graph or hierarchical layout
- Filter by: environment, namespace, service type, health status, dependency confidence
- Show/hide unknown-confidence dependencies (< 0.5)
- Real-time updates via WebSocket when new services are discovered or health changes

**Implementation Prompt:**

> "Update the frontend to visualize auto-discovered service topology.
> 
> 1. Create `frontend/src/components/ServiceTopologyMap.tsx`:
>    - Fetch auto-discovered services from `GET /services/discovered`
>    - Fetch auto-discovered dependency graph from `GET /graph/auto`
>    - Fetch health status from `GET /services/health`
>    - Use D3.js or React Flow to render interactive topology graph
>    - Nodes: auto-discovered services with icons based on service_type (database icon, cache icon, web icon, etc.). Color by health status (green/yellow/red/gray). Size by importance (critical services are larger).
>    - Edges: dependency arrows with labels showing latency and error rate. Color by confidence (solid for high confidence > 0.8, dashed for medium 0.5-0.8, dotted for low < 0.5). Animated edges for active traffic.
>    - Interactions: click to show service details panel (health, incidents, runbooks, dependencies), hover to show tooltip with quick stats, drag to rearrange, zoom and pan.
>    - Controls: filter by service_type, health_status, min_confidence, environment. Toggle auto-refresh (every 10 seconds). Toggle layout mode (force-directed, hierarchical, circular).
>    - WebSocket integration: listen for `service_discovered`, `service_health_changed`, `dependency_detected` events and update the graph in real-time.
> 
> 2. Create `frontend/src/components/ServiceDetailsPanel.tsx`:
>    - Tabbed panel showing: Health history (sparkline), Recent incidents (list), Upstream/downstream dependencies (mini graph), Runbooks (list with create button), Discovery metadata (source, first seen, endpoints).
>    - Actions: mark as ignored (exclude from monitoring), add manual runbook, view in logs.
> 
> 3. Update `App.tsx` to add a new 'Topology' tab that shows the `ServiceTopologyMap`.
> 
> 4. Add TypeScript types for all new API responses: `DiscoveredService`, `ServiceHealth`, `AutoDependencyGraph`, `HealthProbeResult`.
> 
> 5. Write tests for the topology map component (mock API responses, verify D3 rendering)."

---

### 4.2 Service Discovery Event Feed

**Goal:** Show a real-time event feed of discovery activities (like a security camera for your architecture).

**Implementation Prompt:**

> "Create a discovery event feed in the frontend.
> 
> 1. Create `frontend/src/components/DiscoveryEventFeed.tsx`:
>    - WebSocket connection to `/ws/discovery` endpoint (new WebSocket endpoint on backend)
>    - Real-time feed of discovery events: 'New service discovered: payment-service (Kubernetes pod)', 'Service health changed: database (down)', 'New dependency detected: checkout-service -> payment-service (confidence: 0.92)', 'Service disappeared: old-worker-3 (last seen 5 minutes ago)', 'Dependency removed: api-gateway -> deprecated-service (no connections for 10 minutes)'
>    - Each event has a timestamp, icon, severity (info/warning/critical), and detail link
>    - Auto-scroll to latest events, with pause button
>    - Filter by event type, severity, service name
>    - Show event count badges in the sidebar
> 
> 2. Create `backend/app/routers/discovery_ws.py` with WebSocket endpoint `/ws/discovery` that broadcasts discovery events to all connected clients. Events include: `service_discovered`, `service_removed`, `service_health_changed`, `dependency_detected`, `dependency_removed`.
> 
> 3. Add `DiscoveryEvent` model to schemas: event_type, service_id, service_name, detail, severity, timestamp, tenant_id.
> 
> 4. Write tests for WebSocket event broadcasting."

---

## Phase 5: Integration & Testing (Day 46-48)

### 5.1 Multi-Environment Testing Matrix

**Goal:** Test the auto-discovery system across multiple environments.

**Test Environments:**
- Docker Compose with 5+ services
- Local Kubernetes (kind/minikube) with 3+ microservices
- AWS ECS with Fargate tasks
- AWS EKS with pod-based services
- Bare metal with system processes

**Implementation Prompt:**

> "Create comprehensive integration tests for auto-discovery across environments.
> 
> 1. Create `tests/integration/test_discovery_docker.py`:
>    - Start a Docker Compose stack with 5 services (nginx, postgres, redis, a Python API, a Node.js API)
>    - Run SignalForge discovery engine
>    - Verify all 5 services are discovered within 60 seconds
>    - Verify dependencies are detected (e.g., Python API connects to Postgres and Redis)
>    - Verify health probes return correct status for each service
>    - Verify service classification is correct (nginx -> load_balancer, postgres -> database, etc.)
>    - Use Docker SDK to create/remove containers during test and verify dynamic discovery
> 
> 2. Create `tests/integration/test_discovery_kubernetes.py` (using kind/minikube or mocked k8s API):
>    - Create a namespace with 3 deployments (frontend, API, database)
>    - Run SignalForge with Kubernetes discovery provider
>    - Verify all 3 services are discovered
>    - Verify pod names are correctly mapped to service names
>    - Verify namespace filtering works
>    - Test RBAC: verify SignalForge fails gracefully without proper permissions
> 
> 3. Create `tests/integration/test_discovery_baremetal.py`:
>    - Mock `psutil` to simulate system processes
>    - Verify process-to-service name mapping works
>    - Verify port scanning detects listening services
>    - Verify connection tracking detects dependencies
> 
> 4. Create `tests/integration/test_dependency_graph.py`:
>    - Feed known telemetry events from 3 services with implicit dependencies
>    - Verify the dependency graph builder correctly identifies the relationships
>    - Verify confidence scores increase with repeated observations
>    - Verify graph topology matches expected structure (e.g., A -> B -> C)
> 
> 5. Create `tests/integration/test_event_correlation.py`:
>    - Send telemetry events with various metadata (IP, hostname, container ID, pod name)
>    - Verify each event is correctly correlated to the right service
>    - Verify uncorrelated events are captured and exposed via API
>    - Verify correlation confidence is stored and visible in dashboard"

---

### 5.2 Performance & Scalability Testing

**Goal:** Ensure auto-discovery works at scale (100+ services, 1000+ dependencies).

**Implementation Prompt:**

> "Create performance tests for auto-discovery at scale.
> 
> 1. Create `tests/performance/test_discovery_scale.py`:
>    - Simulate 100 services with 500 dependencies
>    - Measure discovery engine latency: time to complete one full discovery cycle
>    - Measure memory usage: ServiceRegistry with 100 services
>    - Measure database writes: time to persist 100 services + 500 dependencies
>    - Verify discovery cycle completes in < 10 seconds
>    - Verify memory usage stays < 200 MB
>    - Verify database writes complete in < 5 seconds
> 
> 2. Create `tests/performance/test_event_correlation_scale.py`:
>    - Simulate 1000 events per second from 100 different services
>    - Measure correlation latency: time to correlate one event
>    - Measure correlation accuracy: percentage of events correctly correlated
>    - Verify correlation latency < 1 ms per event
>    - Verify correlation accuracy > 95%
>    - Verify uncorrelated event queue doesn't grow unbounded (max 1000, then drop oldest)
> 
> 3. Create `tests/performance/test_graph_query_scale.py`:
>    - Query dependency graph with 100 services and 500 dependencies
>    - Measure query latency for: get_all_dependencies, get_upstream, get_downstream, get_critical_path
>    - Verify query latency < 100 ms for all operations
>    - Verify graph rendering data size < 1 MB for frontend transfer"

---

## Phase 6: Documentation & Polish (Day 49-50)

### 6.1 Documentation Updates

**Implementation Prompt:**

> "Update all documentation for the auto-discovery feature.
> 
> 1. Update `README.md`:
>    - Add 'Zero-Config Auto-Discovery' section at the top (key differentiator)
>    - Describe how SignalForge automatically detects services and dependencies
>    - List supported environments (bare metal, Docker, Kubernetes, AWS ECS, AWS EKS, Azure, GCP)
>    - Add quick-start section: 'Install SignalForge on any system in 5 minutes'
>    - Update architecture diagram to include discovery layer
>    - Add screenshots/ASCII art of the auto-generated topology map
> 
> 2. Update `ARCHITECTURE_SUMMARY.md`:
>    - Add discovery layer to the 3-layer architecture (now 4 layers: discovery, streaming, hot state, durable storage)
>    - Add discovery metrics to performance table (discovery cycle time, correlation accuracy)
>    - Add supported environments to tech stack
> 
> 3. Update `INTERVIEW_GUIDE.md`:
>    - Add talking points about auto-discovery: 'The biggest challenge in incident management is not detecting failures, but knowing what services exist and how they connect. SignalForge solves this by automatically discovering your architecture.'
>    - Add Q&A: 'How does it work on my system without configuration?' Answer: 'It scans processes, containers, or Kubernetes resources and builds the service graph automatically. No manual service lists or dependency maps needed.'
>    - Add Q&A: 'How does it handle 100+ microservices?' Answer: 'The discovery engine is designed for scale. It completes a full scan in under 10 seconds for 100 services. The correlation engine handles 1000+ events per second with 95%+ accuracy.'
>    - Update live demo script to include auto-discovery steps: 'Watch as SignalForge discovers services I didn't even know were running'
> 
> 4. Update `DEMO.md`:
>    - Add 'Auto-Discovery Demo' section: run SignalForge on a system with unknown services, watch it discover and map them
>    - Add commands: `curl /services/discovered`, `curl /graph/auto`, `curl /services/health`
>    - Show the auto-generated topology map in the dashboard
> 
> 5. Update `AWS_ARCHITECTURE.md`:
>    - Add IAM roles and permissions needed for AWS service discovery (ECS, EKS)
>    - Add Kubernetes RBAC requirements for pod/service discovery
>    - Add CloudWatch agent integration for log-based traffic analysis
> 
> 6. Create `docs/ENVIRONMENTS.md`:
>    - Detailed setup guides for each environment: Docker, Kubernetes (kind, EKS, GKE, AKS), bare metal, AWS ECS, Azure Container Instances, GCP Cloud Run
>    - Environment-specific configuration examples
>    - Troubleshooting section for each environment (common issues and solutions)
>    - Security considerations (RBAC, IAM roles, network policies)"

---

### 6.2 Resume & Interview Polish

**Implementation Prompt:**

> "Create final resume and interview materials for the auto-discovery feature.
> 
> 1. Create `RESUME_BULLETS.md`:
>    - 10-15 powerful resume bullets covering the auto-discovery enhancement
>    - Examples:
>      - 'Architected a zero-config auto-discovery engine that detects services, maps dependencies, and classifies service types across bare metal, Docker, Kubernetes, and AWS — no manual configuration required'
>      - 'Implemented multi-provider service discovery (process scanning, Docker API, Kubernetes API, cloud provider APIs) with environment auto-detection and pluggable architecture'
>      - 'Built network dependency detection using connection tracking, traffic analysis, distributed tracing, and service mesh telemetry to automatically infer service topology with confidence scoring'
>      - 'Designed event-to-service correlation engine with 95%+ accuracy using IP/port matching, hostname resolution, container/pod metadata, and trace context propagation'
>      - 'Created interactive auto-generated topology map with real-time health status, dependency confidence levels, and dynamic filtering — zero manual graph configuration'
>      - 'Delivered one-command installation (shell script, PowerShell, Helm, Terraform) with environment auto-detection and sensible defaults for any deployment target'
>      - 'Implemented automatic service health probing with protocol detection (HTTP/gRPC/TCP) and service classification (database/cache/queue/web) based on port, protocol, and response analysis'
> 
> 2. Create `INTERVIEW_AUTO_DISCOVERY.md`:
>    - 'How does SignalForge discover my services without configuration?' — deep dive into the multi-provider architecture and environment detection
>    - 'How does it map dependencies?' — explain the 4 techniques (network, traffic, trace, mesh) and confidence scoring
>    - 'What if I have 500 microservices?' — explain the scalability limits and performance numbers
>    - 'What if a service is ephemeral (serverless/spot instances)?' — explain how discovery handles short-lived services and removes stale entries
>    - 'How does it correlate events to services?' — explain the matching strategies and fallback handling
>    - 'What about security? Does it need cluster-admin?' — explain RBAC/IAM least-privilege requirements
>    - 'How accurate is the dependency graph?' — explain confidence scoring, validation, and manual override capabilities"

---

## Summary: New Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SignalForge (Auto-Discovery)                      │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                     Discovery Layer (NEW)                          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │  │
│  │  │ Process  │ │ Docker   │ │ K8s API  │ │ Cloud    │         │  │
│  │  │ Scanner  │ │ Scanner  │ │ Scanner  │ │ Scanner  │         │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘         │  │
│  │       └────────────┼────────────┼────────────┘                 │  │
│  │                    ▼            ▼                               │  │
│  │           ┌─────────────────────────┐                          │  │
│  │           │     Service Registry      │                          │  │
│  │           │  (auto-discovered svcs)   │                          │  │
│  │           └─────────────────────────┘                          │  │
│  │                    │                                              │  │
│  │  ┌──────────┐ ┌────┴────┐ ┌──────────┐ ┌──────────┐         │  │
│  │  │ Network  │ │ Traffic │ │ Trace    │ │ Service  │         │  │
│  │  │ Scanner  │ │ Analyzer│ │ Analyzer │ │ Mesh     │         │  │
│  │  └────┬─────┘ └────┬────┘ └────┬─────┘ └────┬─────┘         │  │
│  │       └────────────┼────────────┼────────────┘                 │  │
│  │                    ▼            ▼                               │  │
│  │           ┌─────────────────────────┐                          │  │
│  │           │   Dependency Graph      │                          │  │
│  │           │   (auto-inferred)       │                          │  │
│  │           └─────────────────────────┘                          │  │
│  │  ┌──────────┐ ┌──────────┐                                    │  │
│  │  │ Health   │ │ Event    │                                    │  │
│  │  │ Prober   │ │ Correlator│                                   │  │
│  │  └──────────┘ └──────────┘                                    │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│  ┌───────────────────────────┼──────────────────────────────────────┐  │
│  │                   Core SignalForge (EXISTING)                       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │  │
│  │  │ Ingest │ │Kafka/  │ │ Worker │ │Anomaly │ │Incident│       │  │
│  │  │ API    │ │Redpanda│ │Consumer│ │Detect  │ │Engine  │       │  │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │  │
│  │  │Root    │ │AI      │ │Search  │ │WebSocket│ │Dashboard│       │  │
│  │  │Cause   │ │Triage  │ │        │ │        │ │        │       │  │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐                               │  │
│  │  │PostgreSQL│ │Redis   │ │Runbooks│                               │  │
│  │  └────────┘ └────────┘ └────────┘                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Timeline: Days 32-50

| Day | Phase | Milestone |
|-----|-------|-----------|
| 32-34 | Service Discovery | Base providers, registry, environment detection |
| 35-38 | Dependency Discovery | Network, traffic, trace, mesh analyzers |
| 39-42 | Zero-Config Deploy | Install scripts, Helm chart, Terraform |
| 43-45 | Dashboard | Auto-generated topology map, discovery event feed |
| 46-48 | Testing | Multi-environment integration tests, performance tests |
| 49-50 | Documentation | Updated docs, resume bullets, interview prep |
| 51-55 | Polish | Bug fixes, performance tuning, edge case handling |
| 56-60 | Final QA | Full end-to-end test, demo script, submission |

---

## Key Metrics to Achieve

| Metric | Target | Resume Bullet |
|--------|--------|---------------|
| Discovery time (100 services) | < 10 seconds | 'Discovers 100 services in under 10 seconds' |
| Correlation accuracy | > 95% | 'Correlates 95%+ of telemetry events to services automatically' |
| Dependency confidence | > 0.8 for 80% of edges | 'Infers service dependencies with 80% high-confidence accuracy' |
| Health probe coverage | 100% of discovered services | 'Auto-probes all discovered services for health status' |
| Classification accuracy | > 90% | 'Classifies service types (database, cache, API) with 90%+ accuracy' |
| Zero-config environments | 5+ (Docker, K8s, ECS, EKS, bare metal) | 'Deploys zero-config on 5+ environments' |
| Installation time | < 5 minutes | 'One-command installation in under 5 minutes' |

---

## Resume Transformation

### Before (Day 31):
> "Built SignalForge, a production-ready incident management platform for microservices, in 31 days using FastAPI, React, PostgreSQL, Redis, and Kafka."

### After (Day 60):
> "Architected SignalForge, a **zero-config, auto-discovering incident management platform** that detects services, maps dependencies, and monitors health across **bare metal, Docker, Kubernetes, and AWS** — no manual configuration required. 
> 
> Built a pluggable discovery engine with **process, container, Kubernetes, and cloud provider** scanners that discovers 100 services in under 10 seconds. Implemented multi-technique dependency inference (**network connection tracking, traffic analysis, distributed tracing, service mesh telemetry**) with confidence scoring. Designed event-to-service correlation with **95%+ accuracy** using IP, hostname, container, and trace context matching. Delivered one-command installation via **shell scripts, Helm charts, and Terraform modules** with environment auto-detection."

