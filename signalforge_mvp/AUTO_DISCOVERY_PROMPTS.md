# SignalForge Auto-Discovery — Day-by-Day Implementation Prompts

Copy-paste one prompt per day into a new conversation. Each prompt is self-contained and produces working, tested code.

---

## Day 32 — Service Discovery Abstraction & Base Models

**Prompt:**

Create the service discovery foundation in `backend/app/discovery/`.

1. Create `backend/app/discovery/base.py` with an abstract `ServiceDiscoveryProvider` class. It must have two async methods: `discover(self) -> List[DiscoveredService]` and `health_check(self) -> bool`. The `health_check` method verifies the provider can reach its target (e.g., Docker daemon is running, Kubernetes API is accessible).

2. Create `backend/app/discovery/models.py` with a `DiscoveredService` Pydantic model containing these fields: `service_id` (UUID auto-generated), `service_name` (str), `service_type` (str, default "unknown"), `endpoints` (List[str], e.g., ["http://127.0.0.1:8080", "tcp://127.0.0.1:5432"]), `host` (str, IP or hostname), `metadata` (Dict[str, Any], open-ended), `health_check_url` (Optional[str]), `discovery_source` (str, e.g., "process", "docker", "kubernetes", "config", "manual"), `first_seen_at` (datetime, UTC), `last_seen_at` (datetime, UTC), `last_heartbeat_at` (datetime, UTC). All datetime fields must be timezone-aware (UTC).

3. Create `backend/app/discovery/registry.py` with a `ServiceRegistry` class. This class persists discovered services to PostgreSQL and caches them in memory for fast lookups. Methods required: `register_service(self, service: DiscoveredService) -> str` (returns service_id, inserts if new or updates if existing based on `service_name + host`), `get_service(self, service_id: str) -> Optional[DiscoveredService]`, `list_services(self, tenant_id: Optional[str] = None, active_only: bool = True) -> List[DiscoveredService]`, `update_heartbeat(self, service_id: str) -> None`, `remove_stale_services(self, timeout_seconds: int = 120) -> int` (returns count removed, removes services whose `last_heartbeat_at` is older than `timeout_seconds`). Use SQLAlchemy for database operations. The in-memory cache should be a simple `dict` keyed by `service_id` that syncs with the database on every read.

4. Add a `discovered_services` table to `backend/app/models.py` with these columns: `id` (String, primary key), `service_id` (String, unique, index), `service_name` (String, index), `service_type` (String), `endpoints` (JSON), `host` (String), `metadata` (JSON), `health_check_url` (String, nullable), `discovery_source` (String), `is_active` (Boolean, default True), `first_seen_at` (DateTime, timezone=True), `last_seen_at` (DateTime, timezone=True), `last_heartbeat_at` (DateTime, timezone=True), `tenant_id` (String, index, nullable for now). Include an index on `(service_name, host)` for deduplication lookups. Use `Base` from `database.py`.

5. Create `backend/app/discovery/engine.py` with a `DiscoveryEngine` class. This class holds a list of configured providers and runs them. Methods: `register_provider(self, provider: ServiceDiscoveryProvider) -> None`, `run_discovery(self) -> List[DiscoveredService]` (runs all providers concurrently using `asyncio.gather`, deduplicates by `service_name + host`, updates registry, returns list of discovered services), `start_background_discovery(self, interval_seconds: int = 30) -> None` (starts an `asyncio` background task that runs `run_discovery` every `interval_seconds`), `stop_background_discovery(self) -> None`. The background task should handle exceptions gracefully — if a provider fails, log the error and continue with other providers.

6. Write tests in `backend/tests/discovery/test_models.py` and `backend/tests/discovery/test_registry.py`. Test: `DiscoveredService` model creation and serialization, `ServiceRegistry` CRUD operations, deduplication logic, stale removal, and heartbeat updates. Use SQLite in-memory database for tests. No external dependencies (no Docker, no Kubernetes) should be required for these tests.

---

## Day 33 — Process & Docker Discovery Providers

**Prompt:**

Implement two concrete discovery providers: process scanning and Docker scanning.

1. Add `psutil` to `backend/requirements.txt` if not already present. Create `backend/app/discovery/providers/process.py` with a `ProcessDiscoveryProvider` class implementing `ServiceDiscoveryProvider`. It should:
   - Use `psutil.process_iter()` to iterate all running processes.
   - For each process, use `process.connections(kind='inet')` to find listening sockets.
   - Map the process `exe()` or `name()` to a `service_name` (e.g., `nginx` -> `nginx`, `python` -> `python-app`, `postgres` -> `postgres`). Use a simple mapping: if the executable name contains known keywords, use that; otherwise use the basename of the executable minus the extension. If the executable path is not available, use `process.name()`.
   - Extract listening ports (IPv4 and IPv6, status `LISTEN`). For each unique `(host, port)` pair, create an endpoint string like `tcp://host:port`.
   - Include process metadata: `pid`, `exe`, `cmdline`, `username`, `create_time` (as ISO string), `cpu_percent`, `memory_percent`.
   - Set `discovery_source = "process"`.
   - Set `service_type` based on known port mappings: 80/443 -> `web`, 5432 -> `database`, 6379 -> `cache`, 9092 -> `message_queue`, 8080/3000/5000/8000 -> `api`, 3306 -> `database`, 27017 -> `database`, 11211 -> `cache`, 9200 -> `search`, 5601 -> `dashboard`. Unknown ports -> `unknown`.
   - Skip system processes that are not listening on any port (e.g., kernel threads, system services like `svchost.exe` on Windows). Use a heuristic: if the process name is in a blocklist (`system`, `kernel`, `svchost`, `services`, `wininit`, `winlogon`, `csrss`, `lsass`, `smss`, `crss`, `registry`, `fontdrvhost`), skip it.
   - The `health_check()` method should verify `psutil` is importable and `process_iter()` works (returns True if yes, False if `psutil` is not installed or raises PermissionError).

2. Add `docker` to `backend/requirements.txt` (the Docker SDK for Python). Create `backend/app/discovery/providers/docker.py` with a `DockerDiscoveryProvider` class. It should:
   - Use `docker.from_env()` to connect to the local Docker daemon.
   - List all running containers using `client.containers.list()`.
   - For each container, extract: `name` (use `container.name`), `image` (use `container.image.tags[0]` if available, else `container.image.id`), `id` (short version, 12 chars), `status` (running/stopped), `ports` (from `container.attrs['NetworkSettings']['Ports']`), `networks` (from `container.attrs['NetworkSettings']['Networks']`), `labels` (from `container.labels`).
   - Map container name to `service_name`. If the container has a label `app` or `service.name`, use that. Otherwise, use the container name (remove leading slash if present). Remove random suffixes added by Docker Compose (e.g., `myapp_1` -> `myapp`).
   - Build endpoints from exposed ports: for each port mapping, create `tcp://host:port`. Use the host IP from the port mapping if available, otherwise `127.0.0.1`.
   - Include metadata: `container_id`, `image`, `status`, `labels`, `networks`, `command` (from `container.attrs['Config']['Cmd']`), `created_at` (from `container.attrs['Created']`).
   - Set `discovery_source = "docker"`.
   - Set `service_type` based on image name keywords: if `postgres`, `mysql`, `mongo`, `redis`, `kafka`, `nginx`, `node`, `python`, `go`, `java`, `dotnet` are in the image name, map accordingly. Otherwise infer from exposed ports using the same mapping as process discovery.
   - The `health_check()` method should try to connect to Docker and return `client.ping()` result. If Docker is not running or not accessible, return False.
   - Handle `docker.errors.DockerException` gracefully in `discover()` — if Docker is not running, return an empty list and log a warning.

3. Write tests in `backend/tests/discovery/test_process_provider.py` and `backend/tests/discovery/test_docker_provider.py`. For process provider tests, mock `psutil.process_iter()` and `process.connections()` to return fake processes and connections. Verify the provider discovers the expected services, maps ports correctly, and skips system processes. For Docker provider tests, mock `docker.from_env()` and `client.containers.list()` to return fake containers. Verify container name mapping, label-based naming, port extraction, and metadata inclusion. Test the `health_check()` method for both providers.

---

## Day 34 — Kubernetes, Cloud & Config Providers + Environment Detection

**Prompt:**

Implement the remaining discovery providers and the environment auto-detection system.

1. Add `kubernetes` to `backend/requirements.txt`. Create `backend/app/discovery/providers/kubernetes.py` with a `KubernetesDiscoveryProvider` class. It should:
   - Use `kubernetes.config.load_incluster_config()` when running inside a pod (check for `KUBERNETES_SERVICE_HOST` env var). Use `kubernetes.config.load_kube_config()` as fallback for local development.
   - Create a `CoreV1Api` client. Use `list_pod_for_all_namespaces()` or `list_namespaced_pod(namespace=...)` depending on whether a namespace is configured (env var `SIGNALFORGE_K8S_NAMESPACE`, default to all namespaces).
   - For each pod, extract: `name` (pod.metadata.name), `namespace` (pod.metadata.namespace), `labels` (pod.metadata.labels), `node_name` (pod.spec.node_name), `pod_ip` (pod.status.pod_ip), `phase` (pod.status.phase), `container_ports` (from pod.spec.containers[].ports), `start_time` (pod.status.start_time), `restart_count` (from pod.status.container_statuses[].restart_count).
   - Map pod to service name: if the pod has a label `app.kubernetes.io/name` or `app`, use that. Otherwise, use the pod name with the random suffix removed (e.g., `checkout-7d8f9b2c4-x1z2a` -> `checkout`). Use regex to remove the last two dash-separated segments if they look like hash-replicaset-pod patterns.
   - Build endpoints from container ports: for each container port, create `tcp://pod_ip:port`. If `pod_ip` is not available, skip.
   - Include metadata: `pod_name`, `namespace`, `node_name`, `labels`, `container_ports`, `phase`, `restart_count`, `cluster_name` (from `pod.metadata.cluster_name` if available, else "unknown").
   - Set `discovery_source = "kubernetes"`.
   - Set `service_type` based on labels: if `app.kubernetes.io/component` is `database` or `db`, use `database`. If `cache` or `redis`, use `cache`. If `queue` or `kafka`, use `message_queue`. If `web` or `frontend`, use `web`. If `api` or `backend`, use `api`. Otherwise infer from ports.
   - The `health_check()` method should try to load k8s config and return True if successful. If `kubernetes.config.ConfigException` is raised, return False.
   - Handle `kubernetes.client.rest.ApiException` gracefully in `discover()` — if the API is unavailable, return an empty list and log a warning.

