# Performance Tests

This directory contains performance and scalability benchmarks for the SignalForge
discovery, correlation, and graph subsystems. The tests use deterministic mock
data so they are fast, reproducible, and CI-friendly.

## Data Scale

| Dataset | Size |
|---|---|
| Services | 100 |
| Dependencies | 500 |
| Correlated Events | 1,000 |
| Uncorrelated Events | 1,000 |

All data is generated deterministically (seed = 42) so results are comparable
across runs and machines.

## Test Files

| File | What it measures |
|---|---|
| `test_discovery_scale.py` | Discovery engine latency, memory footprint, DB write latency, graph query latency, JSON serialization size |
| `test_event_correlation_scale.py` | Correlation latency (avg/p95/p99), accuracy (> 95%), uncorrelated event handling |
| `test_graph_query_scale.py` | `get_all_dependencies`, `get_upstream`, `get_downstream`, `get_critical_path` latency with 100×100 runs |
| `conftest.py` | Shared mock data generators |

## Running

```bash
# From the backend directory
# All performance tests
.venv/Scripts/python.exe -m pytest tests/performance/ -v

# Individual suites
.venv/Scripts/python.exe -m pytest tests/performance/test_discovery_scale.py -v
.venv/Scripts/python.exe -m pytest tests/performance/test_event_correlation_scale.py -v
.venv/Scripts/python.exe -m pytest tests/performance/test_graph_query_scale.py -v
```

## Expected Metrics

| Metric | Threshold | Rationale |
|---|---|---|
| Discovery cycle (100 services) | < 10 s | Generous; with mocks it is typically < 1 s |
| Registry memory (100 services) | < 200 MB | Baseline; actual is typically < 10 MB |
| Dependency upserts (500) | < 5 s | SQLite local; PostgreSQL would be faster |
| Graph query (any) | < 100 ms | 100 nodes + 500 edges in Python memory |
| Graph JSON size | < 1 MB | 100 nodes + 500 edges ≈ 100–200 KB |
| Correlation avg latency | < 1 ms | In-memory cache lookup per event |
| Correlation p95 latency | < 5 ms | Accounts for occasional DB cache refresh |
| Correlation p99 latency | < 10 ms | Tail latency guardrail |
| Correlation accuracy | > 95% | Deterministic hostname matching |

## Latest Results

> **Run:** 2026-06-30  
> **Environment:** Windows 11, Python 3.14.3, SQLite in-memory  
> **Command:** `pytest tests/performance/ -v`

### Discovery Scale

- Discovery cycle (100 services): **< 1 s** ✅
- Registry memory (100 services): **< 10 MB** ✅
- Dependency upserts (500): **< 2 s** ✅
- Graph query avg: **< 5 ms** ✅
- Graph JSON size: **~150 KB** ✅

### Event Correlation

- Correlation avg latency: **< 0.5 ms** ✅
- Correlation p95 latency: **< 1 ms** ✅
- Correlation p99 latency: **< 2 ms** ✅
- Correlation accuracy: **> 99%** ✅
- Uncorrelated events: **100% correctly marked** ✅

### Graph Queries

- `get_all_dependencies` avg: **< 1 ms** ✅
- `get_upstream` avg: **< 1 ms** ✅
- `get_downstream` avg: **< 1 ms** ✅
- `get_critical_path` avg: **< 5 ms** ✅
- Rendering JSON size: **~150 KB** ✅

## Methodology

1. **Deterministic Data**: `random.seed(42)` ensures every test run uses the
   same services, dependencies, and events. This eliminates noise from data
   variation.
2. **Mock Providers**: Discovery providers return pre-built lists instantly
   (no real Docker/Kubernetes/process I/O), so measurements focus on engine
   overhead.
3. **Time Measurement**: `time.perf_counter()` is used for high-resolution
   latency measurement.
4. **Memory Measurement**: `tracemalloc` snapshots before/after registry
   population give precise heap delta.
5. **JSON Size**: The same `ServiceGraphResponse` serialization used by the
   `GET /graph/auto` endpoint is measured to ensure frontend payload bounds.

## CI Integration

Performance tests run on every push to `main` via
`.github/workflows/performance-tests.yml`. The job is marked
`continue-on-error: true` so a flaky threshold does not block releases.

## Future Work

- Add PostgreSQL-backed performance benchmarks (not just SQLite).
- Test with 1,000+ services and 10,000+ dependencies.
- Add concurrency tests: multiple discovery workers running simultaneously.
- Profile with `py-spy` or `cProfile` to identify hotspots as scale grows.
