# Worthy One — Global Developer Guide

> **Read this file every time before you start working.**

---

## 1. Always Read This First

Before writing any code, editing any file, or running any command, **read this file from top to bottom**. It contains the workflow rules that keep the project clean, tested, and properly versioned.

---

## 2. Project Structure Overview

```
Worthy One/
├── firstreadme.md              ← You are here. Read this first.
├── signalforge_mvp/            ← Main application (backend + frontend)
│   ├── backend/
│   │   ├── app/                ← FastAPI application
│   │   │   ├── discovery/      ← Service discovery system
│   │   │   │   ├── providers/  ← Process, Docker, K8s, Cloud, Config
│   │   │   │   ├── dependencies/ ← Network scanner, dependency graph
│   │   │   │   ├── correlation.py ← Event-to-service correlation engine
│   │   │   │   ├── models.py
│   │   │   │   ├── registry.py
│   │   │   │   ├── engine.py
│   │   │   │   ├── environment.py
│   │   │   │   └── base.py
│   │   │   ├── routers/        ← API endpoints
│   │   │   ├── models.py       ← SQLAlchemy ORM models
│   │   │   ├── database.py     ← DB connection
│   │   │   ├── main.py         ← FastAPI app factory
│   │   │   └── ...
│   │   ├── tests/              ← pytest test suite
│   │   │   └── discovery/      ← Discovery tests
│   │   ├── alembic/            ← Database migrations
│   │   ├── requirements.txt    ← Python dependencies
│   │   └── pyproject.toml      ← pytest config
│   ├── helm/                   ← Kubernetes Helm chart
│   │   └── signforge/          ← SignalForge Helm chart
│   │       ├── Chart.yaml
│   │       ├── values.yaml
│   │       ├── templates/      ← K8s manifest templates
│   │       └── README.md
│   ├── frontend/               ← React/Vite frontend
│   ├── simulator/              ← Traffic simulator
│   ├── samples/                ← Event JSON samples
│   ├── docker-compose.yml      ← Local infra stack
│   └── README.md
├── Days/                       ← Daily build reports (SignalForge days)
└── Prompt.txt                  ← Current active prompt
```

**Working directory:** All operations happen inside `Worthy One/signalforge_mvp/backend/`.

---

## 3. Commit Rule: Section-Wise, Not Day-Wise

### ❌ Wrong: Day-wise commits
```
feat: day 32 work — process and docker providers
feat: day 33 work — kubernetes and cloud providers
```

### ✅ Correct: Section/feature-wise commits
Each commit must represent a **complete, testable feature or module**. The commit message should describe **what** was built, not **when**.

```
feat: add service discovery backend with DiscoveryEngine, ServiceRegistry, and providers
feat: add process and Docker discovery providers with tests
feat: add K8s, cloud, config providers + environment auto-detection + discovery API
feat: add network-based dependency detection system with graph analysis
```

---

## 3.5 Committing Like a Human

Write commit messages that **a real human would understand** when reading `git log` six months from now. The person reading it might be you, a teammate, or a new hire. Make their life easy.

### Write the subject line as a sentence — but drop the period

Use the imperative mood ("Add", "Fix", "Update", "Remove") and describe the change in plain English.

| ❌ Robotic / vague | ✅ Human-readable |
|---|---|
| `feat: implement scanner` | `feat: scan network connections to detect service dependencies` |
| `feat: add models` | `feat: add ServiceDependency and DependencyGraph Pydantic models` |
| `fix: bug` | `fix: skip LISTEN connections in NetworkConnectionScanner to avoid self-loops` |
| `chore: update` | `chore: add kubernetes, boto3, and pyyaml to requirements.txt` |
| `test: tests` | `test: add 21 tests for network scanner, dependency registry, and graph BFS` |

### The subject line is a headline, not a label

| ❌ Label-style | ✅ Headline-style |
|---|---|
| `feat: discovery` | `feat: add environment auto-detection for Docker, K8s, AWS, and Azure` |
| `feat: registry` | `feat: add DependencyRegistry with upsert, filtering, and stale removal` |
| `feat: provider` | `feat: add ConfigDiscoveryProvider for JSON/YAML service definitions` |

