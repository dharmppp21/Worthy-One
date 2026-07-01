# SignalForge — Environment-Specific Discovery Guide

How SignalForge auto-discovers services across Docker, Kubernetes, AWS, Azure, GCP, and bare-metal environments.

---

## Overview

SignalForge's discovery engine detects the runtime environment and automatically configures the appropriate discovery providers. No manual service registration is required — the system finds services, probes their health, classifies their type, and correlates telemetry events to them.

**Key capabilities:**
- **Environment auto-detection:** Automatically detects if running in Docker, Kubernetes, AWS, Azure, GCP, or on a VM.
- **Multi-provider discovery:** Concurrently scans Docker containers, Kubernetes pods, host processes, cloud metadata, and static config.
- **Health probing:** HTTP and TCP health checks with auto-detection of common endpoints (`/health`, `/healthz`, `/ready`, `/actuator/health`).
- **Service classification:** Automatically classifies services as `database`, `cache`, `api`, `web`, `message_queue`, `monitoring`, etc. using image names, process names, ports, and HTTP response analysis.
- **Event correlation:** Matches telemetry events to discovered services by name, IP, container ID, pod name, or process ID — no manual `service_name` required.
- **Real-time WebSocket feed:** Live discovery events (new services, health changes, dependency detection) pushed to the dashboard.

---

## Discovery Providers

| Provider | Source | What It Finds | Environment |
|----------|--------|---------------|-------------|
| **Docker** | Docker daemon API | Containers, images, port mappings, labels, Compose service names | Docker Desktop, Docker Compose, ECS |
| **Kubernetes** | K8s API (in-cluster or kubeconfig) | Pods, services, labels, container ports, namespaces | EKS, GKE, AKS, Minikube |
| **Process** | `psutil` + `netstat` | Listening processes, PIDs, executable names, ports | Bare metal, VMs, local dev |
| **Config** | `SIGNALFORGE_SERVICES` env var or config file | Static service definitions (JSON/YAML) | All environments |
| **Cloud** | AWS/Azure/GCP metadata endpoints | Cloud-native service metadata, IAM roles, tags | AWS ECS/EKS, GCP GKE, Azure AKS |

**How providers are selected:**
- The `EnvironmentDetector` class checks the runtime environment on startup.
- `SIGNALFORGE_DISCOVERY_PROVIDERS` env var can override auto-detection (comma-separated list).
- If no env var is set, the engine auto-configures providers based on detected environment.
- `docker` provider requires `docker` Python SDK and Docker daemon access.
- `kubernetes` provider requires `kubernetes` Python SDK and in-cluster config or kubeconfig.
- `process` provider requires `psutil` and is safe for local dev (system processes are blocklisted).
- `config` provider always works — zero dependencies.

---

## Environment Matrix

### Docker Compose (Local Development)

```yaml
# docker-compose.yml
services:
  backend:
    image: signforge-backend
    environment:
      - SIGNALFORGE_DISCOVERY_ENABLED=true
      - SIGNALFORGE_DISCOVERY_PROVIDERS=docker,config,process
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # Required for Docker discovery
    pid: host  # Required for process discovery (local dev only)
```

**What gets discovered:**
- Other containers in the same network (e.g., `postgres`, `redis`, `kafka`)
- Host processes (e.g., nginx, local dev servers) — only if `pid: host`
- Static services from mounted `config.yaml`

**Verify discovery:**
```bash
curl http://localhost:8000/services/discovered
curl http://localhost:8000/services/health
curl http://localhost:8000/services/dependencies
```

---

### Kubernetes (EKS / GKE / AKS)

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --set discovery.enabled=true \
  --set discovery.providers=kubernetes,config,cloud \
  --set rbac.create=true
