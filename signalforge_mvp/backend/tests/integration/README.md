# Integration Tests

This directory contains integration tests that verify the full SignalForge
discovery pipeline end-to-end across **Docker, Kubernetes, and bare metal**
environments without requiring real infrastructure.

## Approach: Fully Mocked

All tests use `unittest.mock` to simulate Docker, Kubernetes, psutil, HTTP, and TCP
probes. This makes them fast, deterministic, and CI-friendly.

- **Docker**: `docker_mocks.py` provides fake containers that quack like real
  `docker.Container` objects. Port bindings use the container IP as `HostIp`
  so endpoints match the mocked psutil `raddr` tuples.
- **Kubernetes**: `test_discovery_kubernetes.py` builds fake `V1Pod` objects that
  quack like the Kubernetes Python client. The `CoreV1Api`, `load_config`, and
  `ApiException` are all patched.
- **Process / Bare Metal**: `test_discovery_baremetal.py` mocks `psutil.process_iter`
  and `proc.connections()` to return fake processes with listening ports.
- **Network**: `psutil.net_connections()` is mocked to return fake connections
  showing the Python/Node APIs talking to Postgres and Redis. `raddr` is a
  proper object with `.ip` and `.port` attributes (not a bare tuple) so the
  `NetworkConnectionScanner` can read it correctly.
- **HTTP**: `httpx.AsyncClient.get` is mocked so the Python/Node APIs return
  `200 OK` on their health endpoints; everything else returns `404`.
- **TCP**: `asyncio.open_connection` is mocked so all TCP probes succeed.

## Test Coverage

### Docker (`test_discovery_docker.py`)

| Test Class | What it checks |
|---|---|
| `TestDockerDiscovery` | All 5 services discovered, correct types, endpoints populated |
| `TestHealthProbes` | Health endpoint returns UP for all services, paginated history |
| `TestDependencyGraph` | Graph edges between Python API ↔ Postgres/Redis, Nginx ↔ APIs |
| `TestDynamicDiscovery` | New container detected, removed container marked stale |

### Kubernetes (`test_discovery_kubernetes.py`)

| Test Class | What it checks |
|---|---|
| `TestKubernetesDiscovery` | All 3 pods discovered, correct types, endpoints from pod IP + port |
| `TestKubernetesRBAC` | 403 Forbidden returns empty list, backend continues functioning |
| `TestKubernetesDynamic` | New pod detected, deleted pod marked stale |
| `TestKubernetesNamespace` | Namespace filtering (`default` vs all namespaces) |
| `TestKubernetesClusterRole` | `list_pod_for_all_namespaces` vs `list_namespaced_pod` |

### Bare Metal (`test_discovery_baremetal.py`)

| Test Class | What it checks |
|---|---|
| `TestBareMetalDiscovery` | All 5 processes discovered, correct names, endpoints, types |
| `TestBareMetalSystemProcesses` | systemd, svchost, kernel skipped |
| `TestBareMetalPermissionError` | PermissionError and NoSuchProcess handled gracefully |
| `TestBareMetalMetadata` | PID, command line, username stored in registry |
| `TestBareMetalEnvironmentDetector` | Returns `['process', 'config']` for plain VMs |

### Mixed / Hybrid (`test_discovery_mixed.py`)

| Test Class | What it checks |
|---|---|
| `TestMixedDiscovery` | All three providers active simultaneously, 8+ unique services |
| `TestMixedDeduplication` | Same (name, host) deduplicated; different hosts kept separate |
| `TestMixedDiscoverySource` | `discovery_source` field reflects the discovering provider |

## Running

```bash
# From the backend directory
# All integration tests
.venv/Scripts/python.exe -m pytest tests/integration/ -v

# Docker only
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_docker.py -v

# Kubernetes only
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_kubernetes.py -v

# Bare metal only
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_baremetal.py -v

# Mixed only
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_mixed.py -v

# With coverage
.venv/Scripts/python.exe -m pytest tests/integration/ -v --cov=app.discovery
```

## Files

| File | Purpose |
|---|---|
| `conftest.py` | Shared fixtures: DB, registry, discovery engine, cleanup |
| `docker_mocks.py` | Factory functions for fake Docker containers and psutil connections |
| `test_discovery_docker.py` | Docker integration test suite |
| `test_discovery_kubernetes.py` | Kubernetes integration test suite |
| `test_discovery_baremetal.py` | Bare metal / process integration test suite |
| `test_discovery_mixed.py` | Hybrid environment integration test suite |
| `README.md` | This file |