### Use the body when the "why" matters

If the change is non-obvious, add a blank line and explain the reasoning. This is free documentation embedded in the git history.

```
feat: add inferred placeholder services for unknown network endpoints

When a process connects to an IP:port that is not in the ServiceRegistry,
we now create an inferred DiscoveredService with a low confidence score (0.3).
This prevents us from silently dropping dependencies on external databases,
caches, or message queues that were not picked up by other discovery providers.
```

### Conventional Commit types we use

| Type | Use when | Example |
|---|---|---|
| `feat:` | New feature or capability | `feat: add KubernetesDiscoveryProvider for in-cluster pod scanning` |
| `fix:` | Bug fix | `fix: handle PermissionError in psutil.net_connections()` |
| `test:` | New or updated tests | `test: add 13 tests for ProcessDiscoveryProvider` |
| `docs:` | Documentation only | `docs: add firstreadme.md developer guide` |
| `chore:` | Maintenance, deps, config | `chore: bump pytest-asyncio to 0.23` |
| `refactor:` | Code restructuring | `refactor: extract _infer_dependency_type to shared helper` |

### Commit Checklist (MANDATORY before every push)

1. **Run tests** — see Section 4 below.
2. **Clean pycache** — remove `__pycache__` and `.pytest_cache` directories.
3. **Stage changes** — `git add -A`
4. **Write a human-readable commit message** — describe what and why, not when.
5. **Push** — `git push origin main`

---

## 4. Testing Rule: Test Every Time You Work

### Before every commit, run the full discovery test suite:

```bash
cd signalforge_mvp/backend
.venv/Scripts/python.exe -m pytest tests/discovery/ -v
```

### Before every commit, verify no regressions in existing tests:

```bash
cd signalforge_mvp/backend
.venv/Scripts/python.exe -m pytest tests/test_anomaly.py tests/test_auth.py tests/test_incidents.py -v
```

### Test Rules

| Rule | Enforcement |
|------|-------------|
| All new code must have tests | No exceptions |
| All tests must pass before commit | No exceptions |
| No regressions in existing tests | No exceptions |
| Mock external dependencies (Docker, K8s, AWS, psutil) | No real external services in tests |
| Use pytest-asyncio for async tests | Configured in `pyproject.toml` |
| Use SQLite in-memory for DB tests | No PostgreSQL required for tests |

### If tests fail

1. Fix the failing tests before committing.
2. Do not commit "work in progress" with failing tests.
3. If a test is flaky, stabilize it before committing.

---

## 5. Workflow Steps (Every Session)

### Step 1: Read this file
```bash
cat firstreadme.md
```

### Step 2: Check current git status
```bash
cd signalforge_mvp
git status
```

### Step 3: Run existing tests (baseline)
```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/discovery/ -v
.venv/Scripts/python.exe -m pytest tests/test_anomaly.py tests/test_auth.py tests/test_incidents.py -v
```

### Step 4: Do your work
- Edit/create files in the appropriate module.
- Follow the existing code style (PEP 8, type hints, docstrings).
- Write tests for every new feature.

### Step 5: Run tests again (verify)
```bash
.venv/Scripts/python.exe -m pytest tests/discovery/ -v
.venv/Scripts/python.exe -m pytest tests/test_anomaly.py tests/test_auth.py tests/test_incidents.py -v
```

### Step 6: Clean pycache
```bash
rm -rf app/__pycache__ app/discovery/__pycache__ app/discovery/providers/__pycache__ app/discovery/dependencies/__pycache__ tests/__pycache__ tests/discovery/__pycache__ tests/discovery/dependencies/__pycache__ .pytest_cache
```

### Step 7: Commit and push
```bash
git add -A
git commit -m "feat: <describe what you built — section/feature, not day>"
git push origin main
```

---

## 6. Code Style Rules