```

**What gets discovered:**
- Pods in the same namespace (and optionally cluster-wide)
- Kubernetes services with endpoints
- Cloud metadata (AWS instance tags, GCP labels, Azure VM tags)

**RBAC requirements:**
- The Helm chart includes a `ClusterRole` or `Role` for reading pods and services.
- The service account must have `get`, `list` on `pods` and `services`.

**Verify discovery:**
```bash
kubectl exec -it deploy/signforge-backend -- curl http://localhost:8000/services/discovered
kubectl logs deploy/signforge-backend | grep "discovery"
```

---

### AWS ECS Fargate

```json
{
  "environment": [
    {"name": "SIGNALFORGE_DISCOVERY_ENABLED", "value": "true"},
    {"name": "SIGNALFORGE_DISCOVERY_PROVIDERS", "value": "cloud,config"},
    {"name": "AWS_EXECUTION_ENV", "value": "AWS_ECS_FARGATE"}
  ]
}
```

**What gets discovered:**
- ECS task metadata via `AWS_CONTAINER_METADATA_URI` (v4 endpoint)
- AWS Cloud Map service discovery (if configured)
- Cloud metadata from `169.254.169.254` (instance tags, IAM roles, region)
- Static config from Secrets Manager or env vars

**Note:** ECS Fargate does not support `docker` or `process` discovery due to security constraints. Use `cloud` + `config` providers.

---

### AWS EC2 / Azure VM / GCP Compute Engine

```bash
# Bare VM with process discovery
export SIGNALFORGE_DISCOVERY_ENABLED=true
export SIGNALFORGE_DISCOVERY_PROVIDERS=process,config,cloud
```

**What gets discovered:**
- Listening processes on the VM (e.g., nginx, postgres, custom apps)
- Cloud metadata (instance tags, region, account/ project ID)
- Static config from local files or env vars

**Security note:** Process discovery is safe — it skips system processes (Windows svchost, kernel, etc.) and only reports listening ports with executable names.

---

### Production Hardening

| Environment | Recommended Providers | Why |
|-------------|----------------------|-----|
| Docker Compose (dev) | `docker,config,process` | Full visibility, local dev convenience |
| Docker Compose (prod) | `docker,config` | `process` disabled for security |
| Kubernetes | `kubernetes,config,cloud` | Native pod/service discovery, cloud tags |
| AWS ECS | `cloud,config` | No container/process access in Fargate |
| AWS EC2 | `process,config,cloud` | VM-level process discovery, cloud metadata |
| Azure VM | `process,config,cloud` | Same as EC2 |
| GCP Compute | `process,config,cloud` | Same as EC2 |

**Disable process discovery in containers:**
```yaml
# docker-compose.prod.yml
services:
  backend:
    environment:
      - SIGNALFORGE_DISCOVERY_PROVIDERS=config  # Only static config
```

---

## Configuration Reference

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `SIGNALFORGE_DISCOVERY_ENABLED` | `false` | Master switch for discovery |
| `SIGNALFORGE_DISCOVERY_PROVIDERS` | `auto` | Comma-separated provider list or `auto` |
| `SIGNALFORGE_DISCOVERY_INTERVAL` | `30` | Discovery run interval in seconds |
| `SIGNALFORGE_PROBE_INTERVAL` | `15` | Health probe interval in seconds |
| `SIGNALFORGE_SERVICES` | — | JSON string of static services |
| `SIGNALFORGE_SERVICES_CONFIG` | — | Path to JSON/YAML config file |
| `SIGNALFORGE_DISCOVERY_NAMESPACE` | `default` | Kubernetes namespace to scan |
| `SIGNALFORGE_DISCOVERY_STALE_TIMEOUT` | `120` | Seconds before a service is marked stale |

**Static config example (JSON):**
```json
[
  {
    "name": "payment-service",
    "type": "api",
    "host": "10.0.1.15",
    "endpoints": ["http://10.0.1.15:8080"],
    "metadata": { "team": "payments", "tier": "critical" }
  }
]
```

**Static config example (YAML):**
```yaml
- name: payment-service
  type: api
  host: 10.0.1.15
  endpoints:
    - http://10.0.1.15:8080
  metadata:
    team: payments
    tier: critical
```

---

## WebSocket Discovery Events

Connect to `/ws/discovery` to receive real-time events:

```json
{"type": "service_discovered", "service_name": "postgres", "service_id": "...", "severity": "info"}
{"type": "health_changed", "service_name": "redis", "old_status": "up", "new_status": "down", "severity": "critical"}
{"type": "dependency_detected", "source": "checkout-service", "target": "payment-service", "severity": "info"}
{"type": "service_removed", "service_name": "old-worker", "severity": "warning"}
```

The frontend `DiscoveryEventFeed` component displays these events with color-coded severity and filtering.

---

## Troubleshooting

### No services discovered

1. Check `SIGNALFORGE_DISCOVERY_ENABLED=true`
2. Check provider-specific prerequisites (Docker socket, K8s RBAC, psutil)
3. Check logs: `docker logs signforge-backend | grep discovery`
4. Verify the provider health endpoint: `GET /services/discovery-status`

### Docker discovery fails
- Ensure `/var/run/docker.sock` is mounted.
- Ensure the container has read access to the socket.
- The `docker` Python SDK must be installed (`pip install docker`).

### Kubernetes discovery fails
- Check RBAC: `kubectl auth can-i list pods --as=system:serviceaccount:monitoring:signforge`
- Ensure the K8s Python SDK is installed (`pip install kubernetes`).
- Check in-cluster config: `cat /var/run/secrets/kubernetes.io/serviceaccount/token`

### Process discovery shows system services
- System processes are blocklisted, but some edge cases may slip through.
- Use `SIGNALFORGE_DISCOVERY_PROVIDERS` to exclude `process` if needed.

---

## See Also

- [`AWS_ARCHITECTURE.md`](AWS_ARCHITECTURE.md) — AWS deployment with ECS/EKS discovery
- [`README.md`](README.md) — Quick start and Docker Compose setup
- [`INTERVIEW_AUTO_DISCOVERY.md`](INTERVIEW_AUTO_DISCOVERY.md) — Interview deep-dive on auto-discovery
- `backend/app/discovery/` — Source code for the discovery engine