2. Create `backend/app/discovery/providers/cloud.py` with a `CloudDiscoveryProvider` class. It should detect AWS, Azure, or GCP and query the respective APIs. Start with AWS only for now (Azure and GCP can be stubs). It should:
   - Check for AWS environment: if `AWS_EXECUTION_ENV` contains `AWS_ECS`, query ECS tasks using `boto3`. If `KUBERNETES_SERVICE_HOST` is set AND AWS metadata is available (check `http://169.254.169.254/latest/meta-data/`), query EKS pods via Kubernetes API (delegate to `KubernetesDiscoveryProvider` logic but set `discovery_source = "cloud_aws"`).
   - For ECS: use `boto3.client('ecs')` to list clusters, then list services and tasks. For each task, extract: task ARN, service name, container name, container image, host port, host IP. Map to `service_name` using the ECS service name. Set `discovery_source = "cloud_aws_ecs"`. Set `service_type` based on container image name.
   - For AWS EC2/VM: check the AWS metadata endpoint for instance metadata (instance-id, private-ip, etc.). If this is the only thing detected, skip it (we don't want to discover the VM itself as a service, just services running on it). The ECS and EKS paths are the primary ones.
   - For Azure and GCP: create stub providers that return empty lists and log "Azure/GCP discovery not yet implemented".
   - The `health_check()` method should check if the cloud provider is detectable (env vars or metadata endpoint). Return True if any cloud provider is detected, False otherwise.
   - Handle `ImportError` for `boto3` — if it's not installed, return an empty list and log a warning.
   - Add `boto3` to `requirements.txt` as an optional dependency.

3. Create `backend/app/discovery/providers/config.py` with a `ConfigDiscoveryProvider` class. It should:
   - Read from environment variable `SIGNALFORGE_SERVICES` (JSON string) or a config file path from `SIGNALFORGE_SERVICES_CONFIG` (YAML or JSON file).
   - The JSON format should be a list of objects: `[{"name": "my-service", "type": "api", "endpoints": ["http://my-service:8080"], "host": "my-service", "metadata": {"version": "1.0.0"}}]`.
   - If the env var or file is not present, return an empty list.
   - Set `discovery_source = "config"`.
   - The `health_check()` method should always return True (it's a passive provider).
   - Parse YAML if `pyyaml` is available, otherwise require JSON. Add `pyyaml` as an optional dependency.

4. Create `backend/app/discovery/environment.py` with `EnvironmentDetector` and `AutoConfigurator` classes. It should:
   - `EnvironmentDetector.is_docker()`: Check if `/proc/1/cgroup` contains `docker` or `.docker` (Linux). On Windows, check for `Docker Desktop` processes. Return boolean.
   - `EnvironmentDetector.is_kubernetes()`: Check for `KUBERNETES_SERVICE_HOST` env var. Return boolean.
   - `EnvironmentDetector.is_aws_ecs()`: Check for `AWS_EXECUTION_ENV` containing `AWS_ECS`. Return boolean.
   - `EnvironmentDetector.is_aws_eks()`: Check `is_kubernetes()` AND (AWS metadata endpoint is reachable OR `AWS_WEB_IDENTITY_TOKEN_FILE` is set). Return boolean.
   - `EnvironmentDetector.is_azure()`: Check for `AZURE_*` env vars or try to reach Azure metadata endpoint (`http://169.254.169.254/metadata/instance?api-version=2021-02-01`). Return boolean.
   - `EnvironmentDetector.is_gcp()`: Check for `GOOGLE_*` env vars or try to reach GCP metadata endpoint (`http://metadata.google.internal/`). Return boolean.
   - `EnvironmentDetector.is_vm()`: Default True if none of the above. Return boolean.
   - `EnvironmentDetector.get_cloud_provider()`: Returns `'aws'`, `'azure'`, `'gcp'`, or `None`.
   - `EnvironmentDetector.get_discovery_providers()`: Returns a list of provider class names based on environment. For EKS: `['cloud_aws', 'kubernetes', 'docker', 'process']`. For ECS: `['cloud_aws', 'docker', 'process']`. For Kubernetes (non-AWS): `['kubernetes', 'docker', 'process']`. For Docker: `['docker', 'process']`. For VM/bare metal: `['process', 'config']`. Always include `'config'` as the last fallback.
   - `AutoConfigurator` should read env vars: `SIGNALFORGE_DISCOVERY_ENABLED` (default `true`), `SIGNALFORGE_DISCOVERY_INTERVAL` (default `30`), `SIGNALFORGE_DISCOVERY_PROVIDERS` (comma-separated list, overrides auto-detection). It should instantiate the correct providers and configure the `DiscoveryEngine`.

5. Write tests in `backend/tests/discovery/test_environment.py`. Mock filesystem for `/proc/1/cgroup` (create a temporary file with/without `docker` content). Mock env vars using `monkeypatch` from pytest. Mock HTTP requests to metadata endpoints using `responses` or `unittest.mock`. Test all environment detection methods and the `get_discovery_providers` mapping. Test `AutoConfigurator` with different env var combinations.

6. Wire everything into `backend/app/main.py`. In `create_app()`, after configuring existing middleware, instantiate `AutoConfigurator`, create a `DiscoveryEngine`, register the providers returned by `AutoConfigurator`, and start background discovery if `SIGNALFORGE_DISCOVERY_ENABLED` is `true`. Add a cleanup hook to stop background discovery on shutdown. Add `GET /services/discovered` endpoint to `backend/app/routers/discovery.py` (create this file) that returns all discovered services from the registry. Add `POST /services/discover` endpoint that triggers an on-demand discovery run and returns the discovered services. Register the discovery router in `main.py`.

---

## Day 35 — Network Dependency Detection

**Prompt:**

Implement the network-based dependency detection system.

1. Create `backend/app/discovery/dependencies/models.py` with:
   - `ServiceDependency` Pydantic model: `source_service_id` (str), `target_service_id` (str), `dependency_type` (str, e.g., `http`, `grpc`, `database`, `cache`, `message_queue`, `unknown`), `connection_count` (int, default 1), `avg_latency_ms` (Optional[float]), `error_rate` (Optional[float], 0.0-1.0), `last_seen_at` (datetime, UTC), `confidence_score` (float, 0.0-1.0, default 0.5), `discovery_sources` (List[str], e.g., `["network"]`). Add a validator ensuring `confidence_score` is between 0.0 and 1.0.
   - `DependencyGraph` Pydantic model: `nodes` (List[DiscoveredService]), `edges` (List[ServiceDependency]), `generated_at` (datetime, UTC). Add methods: `get_upstream(self, service_id: str) -> List[ServiceDependency]` (returns edges where `target_service_id == service_id`), `get_downstream(self, service_id: str) -> List[ServiceDependency]` (returns edges where `source_service_id == service_id`), `get_critical_path(self, source_id: str, target_id: str) -> List[ServiceDependency]` (returns the shortest path using BFS or Dijkstra, for now just BFS is fine).

2. Create `backend/app/discovery/dependencies/network_scanner.py` with `NetworkConnectionScanner` class. It should:
   - Use `psutil.net_connections(kind='inet')` to get all network connections.
   - For each connection, identify the local process (using `connection.pid`) and the remote endpoint (`connection.raddr` if available).
   - Look up the local process in the `ServiceRegistry` (by matching PID to process metadata from the process discovery provider). If found, this is the `source_service`.
   - Look up the remote endpoint in the `ServiceRegistry` (by matching IP:port to service endpoints). If found, this is the `target_service`.
   - If the remote endpoint is not in the registry but the port is a known service port (e.g., 5432, 6379, 9092), create a placeholder `target_service` with `discovery_source = "inferred"` and `confidence_score = 0.3`.
   - If the connection is `ESTABLISHED`, record it as a dependency. If the connection is `LISTEN`, skip it (it's an incoming connection, we'll catch it from the other side).
   - Infer `dependency_type` from the target port: 5432 -> `database`, 3306 -> `database`, 6379 -> `cache`, 9092 -> `message_queue`, 11211 -> `cache`, 80/443/8080/3000 -> `http`, 50051 -> `grpc`. If the port is not known, use `unknown`.
   - Record `connection_count` as the number of `ESTABLISHED` connections between the same source and target in the current scan.
   - Run every 30 seconds as a background task.
   - Handle `PermissionError` from `psutil.net_connections()` gracefully (some processes require root to inspect). Log a warning and return empty results.

3. Create `backend/app/discovery/dependencies/registry.py` with `DependencyRegistry` class. It should:
   - Use a `service_dependencies` SQLAlchemy table: `id` (String, primary key), `source_service_id` (String, index), `target_service_id` (String, index), `dependency_type` (String), `connection_count` (Integer), `avg_latency_ms` (Float, nullable), `error_rate` (Float, nullable), `last_seen_at` (DateTime, timezone=True), `confidence_score` (Float), `discovery_sources` (JSON), `tenant_id` (String, index, nullable), `created_at` (DateTime, timezone=True), `updated_at` (DateTime, timezone=True). Add a composite index on `(source_service_id, target_service_id)` for fast lookups.
   - Methods: `store_dependency(self, dep: ServiceDependency) -> None` (upsert based on `source_service_id + target_service_id`), `get_dependencies(self, source_id: Optional[str] = None, target_id: Optional[str] = None, min_confidence: float = 0.0) -> List[ServiceDependency]`, `get_all_dependencies(self) -> List[ServiceDependency]`, `remove_stale_dependencies(self, timeout_seconds: int = 300) -> int`.
   - In-memory cache for fast graph queries. Sync with database on write.

4. Write tests in `backend/tests/discovery/dependencies/test_network_scanner.py`. Mock `psutil.net_connections()` to return fake connections with known PIDs and remote addresses. Mock the `ServiceRegistry` to return fake services for those PIDs and addresses. Verify the scanner correctly identifies dependencies, infers types from ports, handles unknown services, and respects permission errors. Test the `DependencyRegistry` upsert logic, deduplication, and stale removal.

5. Add the `service_dependencies` table to `backend/app/models.py` and create an Alembic migration for it. The migration should be auto-generated with `alembic revision --autogenerate -m "add service_dependencies table"` and then manually reviewed.

---

## Day 36 — Traffic & Trace Dependency Analyzers

**Prompt:**

Implement traffic log analysis and distributed tracing analysis for dependency detection.

1. Create `backend/app/discovery/dependencies/traffic_analyzer.py` with `TrafficAnalyzer` class. It should:
   - Read log files specified by env var `SIGNALFORGE_LOG_PATHS` (comma-separated list of glob patterns, e.g., `/var/log/nginx/*.log,/var/log/app/*.json`). Default to common paths: `/var/log/nginx/access.log`, `/var/log/*/access.log`.
   - Parse multiple log formats:
     - Nginx combined: `192.168.1.1 - - [10/Oct/2023:13:55:36 -0700] "GET /api/users HTTP/1.1" 200 1234 "-" "curl/7.68.0"`. Extract source IP, HTTP method, URL path, status code, and user agent. For the URL, look for outgoing proxy passes or upstream requests. Nginx access logs primarily show *incoming* requests, so for dependency detection we need to look for upstream logs or application logs.
     - Application JSON logs: Expect JSON objects with fields like `timestamp`, `level`, `message`, `service`, `outgoing_url`, `target_service`, `duration_ms`, `status_code`. Parse the JSON and extract `outgoing_url` or `target_service`.
     - Generic HTTP log regex: Look for patterns like `http://service-name:port/path` or `https://service-name.domain.com/path` in any log line. Extract the hostname and port from the URL.
   - Map extracted hostnames to services using the `ServiceRegistry` (match by hostname, service name, or endpoint). If a hostname is `payment-service.svc.cluster.local`, match it to a service named `payment-service`. If it doesn't match any known service, skip it (don't create inferred services here — the network scanner handles that).
   - For each matched outgoing request, record a `ServiceDependency` with `source_service_id` = the service that wrote the log, `target_service_id` = the service from the URL, `dependency_type = "http"`, `discovery_sources = ["traffic_log"]`. Set `confidence_score = 0.7` (logs are higher confidence than pure network connections because they show application-level intent).
   - Handle log rotation: use `tail -f` equivalent in Python (`open(file, 'r').seek()` to end, then read new lines). For now, implement a simple scan: read the last N lines of each file (N = 1000, configurable via `SIGNALFORGE_LOG_TAIL_LINES`).
   - Run every 60 seconds as a background task.
   - Handle file-not-found errors gracefully (skip missing files, log a warning).
   - Handle large files gracefully (read only the last N lines, don't load entire files into memory).

2. Create `backend/app/discovery/dependencies/trace_analyzer.py` with `TraceAnalyzer` class. It should:
   - Read distributed tracing data from a backend specified by `SIGNALFORGE_TRACING_BACKEND_URL` (e.g., `http://jaeger:16686`, `http://zipkin:9411`, or `http://tempo:3200`). Default to None (disabled if not set).
   - Support Jaeger query API: `GET /api/traces?service={service_name}&limit=100`. Parse the response to extract spans. For each span, extract `traceID`, `spanID`, `parentSpanID`, `operationName`, `startTime`, `duration`, `tags` (including `service.name` or `peer.service`), and `references` (childOf relationships).
   - Support Zipkin query API: `GET /api/v2/traces?serviceName={service_name}&limit=100`. Parse JSON to extract spans. Map `localEndpoint.serviceName` to source service, `remoteEndpoint.serviceName` or `peer.service` tag to target service.
   - Support OpenTelemetry format (if the tracing backend supports it): spans with `service.name` resource attribute and `peer.service` span attribute.
   - For each parent-child span relationship where the services are different, record a `ServiceDependency` with `dependency_type = "http"` (or extract from `span.kind` tag: `client` -> `http`, `producer` -> `message_queue`, etc.), `discovery_sources = ["trace"]`.
   - Set `confidence_score = 0.9` (traces are very high confidence because they show explicit application-level calls). Set `avg_latency_ms` from the span duration.
   - Handle connection errors to the tracing backend gracefully (log warning, retry with exponential backoff up to 3 times, then skip until next cycle).
   - Run every 60 seconds as a background task. Query traces for each discovered service in the registry.

3. Write tests in `backend/tests/discovery/dependencies/test_traffic_analyzer.py` and `test_trace_analyzer.py`. For traffic analyzer: create temporary log files with known formats, mock the `ServiceRegistry`, and verify the analyzer correctly extracts dependencies from nginx logs and JSON logs. For trace analyzer: mock HTTP responses from Jaeger/Zipkin APIs using `responses` library or `unittest.mock`, and verify span parsing and dependency extraction. Test error handling for missing files, connection errors, and malformed logs.

4. Add `GET /dependencies/traffic` and `GET /dependencies/traces` endpoints (for debugging/admin) that return the last analyzed dependencies from each analyzer. These are optional for the dashboard but useful for troubleshooting.

---

## Day 37 — Service Mesh Analyzer & Graph Builder

**Prompt:**

Implement the service mesh metrics analyzer and the dependency graph builder that merges data from all analyzers.

1. Create `backend/app/discovery/dependencies/mesh_analyzer.py` with `ServiceMeshAnalyzer` class. It should:
   - Query Prometheus for Istio metrics via `SIGNALFORGE_PROMETHEUS_URL` (default: `http://prometheus:9090`). If not set, the analyzer is disabled.
   - Use Prometheus HTTP API: `GET /api/v1/query?query=istio_requests_total`. Parse the response to get metric samples.
   - For each sample, extract labels: `source_app` (source service), `destination_app` (target service), `response_code`, `reporter` (source or destination). Only use samples where `reporter = "source"` to avoid double-counting.
   - Map `source_app` and `destination_app` to service IDs using the `ServiceRegistry`. If not found, try to match by service name.
   - For each unique `(source_app, destination_app)` pair, query additional metrics: `istio_request_duration_milliseconds_sum` and `istio_request_duration_milliseconds_count` to calculate average latency. `istio_requests_total` with `response_code=~"5.*"` to calculate error rate.
   - Record a `ServiceDependency` with:
     - `source_service_id` and `target_service_id` from the registry
     - `dependency_type = "http"` (or `grpc` if `grpc_response_status` label is present)
     - `connection_count` = the `value` from `istio_requests_total` (total request count over the query window)
     - `avg_latency_ms` = `sum / count` from duration metrics
     - `error_rate` = `5xx_count / total_count`
     - `confidence_score = 0.95` (service mesh metrics are the highest confidence because they come from the infrastructure, not application code)
     - `discovery_sources = ["service_mesh"]`
   - Handle Prometheus query errors gracefully (log warning, retry 3 times with exponential backoff, then skip until next cycle).
   - Run every 60 seconds as a background task.
   - Also support Envoy metrics as a fallback: query `envoy_cluster_upstream_rq_total` and `envoy_cluster_upstream_rq_time_sum` from the Envoy admin endpoint (`http://envoy:9901/stats/prometheus`). Parse the Prometheus text format. Extract cluster names (which map to service names) and request counts/latencies. This is a simpler fallback if Istio is not available.

2. Create `backend/app/discovery/dependencies/graph_builder.py` with `DependencyGraphBuilder` class. It should:
   - Accept a list of `BaseDependencyAnalyzer` instances (network scanner, traffic analyzer, trace analyzer, mesh analyzer). Each analyzer implements `get_dependencies() -> List[ServiceDependency]`.
   - Run all analyzers in parallel using `asyncio.gather` (or sequentially if the analyzers are not async — wrap them in `asyncio.to_thread`).
   - Merge results: for each unique `(source_service_id, target_service_id)` pair:
     - Collect all `ServiceDependency` objects from all analyzers.
     - Calculate merged `confidence_score` = `1 - (1 - c1) * (1 - c2) * ...` (independent probability combination, or simply take the max). Let's use a weighted average: `sum(confidence * weight) / sum(weights)` where weight = `connection_count` from each analyzer. If no connection count, weight = 1.
     - Collect all `discovery_sources` into a unique list.
     - Sum `connection_count` across all analyzers.
     - Calculate weighted average `avg_latency_ms` and `error_rate` across analyzers.
     - Take the most recent `last_seen_at`.
     - If the same dependency is detected by multiple analyzers, increase confidence (e.g., if 2 analyzers agree, confidence = `max(c1, c2) + 0.1` capped at 1.0; if 3+ agree, `+ 0.2` capped at 1.0).
   - Store merged dependencies in the `DependencyRegistry`.
   - Build a `DependencyGraph` from the registry data. Provide methods: `get_graph(self, tenant_id: Optional[str] = None, min_confidence: float = 0.0, dependency_types: Optional[List[str]] = None) -> DependencyGraph`.
   - Run every 60 seconds as a background task.
   - Update the graph incrementally: only re-query analyzers, merge new results, and update changed dependencies. Don't rebuild the entire graph from scratch every time.

3. Create `backend/app/discovery/dependencies/base.py` with `BaseDependencyAnalyzer` abstract class. It should have `async def analyze(self) -> List[ServiceDependency]` and `health_check(self) -> bool` methods. Refactor all analyzers to inherit from this class.

4. Write tests in `backend/tests/discovery/dependencies/test_graph_builder.py`. Mock 2-3 analyzers that return overlapping dependencies with different confidence scores. Verify the graph builder correctly merges them, deduplicates, calculates weighted confidence, and handles edge cases (e.g., one analyzer says A->B, another says A->C, no overlap). Test the `get_graph` filtering methods. Test the background update cycle.

5. Add `GET /graph/auto` endpoint to `backend/app/routers/discovery.py`. It should accept query parameters: `min_confidence` (float, default 0.0), `dependency_type` (str, optional), `tenant_id` (str, required). Return the auto-generated dependency graph. The response format should match the existing `GET /graph` endpoint (nodes and edges) so the frontend can reuse the `ServiceGraph` component.

6. Add `GET /services/{service_id}/dependencies` endpoint. Return `{ "upstream": [...], "downstream": [...], "self": service }`.

---

## Day 38 — Event-to-Service Correlation Engine

**Prompt:**

Implement the event-to-service correlation engine so that telemetry events can be automatically matched to discovered services without requiring the client to specify `service_name`.

1. Create `backend/app/discovery/correlation.py` with `EventServiceCorrelator` class. It should:
   - Accept a `ServiceRegistry` instance in its constructor.
   - Implement `correlate(self, event: TelemetryEvent) -> Tuple[Optional[str], float, str]` which returns: `(service_id, confidence_score, strategy_used)`.
   - Matching strategies (in order of priority, highest confidence first):
     1. **Exact service name match**: If `event.service_name` is provided and matches a known service in the registry (case-insensitive), return that service with `confidence = 1.0` and `strategy = "exact_name"`.
     2. **Source IP + port match**: If `event.attributes` contains `source_ip` and `source_port`, look up services in the registry whose endpoints contain `tcp://source_ip:source_port` or `http://source_ip:source_port`. If exactly one match, return it with `confidence = 0.95` and `strategy = "source_ip_port"`. If multiple matches, return the one with the most recent heartbeat (or the one with `service_type` matching the event type) with `confidence = 0.8`.
     3. **Hostname match**: If `event.attributes` contains `hostname` or `host`, look up services in the registry whose `host` or `service_name` matches the hostname (case-insensitive, partial match allowed). If one match, return with `confidence = 0.9` and `strategy = "hostname"`. If multiple, use the same disambiguation as above.
     4. **Container ID match**: If `event.attributes` contains `container_id`, look up services in the registry whose metadata contains a matching `container_id` (partial match allowed, e.g., first 12 chars). If match, return with `confidence = 0.95` and `strategy = "container_id"`.
     5. **Pod name match**: If `event.attributes` contains `pod_name`, look up services in the registry whose metadata contains a matching `pod_name`. If match, return with `confidence = 0.95` and `strategy = "pod_name"`.
     6. **Process ID match**: If `event.attributes` contains `process_id`, look up services in the registry whose metadata contains a matching `pid`. If match, return with `confidence = 0.9` and `strategy = "process_id"`.
     7. **Trace context match**: If `event.attributes` contains `trace_id` and `parent_span_id`, query the tracing backend (if configured) to find the parent span's service name. Then look up that service in the registry. If found, return with `confidence = 0.85` and `strategy = "trace_context"`. If no tracing backend is configured, skip this strategy.
     8. **Fallback**: If no strategy matches, return `(None, 0.0, "none")`. The event is considered "uncorrelated" and will be queued for admin review.
   - For all strategies that match multiple services, log a warning with the event ID and the list of candidate services. The disambiguation logic (most recent heartbeat, type matching) should be a helper method `_disambiguate(candidates: List[DiscoveredService], event: TelemetryEvent) -> Optional[DiscoveredService]`.
   - Add a `correlation_metadata` field to `TelemetryEvent` (or to the event's `attributes` dict) storing: `strategy`, `confidence`, `matched_field`, `candidate_count`. This is stored in the database when the event is processed.
   - The correlator should be called in `EventProcessor.process()` before storing the event. If a service is correlated, set `event.service_name` to the discovered service's name and `event.tenant_id` to the discovered service's tenant_id (if applicable). Store the correlation metadata in the event's attributes.

2. Add `correlation_metadata` field to the `TelemetryEvent` Pydantic model in `schemas.py`. It should be a nested dict: `{"strategy": str, "confidence": float, "matched_field": Optional[str], "candidate_count": int}`. If not provided by the client, it will be populated by the correlator. Update the database model `TelemetryEventModel` to include a JSON column `correlation_metadata`.

3. Modify `backend/app/services/event_processor.py` to call the `EventServiceCorrelator` if `event.service_name` is not provided or if the provided `service_name` does not match any known service. Add a `correlator` parameter to the `EventProcessor` constructor (default to None, create one if not provided). In `process()`, after validation and before storage, call `correlator.correlate(event)`. Log a warning if correlation confidence is below 0.5. If correlation fails, still store the event but mark it as `uncorrelated = True` in the database.

4. Add `uncorrelated` boolean field to `TelemetryEventModel` (default False). Add an index on `(uncorrelated, tenant_id)` for fast querying of uncorrelated events.

5. Add `GET /events/uncorrelated` endpoint to `backend/app/routers/events.py`. Return events where `uncorrelated = True`, ordered by most recent first, with pagination (`limit`, `offset` parameters). Include the correlation metadata in the response so the admin can see why it failed to match.

6. Write tests in `backend/tests/discovery/test_correlation.py`. Create a mock `ServiceRegistry` with 5 fake discovered services. Test each correlation strategy with events containing the appropriate metadata. Test the disambiguation logic with multiple candidates. Test the fallback case. Test that `EventProcessor` correctly calls the correlator and stores the metadata. Test the `GET /events/uncorrelated` endpoint.

7. Create an Alembic migration for the new `correlation_metadata` and `uncorrelated` fields on the `events` table.

---

## Day 39 — Install Scripts & Environment Auto-Config

**Prompt:**

Create zero-config installation scripts and environment auto-configuration.

1. Create `install/install.sh` (bash script for Linux/macOS). It should:
   - Print a banner: "SignalForge Installer — Auto-Discovering Incident Management".
   - Detect OS: `uname -s` (Linux, Darwin). Detect architecture: `uname -m` (x86_64, arm64, aarch64).
   - Detect environment: check for Docker (docker command available), Kubernetes (kubectl available and cluster accessible), bare metal (neither). Print a summary.
   - Download the latest SignalForge binary or Docker image. For now, use the Docker image approach (simpler and cross-platform): `docker pull ghcr.io/dharmppp21/signforge:latest` (or use a placeholder registry). If Docker is not available, fall back to a Python pip install: `pip install signalforge` (placeholder).
   - Generate a configuration file at `~/.config/signforge/config.yaml` (or `~/.signforge/config.yaml` for simplicity). The config should be auto-generated based on the detected environment:
     - If Docker detected: `discovery.providers: [docker, process, config]`, `discovery.docker.socket: /var/run/docker.sock`
     - If Kubernetes detected: `discovery.providers: [kubernetes, docker, process, config]`, `discovery.kubernetes.namespace: default`, `discovery.kubernetes.in_cluster: true` (if in-cluster) or `kubeconfig: ~/.kube/config` (if local)
     - If bare metal: `discovery.providers: [process, config]`
   - Also auto-configure database: if PostgreSQL is available locally (port 5432 open), use it. Otherwise, use SQLite at `~/.config/signforge/signforge.db`.
   - Also auto-configure Redis: if Redis is available locally (port 6379 open), use it. Otherwise, disable Redis (graceful degradation).
   - Also auto-configure Kafka: disable by default (user must explicitly enable it). Set `kafka.enabled: false`.
   - Print the generated config file and ask for confirmation (Y/n). If the user confirms, write it. If not, print the config and exit, telling the user to manually edit `~/.signforge/config.yaml`.
   - Create a systemd service file at `~/.config/systemd/user/signforge.service` (or `/etc/systemd/system/signforge.service` if run with sudo). The service should run the Docker container or the Python module. Print instructions: `systemctl --user enable signforge && systemctl --user start signforge`.
   - For macOS, create a `launchd` plist at `~/Library/LaunchAgents/com.signforge.plist` instead of systemd.
   - Support flags: `--version` (print version and exit), `--backend-only` (skip frontend installation), `--with-frontend` (pull and run the frontend Docker image too), `--discovery-only` (install only the discovery agent, not the full backend), `--uninstall` (stop and remove the service, delete config, remove images). Implement `--uninstall` fully.
   - Handle errors gracefully: if Docker is not available and pip install fails, print a helpful error message with manual installation instructions.
   - Make the script executable (`chmod +x install.sh`).

2. Create `install/install.ps1` (PowerShell script for Windows). It should:
   - Print the same banner.
   - Detect OS: Windows. Detect architecture: `$env:PROCESSOR_ARCHITECTURE`.
   - Detect environment: check for Docker Desktop (docker command available), WSL (wsl command available), bare Windows.
   - Download and install SignalForge. For Windows, prefer a Docker Desktop approach. If Docker is not available, use a Python pip install (but warn the user that some features won't work).
   - Generate config at `%APPDATA%\SignalForge\config.yaml` (Windows equivalent of `~/.config/signforge/`).
   - Create a Windows service using `New-Service` or `sc.exe`. The service should run the Docker container or a Python script. Print instructions: `Start-Service SignalForge`.
   - Support the same flags as `install.sh`: `-Version`, `-BackendOnly`, `-WithFrontend`, `-DiscoveryOnly`, `-Uninstall`. Implement `-Uninstall` fully (stop service, delete config, remove images).
   - Handle PowerShell execution policy: if the script is blocked, print a message telling the user to run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

3. Create `install/config-template.yaml` with a Jinja2-like template (or just use Python string formatting in the install script) that generates the config. The template should include all possible configuration sections with comments explaining each option. Sections: `database`, `redis`, `kafka`, `discovery` (with sub-sections for each provider), `auth`, `logging`, `api` (rate limiting, CORS). Use sensible defaults and auto-detected values.

4. Write a simple test script `install/test_install.sh` that mocks the Docker/pip commands and verifies the generated config file is correct for each environment. This is a shell script test, not a Python test. Keep it simple.

5. Update `README.md` with a new "One-Command Installation" section at the top (after the quick start). Show: `curl -fsSL https://raw.githubusercontent.com/dharmppp21/signforge/main/install.sh | bash` for Linux/macOS and `iwr -useb https://raw.githubusercontent.com/dharmppp21/signforge/main/install.ps1 | iex` for Windows. Mention that this auto-detects the environment and configures everything.

---

## Day 40 — Helm Chart for Kubernetes

**Prompt:**

Create a production-ready Helm chart for deploying SignalForge on Kubernetes with auto-discovery enabled.

1. Create `helm/signforge/Chart.yaml` with:
   - `apiVersion: v2`, `name: signforge`, `version: 0.1.0`, `description: "Auto-discovering incident management platform"`, `type: application`, `appVersion: "0.1.0"`.
   - `dependencies`: optional subcharts for `postgresql` (Bitnami, version 13.x), `redis` (Bitnami, version 18.x), `kafka` (Bitnami, version 26.x). All dependencies should be `condition: postgresql.enabled`, `redis.enabled`, `kafka.enabled` so they can be disabled if the user brings their own.

2. Create `helm/signforge/values.yaml` with comprehensive defaults. Key sections:
   - `replicaCount: 1` (backend replicas), `image.repository: ghcr.io/dharmppp21/signforge`, `image.tag: latest`, `image.pullPolicy: IfNotPresent`.
   - `service.type: ClusterIP`, `service.port: 8000`, `ingress.enabled: false` (user can enable with their own ingress config).
   - `resources: {}` (user can set CPU/memory limits), `nodeSelector: {}`, `tolerations: []`, `affinity: {}`.
   - `postgresql.enabled: true`, `postgresql.auth.database: signforge`, `postgresql.auth.username: signforge`, `postgresql.auth.password: signforge` (generate random in production using Helm secrets or external secret management).
   - `redis.enabled: true`, `redis.auth.enabled: false` (for simplicity, or generate password).
   - `kafka.enabled: false` (default off, user can enable).
   - `discovery.enabled: true`, `discovery.interval: 30`, `discovery.providers: ["kubernetes", "docker", "process", "config"]`.
   - `discovery.kubernetes.namespace: ""` (empty string means all namespaces), `discovery.kubernetes.clusterRole: true` (create a ClusterRole for cross-namespace discovery). If `clusterRole: false`, use Role for single-namespace discovery.
   - `serviceAccount.create: true`, `serviceAccount.name: signforge`.
   - `rbac.create: true` (create ClusterRole and ClusterRoleBinding for Kubernetes API access).
   - `env: {}` (extra environment variables).
   - `config: {}` (extra config file entries, merged into the generated config).

3. Create `helm/signforge/templates/` with:
   - `_helpers.tpl`: define template helpers for name, fullname, chart, labels, service account name, etc.
   - `deployment.yaml`: Deployment for the SignalForge backend. Include init containers for database migrations (run `alembic upgrade head` before the main container starts). Include volumes for the config file (from ConfigMap). Include liveness probe (`GET /health`) and readiness probe (`GET /health`). Include environment variables from `values.yaml` and secrets.
   - `service.yaml`: Service exposing port 8000.
   - `configmap.yaml`: ConfigMap containing the auto-generated `config.yaml`. The config should be generated from `values.yaml` settings: database URL (if postgresql enabled, use the service name from the subchart), Redis URL, Kafka brokers (if enabled), discovery settings, auth settings. Use Helm template functions to construct the database URL from the PostgreSQL subchart service name.
   - `serviceaccount.yaml`: ServiceAccount for the pod.
   - `rbac.yaml`: ClusterRole with permissions to get/list/watch pods, services, endpoints, nodes, deployments, replicasets, statefulsets, daemonsets, namespaces. This is the minimal set needed for service discovery. If `rbac.create: false`, skip this. If `discovery.kubernetes.clusterRole: false`, create a Role instead of ClusterRole, limited to the release namespace.
   - `ingress.yaml`: Optional Ingress template (disabled by default, template exists for user customization).
   - `hpa.yaml`: Optional HorizontalPodAutoscaler (disabled by default).
   - ` NOTES.txt`: Post-installation notes showing how to access the service, check logs, and verify discovery is working. Include a command to port-forward: `kubectl port-forward svc/signforge 8000:8000`.

4. Create `helm/signforge/templates/tests/test-connection.yaml`: A Helm test pod that runs `curl` against the SignalForge service to verify it's reachable after installation. This is a standard Helm pattern.

5. Add a `README.md` in `helm/signforge/` explaining how to install, configure, and upgrade the chart. Include examples for:
   - Basic install: `helm install signforge ./helm/signforge --namespace monitoring --create-namespace`
   - With external PostgreSQL: `helm install signforge ./helm/signforge --set postgresql.enabled=false --set env.DATABASE_URL=postgresql://...`
   - With limited RBAC (single namespace): `helm install signforge ./helm/signforge --set discovery.kubernetes.clusterRole=false`
   - Enabling Kafka: `helm install signforge ./helm/signforge --set kafka.enabled=true`
   - Upgrading: `helm upgrade signforge ./helm/signforge`

6. Write a test script `helm/test-chart.sh` that uses `helm lint` and `helm template` to verify the chart renders without errors. Also use `helm unittest` if available (add `helm-unittest` plugin as a dev dependency). This is a shell script test, not a Python test.

7. Add a GitHub Actions workflow (`.github/workflows/helm-chart.yaml`) that lints the chart on every push to the main branch. This is optional but impressive for a resume.

---

## Day 41 — Terraform Module for AWS

**Prompt:**

Create Terraform modules for deploying SignalForge on AWS (EKS + ECS options).

1. Create `terraform/modules/signforge/` with the following files:
   - `variables.tf`: Define all input variables: `cluster_name`, `vpc_id`, `private_subnet_ids` (list), `public_subnet_ids` (list, optional), `enable_eks` (bool, default true), `enable_ecs` (bool, default false), `enable_rds` (bool, default true), `enable_elasticache` (bool, default true), `enable_msk` (bool, default false), `enable_alb` (bool, default true), `enable_cloudfront` (bool, default false), `db_instance_class` (default `db.t3.medium`), `db_allocated_storage` (default 20), `redis_node_type` (default `cache.t3.micro`), `ecs_task_cpu` (default 512), `ecs_task_memory` (default 1024), `eks_node_instance_types` (default `["t3.medium"]`), `eks_desired_capacity` (default 2), `tags` (map, default {}).
   - `main.tf`: Orchestrate the sub-modules based on variable flags. Use `module` blocks for each sub-module. Use `count` or `for_each` to conditionally create resources based on boolean flags.
   - `outputs.tf`: Output the service URL (ALB DNS name or CloudFront domain), database endpoint, Redis endpoint, EKS cluster endpoint (if enabled), ECS service ARN (if enabled).
   - `versions.tf`: Require Terraform >= 1.0, AWS provider >= 5.0, Kubernetes provider >= 2.0, Helm provider >= 2.0.

2. Create sub-modules in `terraform/modules/signforge/modules/`:
   - `vpc/` (optional, reuse existing VPC): Data sources for VPC and subnets. If `vpc_id` is provided, use data sources. If not, create a new VPC (simplified, just for completeness).
   - `eks/`: Create an EKS cluster using the `terraform-aws-modules/eks/aws` module. Configure managed node groups with the specified instance types. Enable IRSA (IAM Roles for Service Accounts) so pods can assume IAM roles. Output the cluster endpoint and certificate.
   - `ecs/`: Create an ECS Fargate cluster. Create a task definition for SignalForge (container image, CPU, memory, environment variables). Create an ECS service with the desired count. Configure the task execution role with permissions for ECR, CloudWatch Logs, and Secrets Manager. Configure the task role with permissions for RDS, ElastiCache, and MSK (if enabled).
   - `rds/`: Create a PostgreSQL RDS instance (Multi-AZ if `db_multi_az = true`). Create a DB subnet group using the private subnets. Create a security group allowing access from the EKS/ECS security group. Store the master password in AWS Secrets Manager. Output the endpoint and port.
   - `elasticache/`: Create a Redis cluster (ElastiCache). Create a subnet group and security group. Output the primary endpoint and port.
   - `msk/`: Create an MSK (Managed Kafka) cluster. Create a security group. Output the bootstrap brokers.
   - `alb/`: Create an Application Load Balancer. Create target groups for the backend service (ECS or EKS). Create listeners for HTTP (port 80) and optionally HTTPS (port 443) with an ACM certificate. Create security groups. Output the ALB DNS name.
   - `cloudfront/`: Create a CloudFront distribution. Create an S3 bucket for the frontend static assets. Create an origin access identity. Configure the origin to be the ALB (for API) and S3 (for frontend). Output the CloudFront domain name.
   - `iam/`: Create IAM roles and policies for the SignalForge service. The EKS/IRSA role needs permissions to read from RDS, ElastiCache, MSK, and Secrets Manager. The ECS task role needs the same. The ECS execution role needs ECR pull, CloudWatch Logs write, and Secrets Manager read. Create a minimal policy document for each.
   - `security_groups/`: Create security groups for each service (backend, database, Redis, Kafka, ALB) and the rules between them. For example, backend SG can egress to database SG on port 5432, to Redis SG on port 6379, and to Kafka SG on port 9092.

3. Create example configurations in `terraform/examples/`:
   - `eks-complete/`: A complete example using EKS with all managed services. `main.tf` calls the root module with `enable_eks = true`, `enable_ecs = false`, `enable_rds = true`, `enable_elasticache = true`, `enable_msk = false`, `enable_alb = true`, `enable_cloudfront = false`. Include a `terraform.tfvars` file with example values. Include a `README.md` explaining how to run `terraform init && terraform plan && terraform apply`.
   - `ecs-simple/`: A simpler example using ECS Fargate with RDS and ElastiCache. No EKS, no CloudFront, no MSK. This is cheaper for dev environments.
   - `backend-variables.tfvars`: A file showing all possible variable values and their meanings.

4. Update `AWS_ARCHITECTURE.md` to reference the Terraform modules. Add a section "Infrastructure as Code" with the module structure and example usage.

5. Write a simple validation script `terraform/validate.sh` that runs `terraform validate` in each example directory. This ensures the Terraform syntax is correct.

6. Add a GitHub Actions workflow (`.github/workflows/terraform-validate.yaml`) that validates the Terraform modules on every push. This is optional but impressive.

---

## Day 42 — Docker Compose with Auto-Discovery & Final Deployment Polish

**Prompt:**

Update the Docker Compose stack for full auto-discovery support and finalize deployment documentation.

1. Update `docker-compose.yml`:
   - Add a `signforge-discovery` service (or just use the backend container with discovery enabled). The backend container needs access to the Docker socket for Docker discovery. Add a volume: `/var/run/docker.sock:/var/run/docker.sock:ro` (read-only). Add `network_mode: host` or use the `host` network mode for the backend container if process discovery needs to see host processes (this is a security trade-off, document it). Alternatively, add `pid: host` to share the process namespace.
   - Add environment variables for auto-discovery: `SIGNALFORGE_DISCOVERY_ENABLED=true`, `SIGNALFORGE_DISCOVERY_INTERVAL=30`, `SIGNALFORGE_DISCOVERY_PROVIDERS=docker,process,config`.
   - Add comments in the `docker-compose.yml` explaining each section and how to run on different environments (Docker-only, Docker + K8s locally via minikube, bare metal with just the backend container).
   - Ensure the `backend` service depends on `postgres`, `redis`, and `redpanda` with `condition: service_healthy`.
   - Add a `signforge-frontend` service (already exists, but verify it proxies `/api/*` to the backend service name `backend` in the Docker network).
   - Add a `signforge-simulator` service with profile `simulator` (already exists, verify).

2. Create `docker-compose.override.yml` (optional override for local development). It should:
   - Mount the backend source code as a volume for live reloading (`./backend:/app`).
   - Set `ENVIRONMENT=development` and `LOG_LEVEL=DEBUG`.
   - Expose the backend directly on port 8000 (not just through the frontend proxy).
   - Disable the frontend nginx service (use `npm run dev` directly for frontend development, or just proxy to the backend).
   - This file is automatically picked up by `docker-compose up` if present. Document it in the README.

3. Create `docker-compose.prod.yml` (production override). It should:
   - Use `restart: unless-stopped` for all services.
   - Use read-only volumes where possible (e.g., `/app` read-only for the backend, only `/tmp` and `/app/data` writable).
   - Use resource limits (CPU and memory) for each service.
   - Remove volume mounts for source code (use the built image only).
   - Use `SIGNALFORGE_DISCOVERY_PROVIDERS=config` (only static config, no process scanning in production containers for security).
   - Document: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

4. Create `Dockerfile.discovery` (optional, if we want a separate discovery agent). This is a lightweight container that only runs the discovery engine and reports to the main backend. It should be based on `python:3.12-slim` and only include the discovery dependencies (`psutil`, `docker`, `kubernetes`). This is useful for running discovery in restricted environments where the main backend doesn't have access to the Docker socket or K8s API. For now, keep it simple: the discovery engine runs inside the main backend container. But create the Dockerfile as a placeholder for future use.

5. Update `README.md` with:
   - A "Docker Compose with Auto-Discovery" section explaining how the backend automatically discovers other containers in the same Docker network. Show the command to check discovered services: `docker exec signforge-backend curl -s http://localhost:8000/services/discovered`.
   - A "Kubernetes Deployment" section summarizing the Helm chart (refer to `helm/signforge/README.md` for details).
   - A "AWS Deployment" section summarizing the Terraform modules (refer to `terraform/examples/` for details).
   - A "Production Deployment Checklist" section: enable PostgreSQL (not SQLite), enable Redis, enable Kafka (optional), disable process discovery (use config or K8s discovery instead), use Secrets Manager or environment variables for credentials, configure TLS/SSL, set up monitoring (CloudWatch/Prometheus), configure backups (RDS snapshots), enable rate limiting, review RBAC/IAM permissions.

6. Update `PROJECT_STATE.md` to include the new deployment artifacts (install scripts, Helm chart, Terraform modules, Docker Compose updates) in the file inventory and timeline.

7. Final cleanup: run `docker-compose config` to validate the compose files. Run `helm lint` if Helm is installed. Run `terraform validate` if Terraform is installed. Fix any issues.

---

## Day 43 — Auto-Generated Service Topology Dashboard (Frontend)

**Prompt:**

Create the auto-discovered service topology map in the React frontend.

1. Create `frontend/src/components/ServiceTopologyMap.tsx`:
   - Fetch data from three endpoints on mount and every 10 seconds (using TanStack Query `useQuery` with `refetchInterval: 10000`):
     - `GET /services/discovered` (services with health status)
     - `GET /graph/auto` (auto-discovered dependency graph)
     - `GET /services/health` (health status for all services)
   - Render an interactive topology graph using **React Flow** (`reactflow` npm package) or **D3 force-directed graph** (reuse existing D3 approach if you prefer). React Flow is recommended because it provides built-in zoom, pan, drag, and layout algorithms. Install it: `npm install reactflow`.
   - Nodes: one node per discovered service. Node properties:
     - `id`: service_id
     - `label`: service_name
     - `type`: custom node type based on `service_type` (database icon, cache icon, web icon, API icon, unknown icon). Use simple SVG icons or emoji icons for now (e.g., 🗄️ for database, ⚡ for cache, 🌐 for web, 🔧 for API, ❓ for unknown).
     - `style`: border color based on health status (green `#22c55e` for up, yellow `#eab308` for unknown, red `#ef4444` for down). Background color based on service_type (light tint). Node size based on "importance" (critical services like databases are larger).
     - `data`: full service object for the detail panel.
   - Edges: one edge per dependency. Edge properties:
     - `id`: `source->target`
     - `source`, `target`: service IDs
     - `label`: show `connection_count` and `avg_latency_ms` (e.g., "42 reqs, 15ms")
     - `style`: stroke color based on confidence (solid `#3b82f6` for confidence > 0.8, dashed `#6b7280` for 0.5-0.8, dotted `#9ca3af` for < 0.5). Stroke width based on `connection_count` (more connections = thicker line). Animated flow for edges with high traffic (use CSS animation or React Flow's animated edges).
   - Layout: use React Flow's `dagre` layout (install `@dagrejs/dagre`) for hierarchical layout, or `elkjs` for more advanced layout. Alternatively, use a simple grid layout if the graph library is too complex. The key is that the layout is automatic — no manual node positioning.
   - Interactions:
     - Click on a node: open the `ServiceDetailsPanel` (see below).
     - Hover on a node: show a tooltip with quick stats (health status, type, endpoints, uptime).
     - Hover on an edge: show a tooltip with dependency details (type, latency, error rate, confidence, sources).
     - Drag to rearrange nodes (persist layout in localStorage or session state).
     - Zoom and pan (built into React Flow).
   - Controls: add a control panel with:
     - Filter by `service_type` (checkboxes: all, database, cache, web, api, message_queue, unknown)
     - Filter by `health_status` (checkboxes: all, up, down, unknown)
     - Filter by `min_confidence` (slider: 0.0 to 1.0, default 0.0)
     - Toggle auto-refresh (on/off, default on)
     - Toggle layout mode (hierarchical, force-directed, circular)
     - Reset layout button
     - Search box to highlight a service by name
   - Loading state: show a skeleton or spinner while fetching data. Error state: show the error message and a retry button.
   - WebSocket integration: listen for `service_discovered`, `service_health_changed`, `dependency_detected` events on a new WebSocket connection (`/ws/discovery`). When an event arrives, update the graph in real-time (add new node, change color, add new edge). Use the existing WebSocket hook pattern from the dashboard.

2. Create `frontend/src/components/ServiceDetailsPanel.tsx`:
   - This is a side panel or modal that opens when a node is clicked.
   - Tabs:
     - **Overview**: service name, type, discovery source, host, endpoints, first seen, last seen, uptime percentage.
     - **Health History**: a sparkline chart showing health status over time (last 24 hours). Use a simple SVG chart or `recharts` library. Show timestamps of state changes (up -> down, down -> up).
     - **Incidents**: list of recent incidents for this service (fetch from `GET /incidents?service_name={name}`). Show severity, status, and creation time. Click to open the incident detail.
     - **Dependencies**: mini topology graph showing only this service and its immediate upstream/downstream neighbors (1 hop). Use a smaller React Flow instance or D3 graph. Show dependency details (type, confidence, latency, error rate).
     - **Runbooks**: list of runbooks for this service (fetch from `GET /runbooks?service_name={name}`). Show title and steps. Allow creating a new runbook directly from this panel (reuse the `RunbookPanel` component or a simplified form).
     - **Discovery Metadata**: raw JSON metadata from the discovery process (labels, container info, pod info, process info). This is for debugging/admin purposes. Collapse by default.
   - Actions:
     - **Ignore Service**: exclude this service from monitoring (set a flag in the backend, `ignored = true`). Show a confirmation dialog.
     - **Add Manual Runbook**: open a modal to create a runbook pre-filled with this service name.
     - **View in Logs**: link to `/events?service_name={name}` (or a log viewer if we have one).
     - **Refresh Health**: trigger a manual health probe for this service (POST to a new endpoint, or just refresh the data).
   - Close button or click outside to close.

3. Create `frontend/src/components/DiscoveryEventFeed.tsx`:
   - A real-time event feed showing discovery activities.
   - WebSocket connection to `/ws/discovery`.
   - Events displayed as a list: timestamp, icon, event type, service name, detail. Examples:
     - `🟢 [10:00:00] Service discovered: payment-service (Kubernetes pod)`
     - `🔴 [10:05:00] Health changed: database (down)`
     - `🔵 [10:10:00] Dependency detected: checkout-service -> payment-service (confidence: 0.92)`
     - `⚫ [10:15:00] Service disappeared: old-worker-3 (last seen 5 min ago)`
   - Filter by event type (discovered, removed, health_changed, dependency_detected, dependency_removed) and severity (info, warning, critical).
   - Auto-scroll to the latest event. Pause button to stop auto-scroll. Clear button to clear the feed.
   - Show event count badges in the sidebar (e.g., "3 new services discovered", "1 health alert").
   - Max 100 events in memory, drop oldest when full.

4. Update `frontend/src/App.tsx`:
   - Add a new tab called **"Topology"** that shows the `ServiceTopologyMap`.
   - Add a new tab called **"Discovery Feed"** that shows the `DiscoveryEventFeed`.
   - Update the existing "Service Graph" tab to use the auto-discovered graph if available, falling back to the trace-based graph from Day 12. Or just replace the old graph with the new topology map — the old trace-based graph is a subset of the auto-discovered graph.
   - Ensure the dashboard layout works with the new tabs (no horizontal scrolling, responsive).

5. Add TypeScript types in `frontend/src/types.ts` for all new API responses: `DiscoveredService`, `ServiceHealth`, `AutoDependencyGraph`, `HealthProbeResult`, `DiscoveryEvent`. Match the backend Pydantic schemas exactly.

6. Add `reactflow` and `@dagrejs/dagre` (or `elkjs`) to `frontend/package.json`. Run `npm install`.

7. Write basic frontend tests (if the frontend test framework is set up, or just verify the build passes with `npm run build-check`).

---

## Day 44 — WebSocket Discovery Events & Real-Time Updates

**Prompt:**

Implement the backend WebSocket endpoint for discovery events and wire it into the frontend.

1. Create `backend/app/routers/discovery_ws.py` with a WebSocket endpoint `/ws/discovery`. It should:
   - Reuse the existing WebSocket connection manager pattern from `websocket.py` (or create a new `DiscoveryConnectionManager` if the event types are different).
   - Accept WebSocket connections at `/ws/discovery`.
   - On connection, send the current list of discovered services and the current dependency graph to the client (so the client has initial data without waiting for events).
   - Listen for discovery events from the discovery engine and broadcast them to all connected clients.
   - Events to broadcast:
     - `service_discovered`: `{ "event_type": "service_discovered", "service": DiscoveredService }`
     - `service_removed`: `{ "event_type": "service_removed", "service_id": str, "service_name": str }`
     - `service_health_changed`: `{ "event_type": "service_health_changed", "service_id": str, "service_name": str, "old_status": str, "new_status": str }`
     - `dependency_detected`: `{ "event_type": "dependency_detected", "dependency": ServiceDependency }`
     - `dependency_removed`: `{ "event_type": "dependency_removed", "source_id": str, "target_id": str }`
   - Implement a `DiscoveryEventPublisher` class that the discovery engine, graph builder, and health prober can call to publish events. This class should maintain a list of connected WebSocket clients and broadcast JSON-serialized events. It should be a singleton or stored in the FastAPI app state.
   - Handle client disconnections gracefully (remove from the connection list). Handle connection limits (max 100 clients per endpoint, reject new connections with a 403 if exceeded).
   - Include tenant isolation: if the WebSocket connection includes an `X-API-Key` header or query parameter, verify the tenant and only broadcast events for that tenant. If no auth is provided, allow the connection but only show public/demo data (or reject it — decide based on your auth policy). For simplicity, use the same `get_current_tenant` dependency from `auth.py`.

2. Modify `backend/app/discovery/engine.py` to publish events:
   - When a new service is discovered (not already in the registry), call `publisher.publish_service_discovered(service)`.
   - When a service is removed (stale removal), call `publisher.publish_service_removed(service_id, service_name)`.
   - When a service's heartbeat is updated, check if the health status changed. If it did, call `publisher.publish_health_changed(...)`.

3. Modify `backend/app/discovery/dependencies/graph_builder.py` to publish events:
   - When a new dependency is detected (not already in the registry), call `publisher.publish_dependency_detected(dep)`.
   - When a dependency is removed (stale removal), call `publisher.publish_dependency_removed(source_id, target_id)`.

4. Modify `backend/app/discovery/probing.py` (from Day 39) to publish events:
   - When a health probe changes a service's status (up -> down, down -> up, unknown -> up, etc.), call `publisher.publish_health_changed(...)`.

5. Modify `backend/app/main.py` to:
   - Instantiate the `DiscoveryEventPublisher` and store it in `app.state.discovery_publisher`.
   - Pass the publisher to the `DiscoveryEngine`, `DependencyGraphBuilder`, and `ServiceProber` (or let them access it via `app.state` if you use a singleton pattern).
   - Include the `discovery_ws` router in the app.

6. Update `frontend/src/components/DiscoveryEventFeed.tsx` to connect to `ws://localhost:8000/ws/discovery` (or `wss://` in production). Parse the events and update the feed. On initial connection, the backend sends the current state — the frontend should populate the topology map with this data before any events arrive.

7. Update `frontend/src/components/ServiceTopologyMap.tsx` to listen for WebSocket events and update the graph in real-time:
   - `service_discovered`: add a new node to the React Flow graph.
   - `service_removed`: remove the node and its connected edges.
   - `service_health_changed`: update the node color.
   - `dependency_detected`: add a new edge.
   - `dependency_removed`: remove the edge.
   - Use React Flow's `useNodesState` and `useEdgesState` hooks to manage the graph state. When an event arrives, update the state and React Flow will re-render.

8. Write tests in `backend/tests/discovery/test_discovery_ws.py`. Use `TestClient` with `client.websocket_connect("/ws/discovery")`. Verify the connection is accepted, verify the initial data is sent, verify that publishing an event from the discovery engine results in the client receiving a JSON message. Test disconnection handling. Test auth (with and without API key).

---

## Day 45 — Service Health Probing & Auto-Classification

**Prompt:**

Implement automatic service health probing and service type classification based on protocol detection and response analysis.

1. Create `backend/app/discovery/probing.py` with `ServiceProber` class. It should:
   - Accept a `ServiceRegistry` and `DiscoveryEventPublisher` in its constructor.
   - Implement `async def probe_http(self, service: DiscoveredService) -> HealthProbeResult`:
     - Try common health endpoints in order: `/health`, `/healthz`, `/ready`, `/alive`, `/status`, `/actuator/health`, `/api/health`, `/health/check`.
     - For each endpoint, try `GET http://host:port/endpoint` with a 5-second timeout. If the endpoint is not available (connection refused), try the next one.
     - If the endpoint returns HTTP 200-299, the service is UP. Record the response time, status code, and a truncated response body (first 1024 bytes, or parse JSON and extract a `status` field if present).
     - If the endpoint returns HTTP 400-499, the service is UP but the endpoint doesn't exist (client error). Try the next endpoint.
     - If the endpoint returns HTTP 500+, the service is DOWN. Record the error.
     - If all endpoints fail, the service is UNKNOWN (can't determine health).
     - Handle connection errors (timeout, connection refused) gracefully: try the next endpoint, and if all fail, return UNKNOWN.
     - Use `httpx.AsyncClient` for HTTP requests (it's already a dependency). Configure it with `follow_redirects=True`, `timeout=5.0`.
   - Implement `async def probe_tcp(self, service: DiscoveredService, port: int) -> HealthProbeResult`:
     - Open a TCP connection to `host:port` with a 3-second timeout.
     - If the connection succeeds, the service is UP. Record the connection time.
     - If the connection fails, the service is DOWN. Record the error.
     - This is used for non-HTTP services (databases, caches, message queues) where we can't probe HTTP endpoints.
   - Implement `async def detect_protocol(self, host: str, port: int) -> str`:
     - Send an HTTP/1.1 GET request to the port. If the response is valid HTTP, return `"http"`.
     - If the response looks like HTTP/2 (contains `HTTP/2` or `PRI * HTTP/2.0`), return `"http2"`.
     - If the response starts with a gRPC frame (starts with `0x00` or `0x80` for compressed), return `"grpc"`. This is tricky — for now, just check if the port is 50051 (common gRPC port) and return `"grpc"` if the HTTP probe fails with a non-HTTP response.
     - If none of the above, return `"raw_tcp"`.
     - Use `httpx` for the HTTP probe. If it fails with `RemoteProtocolError` or `ConnectError`, it's likely not HTTP.
   - Implement `async def classify_service(self, service: DiscoveredService, probe_results: List[HealthProbeResult]) -> str`:
     - Classification logic (in order of priority):
       1. If the service was discovered by Kubernetes and has a label `app.kubernetes.io/component`, use that.
       2. If the service was discovered by Docker and the image name contains a known keyword (`postgres`, `mysql`, `redis`, `kafka`, `nginx`, `mongo`, `elasticsearch`, `grafana`, `prometheus`), map to the corresponding type.
       3. If the process name contains a known keyword (`nginx`, `apache`, `postgres`, `redis`, `kafka`, `mongod`, `mysqld`, `elasticsearch`), map to the corresponding type.
       4. If the detected protocol is `http` and the HTTP response contains known framework strings (e.g., `Spring Boot`, `Express`, `Fastify`, `Django`, `Flask`, `FastAPI`, `Rails`, `Laravel`, `ASP.NET`), map to the language/framework type: `java_api`, `nodejs_api`, `python_api`, `ruby_api`, `php_api`, `dotnet_api`. This is done by inspecting the response body or headers (`Server` header, `X-Powered-By` header).
       5. If the port is a known service port, map to the type: 5432 -> `database`, 3306 -> `database`, 6379 -> `cache`, 9092 -> `message_queue`, 11211 -> `cache`, 9200 -> `search`, 5601 -> `dashboard`, 27017 -> `database`, 50051 -> `grpc_api`.
       6. If the detected protocol is `http` and no framework is detected, return `web` (if HTML response) or `api` (if JSON response). Check `Content-Type` header: `text/html` -> `web`, `application/json` -> `api`.
       7. If all else fails, return `unknown`.
     - Update the service in the registry with the classified type.
   - Implement `async def probe_all_services(self) -> List[HealthProbeResult]`:
     - Get all active services from the registry.
     - For each service, determine which probes to run:
       - If the service has HTTP endpoints (ports 80, 443, 8080, 3000, 5000, 8000, 5173), run `probe_http`.
       - If the service has TCP endpoints (other ports), run `probe_tcp` for each port.
     - Run all probes in parallel using `asyncio.gather` with `return_exceptions=True`.
     - For each result, update the service's health status in the registry. If the health status changed, publish a `health_changed` event.
     - Return all probe results.
   - Run every 15 seconds as a background task.

2. Create `HealthProbeResult` Pydantic model in `backend/app/discovery/models.py`: `status` (Enum: `up`, `down`, `unknown`), `probe_type` (Enum: `http`, `tcp`), `endpoint` (Optional[str]), `response_time_ms` (Optional[float]), `response_status_code` (Optional[int]), `response_body_preview` (Optional[str], max 200 chars), `error_message` (Optional[str]), `probed_at` (datetime, UTC). Ensure all datetime fields are timezone-aware.

3. Add `service_health` table to `backend/app/models.py`: `id` (String, primary key), `service_id` (String, index), `status` (String), `probe_results` (JSON), `last_probed_at` (DateTime, timezone=True), `last_up_at` (DateTime, timezone=True, nullable), `last_down_at` (DateTime, timezone=True, nullable), `uptime_percentage` (Float, default 100.0), `tenant_id` (String, index, nullable). Create an Alembic migration for this table.

4. Add `GET /services/health` endpoint to `backend/app/routers/discovery.py`. Return a list of health records for all active services. Include the latest probe result in each record.

5. Add `GET /services/{service_id}/health` endpoint. Return detailed health history for a specific service (last 100 probes, with timestamps and results). Implement pagination with `limit` and `offset` parameters.

6. Modify the `incident_engine.py` to use auto-discovered health status when determining severity. If a service with `service_type = "database"` or `service_type = "message_queue"` is down, increase the incident severity by one level (warning -> critical, info -> warning). This is because infrastructure services are critical.

7. Write tests in `backend/tests/discovery/test_probing.py`. Use `httpx` mock transport or `respx` library to mock HTTP responses. Test each probe type (HTTP success, HTTP failure, TCP success, TCP failure). Test protocol detection (HTTP, gRPC, raw TCP). Test service classification (all logic paths). Test `probe_all_services` parallel execution. Test the background task scheduling. Use a mock `ServiceRegistry` with fake services.

8. Update the `ServiceTopologyMap` frontend component to show health status on nodes (already planned in Day 43, but ensure the data from `/services/health` is properly displayed).

---

## Day 46 — Multi-Environment Integration Tests (Docker)

**Prompt:**

Write comprehensive integration tests for auto-discovery in a Docker environment.

1. Create `tests/integration/test_discovery_docker.py`. This test should:
   - Use `pytest` fixtures to start a Docker Compose stack with 5 services: `nginx` (load balancer), `postgres` (database), `redis` (cache), `python-api` (a simple Python Flask app on port 5000), `nodejs-api` (a simple Node.js Express app on port 3000). The test services should be defined in a `tests/integration/docker-compose.test.yml` file. Use `pytest-docker` plugin or `python-on-whales` library to manage the Docker Compose lifecycle from within the test.
   - Alternatively, mock the Docker SDK entirely (no real Docker containers needed). This is faster and more reliable. Use `unittest.mock` to mock `docker.from_env()` and `client.containers.list()` to return fake containers representing the 5 services. Mock the container attributes to include realistic data (names, images, ports, networks, labels).
   - Start the SignalForge backend with the Docker discovery provider enabled.
   - Wait for the discovery engine to run at least one cycle (use `time.sleep(2)` or poll the `/services/discovered` endpoint until 5 services are found).
   - Verify all 5 services are discovered within 60 seconds. Check each service's name, type, and endpoints.
   - Verify the dependency graph is detected. The Python API and Node.js API should connect to Postgres and Redis. Use mock network connections or mock traffic logs to simulate this. For the mock approach, mock `psutil.net_connections()` to show connections from the Python API process to Postgres port 5432 and Redis port 6379.
   - Verify health probes return correct status for each service. Mock `httpx` responses for the Python API and Node.js API health endpoints. Mock `probe_tcp` for Postgres and Redis.
   - Verify service classification is correct: nginx -> `load_balancer`, postgres -> `database`, redis -> `cache`, python-api -> `python_api` (or `api`), nodejs-api -> `nodejs_api` (or `api`).
   - Verify the `GET /graph/auto` endpoint returns a graph with the expected nodes and edges.
   - Dynamic discovery test: add a new container to the mock (simulate a new service starting). Verify the discovery engine detects it within the next cycle. Remove a container. Verify it's marked as stale and removed.
   - Clean up: stop the Docker Compose stack (if using real Docker) or reset mocks (if using mocked approach).

2. Create `tests/integration/docker-compose.test.yml` (only needed if using real Docker). Define the 5 services with minimal configurations. Use `python:3.12-slim` for the Python API with a simple `CMD ["python", "-m", "http.server", "5000"]`. Use `node:20-alpine` for the Node.js API with a simple `CMD ["npx", "http-server", "-p", "3000"]`. Use `nginx:alpine` for nginx. Use `postgres:16-alpine` and `redis:7-alpine`. All services should be on the same Docker network so they can see each other.

3. If using the mocked approach (recommended for speed and reliability), create `tests/integration/docker_mocks.py` with helper functions to create mock Docker containers and mock `psutil` connections. This makes the tests reusable and maintainable.

4. Write a `tests/integration/README.md` explaining how to run the integration tests. Include the command: `pytest tests/integration/test_discovery_docker.py -v`.

5. Ensure the tests run in CI. Update `.github/workflows/ci.yml` (or create it) to run the integration tests. If using real Docker, the CI runner needs Docker installed (GitHub Actions `ubuntu-latest` has it by default). If using mocks, no special CI setup is needed.

---

## Day 47 — Multi-Environment Integration Tests (Kubernetes & Bare Metal)

**Prompt:**

Write integration tests for Kubernetes and bare metal environments.

1. Create `tests/integration/test_discovery_kubernetes.py`. This test should:
   - Mock the Kubernetes API using `unittest.mock`. Mock `kubernetes.config.load_kube_config` (or `load_incluster_config`) to avoid needing a real cluster. Mock `kubernetes.client.CoreV1Api` and its methods: `list_pod_for_all_namespaces`, `list_service_for_all_namespaces`, `list_node`.
   - Create fake Kubernetes data: 3 pods in namespace `default` with labels `app=frontend`, `app=api`, `app=database`. Create corresponding services for each pod. Create a node.
   - The fake pods should have realistic attributes: names, IPs, container ports, labels, status. The services should have cluster IPs and selector labels matching the pods.
   - Start the SignalForge backend with the Kubernetes discovery provider enabled (using the mocked API).
   - Run the discovery engine.
   - Verify all 3 services are discovered. Check service names are derived from pod labels (`frontend`, `api`, `database`). Check endpoints are derived from pod IPs and container ports.
   - Verify the `ServiceRegistry` stores the Kubernetes metadata (labels, namespace, node name, pod name).
   - Verify RBAC handling: test that if the Kubernetes API returns a 403 Forbidden (insufficient permissions), the provider logs a warning and returns an empty list. Test that the backend continues to function (falls back to other providers or config).
   - Dynamic test: add a new pod to the mock. Verify it's discovered in the next cycle. Delete a pod. Verify it's marked stale and removed.
   - Test namespace filtering: set `SIGNALFORGE_K8S_NAMESPACE=default` and verify only pods in that namespace are discovered. Set it to empty and verify all namespaces are discovered.
   - Test ClusterRole vs Role: if `clusterRole: true` (default), verify the provider calls `list_pod_for_all_namespaces`. If `clusterRole: false`, verify it calls `list_namespaced_pod`.

2. Create `tests/integration/test_discovery_baremetal.py`. This test should:
   - Mock `psutil` to simulate system processes. Use `unittest.mock` to patch `psutil.process_iter` and `process.connections`. Create fake processes: nginx (PID 1001, port 80), postgres (PID 1002, port 5432), redis (PID 1003, port 6379), python (PID 1004, port 5000), node (PID 1005, port 3000).
   - Start the SignalForge backend with the process discovery provider enabled.
   - Run the discovery engine.
   - Verify all 5 services are discovered. Check service names are derived from process names. Check endpoints are derived from listening ports.
   - Verify system processes are skipped (e.g., `systemd`, `svchost`, `kernel`).
   - Verify `psutil` PermissionError is handled gracefully (skip processes that can't be inspected, log a warning).
   - Verify the `ServiceRegistry` stores process metadata (PID, command line, username).
   - Test the `EnvironmentDetector` for bare metal: verify it returns `['process', 'config']` as the providers.

3. Create `tests/integration/test_discovery_mixed.py`. This test should:
   - Simulate a hybrid environment: some services are discovered via Docker, some via Kubernetes, some via process scanning. This is realistic for development environments where Docker Desktop runs a Kubernetes cluster and also has standalone containers.
   - Mock all three providers simultaneously. Verify the `DiscoveryEngine` deduplicates services correctly (by `service_name + host`). If the same service is discovered by multiple providers (e.g., a Docker container named `api` and a Kubernetes pod labeled `app=api`), verify the registry stores the merged metadata from all providers (or picks the most recent, based on your deduplication logic).
   - Verify the `discovery_source` field shows the primary source or all sources.

4. Create a `tests/integration/conftest.py` with shared fixtures for the mocked providers, mock ServiceRegistry, and mock DiscoveryEngine. This keeps the test files DRY.

5. Document how to run the tests in `tests/integration/README.md`. Include the command to run all integration tests: `pytest tests/integration/ -v`.

---

## Day 48 — Performance & Scalability Testing

**Prompt:**

Create performance tests to verify auto-discovery scales to 100+ services and 1000+ dependencies.

1. Create `tests/performance/test_discovery_scale.py`. This test should:
   - Simulate a large environment with 100 services and 500 dependencies. Create mock data: 100 `DiscoveredService` objects with random names, types, endpoints, and hosts. Create 500 `ServiceDependency` objects with random source/target pairs, types, and confidence scores.
   - Measure discovery engine latency: time the `DiscoveryEngine.run_discovery()` method with the mocked providers. The providers should return the 100 services instantly (no real I/O). The measurement should focus on the engine's deduplication, registry updates, and database writes. Verify the cycle completes in < 10 seconds (actually it should be much faster with mocks, but set a generous threshold).
   - Measure memory usage: use `tracemalloc` or `psutil.Process().memory_info()` to check the memory footprint of the `ServiceRegistry` with 100 services. Verify it stays under 200 MB. With 100 services, the memory should be negligible (< 10 MB), so this test is more about establishing a baseline.
   - Measure database write latency: time the `DependencyRegistry` upsert operation for 500 dependencies. Verify it completes in < 5 seconds. This tests the SQLAlchemy batch insert/update performance.
   - Measure graph query latency: time the `DependencyGraphBuilder.get_graph()` query with 100 services and 500 dependencies. Verify it completes in < 100 ms. Test `get_upstream()`, `get_downstream()`, and `get_critical_path()` with various service IDs. Verify all queries complete in < 100 ms.
   - Measure graph rendering data size: serialize the `DependencyGraph` to JSON. Verify the JSON size is < 1 MB. With 100 nodes and 500 edges, the JSON should be around 100-200 KB.

2. Create `tests/performance/test_event_correlation_scale.py`. This test should:
   - Simulate 1000 events per second from 100 different services. Create 1000 `TelemetryEvent` objects with random metadata (IP, hostname, container ID, pod name, process ID). Each event should be correlatable to exactly one of the 100 services.
   - Measure correlation latency: time the `EventServiceCorrelator.correlate()` method for one event. Run it 1000 times and calculate average, p95, and p99. Verify average latency is < 1 ms per event. The correlator should use the in-memory cache from the `ServiceRegistry`, so lookups should be very fast.
   - Measure correlation accuracy: count how many of the 1000 events are correctly correlated to their intended service. Verify accuracy is > 95%. The 5% error rate accounts for ambiguous events (e.g., two services on the same IP with different ports, or events missing all metadata).
   - Measure uncorrelated event queue: send 100 events with no metadata (empty attributes). Verify they are all marked as uncorrelated. Verify the uncorrelated queue doesn't grow unbounded: when it exceeds 1000 events, the oldest events should be dropped (FIFO). Test this by sending 1500 uncorrelated events and verifying the queue has 1000.

3. Create `tests/performance/test_graph_query_scale.py`. This test should:
   - Build a `DependencyGraph` with 100 services and 500 dependencies. Use the `DependencyGraphBuilder` to create the graph from the mock registry data.
   - Measure query latency for: `get_all_dependencies()` (all 500 edges), `get_upstream(service_id)` (average ~5 edges per service), `get_downstream(service_id)` (average ~5 edges per service), `get_critical_path(source_id, target_id)` (BFS shortest path, should be fast).
   - Run each query 100 times and calculate average, p95, p99. Verify all queries complete in < 100 ms.
   - Test the frontend rendering data size: serialize the graph to the same JSON format used by the `GET /graph/auto` endpoint. Verify the JSON size is < 1 MB. With 100 nodes and 500 edges, this should be well under 1 MB.

4. Create `tests/performance/conftest.py` with shared fixtures for generating mock services, mock dependencies, and mock events. Use `faker` library or simple random generation.

5. Add a GitHub Actions workflow (`.github/workflows/performance-tests.yml`) that runs the performance tests on every push to the main branch. These tests should be fast (< 30 seconds total) and should not block CI if they fail (use `continue-on-error: true` for the performance job, or make them optional).

6. Document the performance test results in a `PERFORMANCE.md` file. Include the expected metrics, the actual metrics (from the latest test run), and the methodology. Update this file periodically as the system improves.

---

## Day 49 — Documentation Updates & Resume Polish

**Prompt:**

Update all project documentation for the auto-discovery feature and create final resume/interview materials.

1. Update `README.md`:
   - Add a prominent "Zero-Config Auto-Discovery" section at the top (after the one-line description). This is the key differentiator. Include a short paragraph: "SignalForge automatically detects your services, maps their dependencies, and monitors their health — no manual configuration required. Deploy it on any system and it discovers what you have."
   - Add a new architecture diagram that includes the discovery layer (before the existing 3-layer diagram). Show: `Discovery Engine -> Service Registry -> Dependency Graph -> Event Correlation -> Core SignalForge`.
   - Update the "Quick Start" section to emphasize auto-discovery: after `docker-compose up -d`, run `curl http://localhost:8000/services/discovered` to see the auto-discovered services.
   - Add a "Supported Environments" section listing: Docker, Kubernetes (kind, minikube, EKS, GKE, AKS), bare metal, AWS ECS, AWS EKS, Azure AKS, GCP GKE. Include small icons or badges for each.
   - Add a "How Auto-Discovery Works" section with a simple explanation of the 3-phase process: (1) scan environment for services, (2) analyze traffic to find dependencies, (3) correlate events to services. Keep it high-level and non-technical for recruiters and hiring managers.
   - Add a screenshot placeholder or ASCII art of the topology map. Describe what the user sees: "An interactive map of all your services, automatically generated, with health status, dependency arrows, and confidence scores."
   - Update the "What Makes This Production-Ready" section to include auto-discovery bullets: auto-detects 100+ services in < 10 seconds, maps dependencies across 4 techniques with confidence scoring, classifies service types automatically, one-command installation.

2. Update `ARCHITECTURE_SUMMARY.md`:
   - Add the discovery layer to the 3-layer architecture. Now it's a 4-layer model: discovery, streaming, hot state, durable storage.
   - Add discovery metrics to the performance table: discovery cycle time (target: < 10s for 100 services), correlation accuracy (target: > 95%), dependency confidence (target: > 0.8 for 80% of edges).
   - Add the supported environments to the tech stack table.
   - Add a "Discovery Providers" section listing the 6 providers: process, Docker, Kubernetes, AWS, Azure, GCP, config, manual.
   - Add a "Dependency Inference Techniques" section listing: network scanning, traffic analysis, distributed tracing, service mesh telemetry.

3. Update `INTERVIEW_GUIDE.md`:
   - Add a new "Auto-Discovery" section after the existing 30-second pitch. Include:
     - "How does SignalForge discover my services without configuration?" — explain the multi-provider architecture and environment detection.
     - "How does it map dependencies?" — explain the 4 techniques and confidence scoring.
     - "What if I have 500 microservices?" — explain the scalability limits and performance numbers.
     - "What if a service is ephemeral (serverless/spot instances)?" — explain how discovery handles short-lived services and removes stale entries.
     - "How does it correlate events to services?" — explain the 7 matching strategies and fallback handling.
     - "What about security? Does it need cluster-admin?" — explain RBAC/IAM least-privilege requirements.
     - "How accurate is the dependency graph?" — explain confidence scoring, validation, and manual override capabilities.
   - Add a "Zero-Config Deployment" talking point for the 2-minute and 5-minute explanations: "One command to install, one command to start, and your entire architecture is visible in the dashboard. No manual service lists, no dependency maps, no configuration files."
   - Update the live demo script to include auto-discovery steps: after starting the stack, show the auto-discovered services before generating any traffic. This demonstrates that the system works even with zero input.
   - Update the "One-Page Cheat Sheet" with the new metrics: discovery time, correlation accuracy, dependency confidence, classification accuracy, zero-config environments, installation time.

4. Update `DEMO.md`:
   - Add an "Auto-Discovery Demo" section at the beginning (before the existing seed script demo). This section should show how to run SignalForge on a system with unknown services and watch it discover them.
   - Step 1: Start the stack with Docker Compose. Step 2: Check `/services/discovered` — you'll see nginx, postgres, redis, and any other containers in the network. Step 3: Check `/graph/auto` — you'll see dependencies between them (e.g., the backend connects to postgres and redis). Step 4: Check `/services/health` — you'll see health status for each service. Step 5: Start the simulator and watch the topology map update in real-time as the new services and dependencies are detected.
   - Add the new API endpoints to the cheat sheet: `GET /services/discovered`, `GET /graph/auto`, `GET /services/health`, `GET /services/{id}/dependencies`, `GET /events/uncorrelated`.

5. Update `AWS_ARCHITECTURE.md`:
   - Add IAM roles and permissions for AWS service discovery. For ECS: `ecs:ListClusters`, `ecs:ListServices`, `ecs:ListTasks`, `ecs:DescribeTasks`, `ecs:DescribeContainerInstances`. For EKS: the existing Kubernetes RBAC permissions, plus `eks:DescribeCluster` (optional). For EC2: `ec2:DescribeInstances` (optional, for VM discovery).
   - Add Kubernetes RBAC requirements for pod/service discovery. List the exact API resources and verbs: `pods` (get, list, watch), `services` (get, list, watch), `endpoints` (get, list, watch), `nodes` (get, list, watch), `deployments` (get, list, watch), `replicasets` (get, list, watch), `statefulsets` (get, list, watch), `daemonsets` (get, list, watch), `namespaces` (get, list, watch).
   - Add CloudWatch agent integration: the CloudWatch agent can be configured to collect application logs and forward them to SignalForge for traffic analysis. This is an optional enhancement for environments where direct log file access is not possible (e.g., AWS Fargate).

6. Create `docs/ENVIRONMENTS.md`:
   - Detailed setup guides for each environment: Docker, Kubernetes (kind, EKS, GKE, AKS), bare metal, AWS ECS, Azure Container Instances, GCP Cloud Run.
   - For each environment:
     - Prerequisites (Docker, kubectl, Helm, etc.)
     - Installation command (one-liner)
     - Configuration options (env vars, config file)
     - Verification steps (check `/services/discovered`, `/health`, `/graph/auto`)
     - Troubleshooting section (common issues and solutions)
     - Security considerations (RBAC, IAM roles, network policies, security groups)
   - Include code blocks for each step. Make it copy-paste friendly.
   - Include a comparison table: which features work on which environment (e.g., process discovery only works on bare metal and Docker; Kubernetes discovery only works on K8s; service mesh discovery only works on Istio).

7. Create `RESUME_BULLETS.md`:
   - 10-15 powerful resume bullets for the auto-discovery feature. Each bullet should be one sentence, action-oriented, and quantified. Examples:
     - "Architected a zero-config auto-discovery engine that detects services, maps dependencies, and monitors health across bare metal, Docker, Kubernetes, and AWS — no manual configuration required"
     - "Implemented multi-provider service discovery (process scanning, Docker API, Kubernetes API, cloud provider APIs) with environment auto-detection and pluggable architecture"
     - "Built network dependency detection using connection tracking, traffic analysis, distributed tracing, and service mesh telemetry to automatically infer service topology with confidence scoring"
     - "Designed event-to-service correlation engine with 95%+ accuracy using IP/port matching, hostname resolution, container/pod metadata, and trace context propagation"
     - "Created interactive auto-generated topology map with real-time health status, dependency confidence levels, and dynamic filtering — zero manual graph configuration"
     - "Delivered one-command installation (shell script, PowerShell, Helm, Terraform) with environment auto-detection and sensible defaults for any deployment target"
     - "Implemented automatic service health probing with protocol detection (HTTP/gRPC/TCP) and service classification (database/cache/queue/web) based on port, protocol, and response analysis"
     - "Wrote 40+ integration and performance tests covering multi-environment discovery (Docker, Kubernetes, bare metal), dependency graph accuracy, and event correlation at 1000 events/second"

8. Create `INTERVIEW_AUTO_DISCOVERY.md`:
   - A focused interview guide for the auto-discovery feature. This is a supplement to `INTERVIEW_GUIDE.md`, not a replacement.
   - Include the 7 common questions and answers from the interview guide update (Day 49, point 3).
   - Add "Tell me about the hardest part of auto-discovery" — answer: "The multi-provider deduplication logic. When the same service is discovered by process scanning, Docker scanning, and Kubernetes scanning, we need to merge the metadata without losing information. We use a weighted merge strategy that prioritizes the most recent discovery and the most detailed metadata."
   - Add "How do you handle false positives in dependency detection?" — answer: "Confidence scoring. If a dependency is only detected by one analyzer (e.g., a single network connection), it gets a low confidence score (0.3-0.5). If it's detected by multiple analyzers (network + traffic + trace), the confidence increases (0.8-0.95). The dashboard shows dashed or dotted lines for low-confidence dependencies, and users can hide them. We also remove stale dependencies after a timeout if no new evidence is found."
   - Add "How do you prevent the discovery engine from being a security risk?" — answer: "Least privilege. The Kubernetes provider uses a ServiceAccount with minimal RBAC permissions (get/list/watch on pods, services, endpoints). It never needs write access. The Docker provider only needs read access to the Docker socket (and we mount it read-only). The process provider only inspects its own processes unless run as root (which we don't recommend). The cloud provider uses IAM roles with minimal permissions (read-only on ECS/EKS resources). We also support disabling specific providers if they don't meet your security requirements."

9. Update `PROJECT_STATE.md` to reflect all new files, features, and the completion of the auto-discovery enhancement. Add the new files to the file inventory. Update the timeline to include Days 32-50. Update the current phase to "Auto-discovery complete — zero-config deployment on any environment."

---

## Day 50 — Final Polish & Bug Fixes

**Prompt:**

Fix any remaining bugs, polish the codebase, and ensure everything is ready for submission.

1. Run all tests (unit, integration, performance) and fix any failures:
   - `cd backend && pytest tests/ -v`
   - Fix any test failures introduced by the auto-discovery changes.
   - Fix any deprecation warnings (e.g., SQLAlchemy 2.0 warnings, Pydantic v2 warnings).
   - Fix any type errors (run `mypy` if available, or just review the code for obvious type issues).

2. Fix any known bugs from the implementation:
   - Root cause engine timezone mismatch (offset-aware vs offset-naive datetime) — this was a pre-existing bug, but now is the time to fix it. Ensure all datetime comparisons use timezone-aware UTC datetimes. Use `datetime.now(timezone.utc)` everywhere, never `datetime.utcnow()` (deprecated). Ensure the database stores timezone-aware datetimes (SQLAlchemy `DateTime(timezone=True)`).
   - Any memory leaks in the background discovery tasks (ensure tasks are properly cancelled on shutdown, ensure the `ServiceRegistry` cache doesn't grow unbounded).
   - Any race conditions in the `DependencyGraphBuilder` (ensure thread safety if using threads, or use async locks if using asyncio). The graph builder runs as a background task, so it should use `asyncio.Lock` to prevent concurrent updates.
   - Any performance issues in the `EventServiceCorrelator` (ensure the in-memory cache is used, not the database, for fast lookups).

3. Add missing docstrings and type hints to all new functions and classes. Ensure the code is readable and maintainable.

4. Run `black` or `ruff` (code formatters) on all new Python files. Ensure consistent formatting.

5. Verify the frontend builds without errors: `cd frontend && npm run build-check`. Fix any TypeScript errors or React warnings.

6. Verify the Docker Compose stack works: `docker-compose up -d` and then `curl http://localhost:8000/services/discovered`. Verify services are auto-discovered. Verify the topology map shows the auto-discovered graph. If running in a real environment (not just mocks), verify the process discovery shows the host processes and the Docker discovery shows the containers.

7. Verify the Helm chart works: `helm lint helm/signforge/`. Fix any lint errors. Use `helm template` to render the templates and verify they look correct.

8. Verify the Terraform modules work: `terraform validate` in each module directory. Fix any validation errors.

9. Final documentation review:
   - Read through `README.md` from top to bottom. Fix any broken links, outdated commands, or incorrect information.
   - Read through `DEMO.md`. Ensure the demo commands are correct and produce the expected output.
   - Read through `INTERVIEW_GUIDE.md`. Ensure all answers are accurate and reflect the current implementation.
   - Read through `ARCHITECTURE_SUMMARY.md`. Ensure all numbers and metrics are up-to-date.

10. Write a final `CHANGELOG.md` or update `PROJECT_STATE.md` with a summary of all changes in Days 32-50. List the new features, the new files, the bug fixes, and the performance improvements.

11. Create a final commit with all changes: `git add -A && git commit -m "Day 50: auto-discovery complete — zero-config deployment, multi-provider service discovery, dependency inference, event correlation, health probing, topology dashboard, Helm chart, Terraform modules, install scripts, comprehensive tests and documentation"` and push to origin.

---

## Day 51-55 (Optional Deep Polish)

If time allows, add these advanced features for extra resume impact:

| Day | Feature | Resume Bullet |
|-----|---------|---------------|
| 51 | **eBPF-based dependency detection** (Linux only) | "Implemented eBPF-based kernel-level network tracing for dependency detection with zero overhead" |
| 52 | **Service mesh integration (Istio/Linkerd)** | "Integrated with Istio and Linkerd for automatic service mesh telemetry ingestion" |
| 53 | **Custom discovery provider SDK** | "Published a plugin SDK allowing users to write custom discovery providers in Python" |
| 54 | **ML-based anomaly detection** | "Trained a custom ML model on historical telemetry for anomaly detection with 99% precision" |
| 55 | **Multi-tenant service discovery** | "Implemented namespace-aware and tenant-aware discovery for multi-tenant environments" |

---

## Day 56-60 (Final QA & Submission)

| Day | Task |
|-----|------|
| 56 | Full end-to-end test on a clean environment (new VM, no existing config) |
| 57 | Performance benchmark on a real Kubernetes cluster (EKS or GKE) |
| 58 | Security audit (RBAC, IAM, network policies) and documentation |
| 59 | Final demo script with auto-discovery narrative and talking points |
| 60 | Submission package: GitHub repo, README, demo video/script, architecture docs |