- **Imports**: `from __future__ import annotations` at the top of every file.
- **Docstrings**: Every module, class, and public method must have a docstring.
- **Type hints**: Use type hints for function signatures and class attributes.
- **Logging**: Use `logging.getLogger(__name__)` — never `print()`.
- **Error handling**: Use try/except with specific exception types. Log errors, don't swallow them.
- **Database**: Use SQLAlchemy 2.0+ style. Use `Base` from `app.database`.
- **Pydantic**: Use Pydantic v2 models for data validation. Use `ConfigDict(populate_by_name=True)`.
- **Async**: Use `async def` for I/O-bound operations. Use `asyncio.gather` for concurrent work.

---

## 7. Module-Specific Guidelines

### Discovery Providers (`app/discovery/providers/`)
- Each provider must inherit from `ServiceDiscoveryProvider`.
- Must implement `health_check()` and `discover()`.
- Handle `ImportError` for optional dependencies (psutil, docker, kubernetes, boto3).
- Handle provider-specific exceptions gracefully (return empty list, log warning).

### Dependency Detection (`app/discovery/dependencies/`)
- Use `NetworkConnectionScanner` to scan `psutil.net_connections()`.
- Map connections to services via `ServiceRegistry`.
- Infer unknown services with `confidence_score = 0.3`.
- Store results in `DependencyRegistry` with upsert logic.

### Correlation Engine (`app/discovery/correlation.py`)
- `EventServiceCorrelator` auto-matches telemetry events to discovered services.
- Strategies are tried in priority order: exact_name, source_ip_port, hostname, container_id, pod_name, process_id, trace_context, fallback.
- Disambiguation picks the most recent heartbeat when multiple candidates match.
- Correlation metadata (strategy, confidence, matched_field) is persisted with the event.
- Events that cannot be correlated are flagged as `uncorrelated` and can be queried via `GET /events/uncorrelated`.

### Helm Chart (`helm/signforge/`)
- Chart depends on Bitnami's PostgreSQL, Redis, and Kafka subcharts (all optional).
- Each dependency is conditionally enabled via `postgresql.enabled`, `redis.enabled`, `kafka.enabled`.
- `rbac.yaml` creates either a ClusterRole (cross-namespace discovery) or Role (single-namespace) based on `discovery.kubernetes.clusterRole`.
- `deployment.yaml` includes an init container for `alembic upgrade head` database migrations.
- Template helpers in `_helpers.tpl` construct `DATABASE_URL`, `REDIS_URL`, and `KAFKA_BROKERS` from subchart service names.
- `values.yaml` provides production-ready defaults with configurable discovery providers, resources, and scheduling.

### Tests (`tests/`)
- Use `pytest.mark.asyncio` for async tests.
- Mock external APIs and system calls (psutil, docker, kubernetes, boto3, requests).
- Use fixtures for DB sessions (SQLite in-memory).
- Test both happy paths and error cases.

---

## 8. Reminders

- **Read this file first** — every single session.
- **Section-wise commits** — never day-wise.
- **Test everything** — every single time.
- **No pushing broken code** — all tests must pass.
- **Clean pycache** — before every commit.
- **Log, don't print** — use the logging module.
- **Be explicit** — type hints, docstrings, clear variable names.

---

## 9. Quick Reference Commands

```bash
# Run all discovery tests
.venv/Scripts/python.exe -m pytest tests/discovery/ -v

# Run specific test file
.venv/Scripts/python.exe -m pytest tests/discovery/dependencies/test_network_scanner.py -v

# Run existing app tests (no regressions)
.venv/Scripts/python.exe -m pytest tests/test_anomaly.py tests/test_auth.py tests/test_incidents.py -v

# Check git status
git status

# Clean and commit
rm -rf app/__pycache__ tests/__pycache__ .pytest_cache
git add -A
git commit -m "feat: <your feature description>"
git push origin main

# Check git log
git log --oneline -5
```

---

**Last updated:** 2026-06-30 — Added correlation engine and Helm chart documentation.
