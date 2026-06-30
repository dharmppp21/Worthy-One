# Integration Tests

This directory contains integration tests that verify the full SignalForge
discovery pipeline end-to-end without requiring real Docker containers.

## Approach: Fully Mocked

All tests use `unittest.mock` to simulate Docker, psutil, HTTP, and TCP
probes. This makes them fast, deterministic, and CI-friendly.

- **Docker**: `docker_mocks.py` provides fake containers that quack like real
  `docker.Container` objects. Port bindings use the container IP as `HostIp`
  so endpoints match the mocked psutil `raddr` tuples.
- **Network**: `psutil.net_connections()` is mocked to return fake connections
  showing the Python/Node APIs talking to Postgres and Redis. `raddr` is a
  proper object with `.ip` and `.port` attributes (not a bare tuple) so the
  `NetworkConnectionScanner` can read it correctly.
- **HTTP**: `httpx.AsyncClient.get` is mocked so the Python/Node APIs return
  `200 OK` on their health endpoints; everything else returns `404`.
- **TCP**: `asyncio.open_connection` is mocked so all TCP probes succeed.

## Test Coverage

| Test Class | What it checks |
|---|---|
| `TestDockerDiscovery` | All 5 services discovered, correct types, endpoints populated |
| `TestHealthProbes` | Health endpoint returns UP for all services, paginated history |
| `TestDependencyGraph` | Graph edges between Python API ↔ Postgres/Redis, Nginx ↔ APIs |
| `TestDynamicDiscovery` | New container detected, removed container marked stale |

## Running

```bash
# From the backend directory
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_docker.py -v

# With coverage
.venv/Scripts/python.exe -m pytest tests/integration/test_discovery_docker.py -v --cov=app.discovery
```

## Files

| File | Purpose |
|---|---|
| `docker_mocks.py` | Factory functions for fake Docker containers and psutil connections |
| `test_discovery_docker.py` | Integration test suite |
| `README.md` | This file |
