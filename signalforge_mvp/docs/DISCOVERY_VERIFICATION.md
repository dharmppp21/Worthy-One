# SignalForge Discovery Verification Guide

How to verify that **real auto-discovery** is working — not hardcoded data.

---

## Prerequisites (Must Read)

Before running any `curl` command below, **the backend server must be running**.

### Step 1: Start the Backend (Terminal 1 — keep it open)

```powershell
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\backend"
.venv\Scripts\Activate.ps1
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**What this does:**
- Starts the FastAPI backend on `http://localhost:8000`
- Runs the discovery engine in the background (checks every 30 seconds)
- Creates the SQLite database if it doesn't exist

**Wait 30 seconds** after startup for the first discovery run to complete.

### Step 2: Run the `curl` commands (Terminal 2 — or PowerShell/Git Bash)

All `curl` commands in this guide run in a **separate terminal** (or in PowerShell/Git Bash) while the backend is running in Terminal 1.

**On Windows, use one of these:**

```powershell
# PowerShell (recommended — built into Windows)
curl http://localhost:8000/services/discovered

# Or with full path to Git Bash curl
"C:\Program Files\Git\mingw64\bin\curl.exe" http://localhost:8000/services/discovered

# Or with Invoke-RestMethod (PowerShell native)
Invoke-RestMethod -Uri http://localhost:8000/services/discovered
```

> **Note:** If you see `curl: (7) Failed to connect to localhost port 8000`, the backend is not running. Go back to Terminal 1 and check for errors.

---

## Table of Contents

1. [What is "Real" Discovery?](#what-is-real-discovery)
2. [Quick Checks](#quick-checks)
3. [Trigger On-Demand Discovery](#trigger-on-demand-discovery)
4. [Inspect Backend Logs](#inspect-backend-logs)
5. [Verify Each Provider](#verify-each-provider)
6. [The "Fresh Database" Test](#the-fresh-database-test)
7. [Common Issues & Fixes](#common-issues--fixes)

---

## 1. What is "Real" Discovery?

SignalForge discovers services from **your actual environment**, not from a config file. The `discovery_source` field tells you where each service came from:

| `discovery_source` | Meaning | Real? |
|---|---|---|
| `"docker"` | Found via Docker SDK inspecting running containers | ✅ **Real** |
| `"kubernetes"` | Found via K8s API (pods, services) | ✅ **Real** |
| `"process"` | Found via `psutil` scanning host processes | ✅ **Real** |
| `"cloud"` | Found from AWS/GCP/Azure metadata | ✅ **Real** |
| `"config"` | Loaded from JSON/YAML config file (`SIGNALFORGE_SERVICES`) | ⚠️ Could be hardcoded |
| `"mock"` or missing | No provider found it | ❌ **Not real** |

> **Rule:** If `discovery_source` is `"docker"`, `"process"`, or `"kubernetes"`, it's real discovery. If it's `"config"`, check whether the config file is hardcoded or generated.

---

## 2. Quick Checks

> **Prerequisite:** Backend must be running. See [Prerequisites](#prerequisites-must-read) above.

### 2.1 Check Discovered Services

```bash
curl http://localhost:8000/services/discovered
```

**Look for:**
- `discovery_source` field in each service
- `first_seen_at` and `last_seen_at` timestamps (should be recent, not old)
- Service names matching your actual running services (e.g., `python`, `node`, `postgres`, `redis`)

**Example — real Docker discovery:**
```json
{
  "service_id": "svc-abc123",
  "service_name": "signforge-postgres",
  "discovery_source": "docker",
  "endpoints": ["tcp://172.18.0.2:5432"],
  "host": "172.18.0.2",
  "first_seen_at": "2025-01-15T10:30:00Z"
}
```

**Example — fake/hardcoded:**
```json
{
  "service_id": "svc-1",
  "service_name": "mock-service",
  "discovery_source": "config",
  "endpoints": ["http://localhost:9999"],
  "host": "localhost",
  "first_seen_at": "2020-01-01T00:00:00Z"
}
```

### 2.2 Check Service Count

```bash
curl http://localhost:8000/services/discovered | findstr service_id
```

- **0 services** = No provider found anything (check logs)
- **1-2 services** = Likely only ConfigProvider running (check `discovery_source`)
- **5+ services** = Real discovery likely working (Docker + Process providers)

### 2.3 Check Health Status

```bash
curl http://localhost:8000/services/health
```

Real services have health checks (`/health`, `/healthz`, `/ready`). If health is `"unknown"` for all, the prober isn't running or services don't respond.

---

## 3. Trigger On-Demand Discovery

> **Prerequisite:** Backend must be running. See [Prerequisites](#prerequisites-must-read) above.

The background discovery runs every 30 seconds. You can also trigger it manually:

```bash
curl -X POST http://localhost:8000/services/discover
```

**What it does:**
- Runs **all** providers immediately (Docker, K8s, Process, Config, Cloud)
- Returns the discovered services as JSON
- Stores results in the database
- Publishes WebSocket events

**Response — real discovery:**
```json
[
  {
    "service_id": "svc-abc123",
    "service_name": "python",
    "discovery_source": "process",
    "host": "127.0.0.1",
    "endpoints": ["tcp://127.0.0.1:8000"],
    "service_type": "api"
  },
  {
    "service_id": "svc-def456",
    "service_name": "node",
    "discovery_source": "process",
    "host": "127.0.0.1",
    "endpoints": ["tcp://127.0.0.1:5173"],
    "service_type": "web"
  }
]
```

**Response — no real services found:**
```json
[]
```

If empty, check the [backend logs](#4-inspect-backend-logs) for provider errors.

---

## 4. Inspect Backend Logs

In **Terminal 1** (where the backend runs), watch for these log lines:

### Docker Provider (requires Docker Desktop running)

```
INFO  app.discovery.providers.docker: Discovered 3 containers
INFO  app.discovery.providers.docker: Container signforge-postgres → tcp://172.18.0.2:5432
INFO  app.discovery.engine: Docker provider returned 3 services
```

If you see **no Docker log lines**, either:
- Docker Desktop is not running
- The Docker socket is not accessible (Linux: `/var/run/docker.sock`, Windows: named pipe)
- The Docker SDK import failed (check `docker` package installed)

### Process Provider (works on all platforms)

```
INFO  app.discovery.providers.process: Found process python.exe on port 8000 → service_type: api
INFO  app.discovery.providers.process: Found process node.exe on port 5173 → service_type: web
INFO  app.discovery.providers.process: Found process postgres.exe on port 5432 → service_type: database
INFO  app.discovery.providers.process: Found process redis-server.exe on port 6379 → service_type: cache
INFO  app.discovery.engine: Process provider returned 4 services
```

If you see **no Process log lines**, either:
- `psutil` is not installed (`pip install psutil`)
- All processes were filtered by the blocklist (system processes skipped by design)

### Kubernetes Provider (only in K8s cluster)

```
INFO  app.discovery.providers.kubernetes: Discovered 5 pods in namespace default
INFO  app.discovery.engine: Kubernetes provider returned 5 services
```

If you see **no K8s log lines**, you're not running inside a Kubernetes pod (expected for local dev).

### Config Provider (always runs last)

```
INFO  app.discovery.providers.config: No SIGNALFORGE_SERVICES env var set; skipping config provider
INFO  app.discovery.engine: Config provider returned 0 services
```

If the ConfigProvider returns services, check `SIGNALFORGE_SERVICES` env var:
```powershell
$env:SIGNALFORGE_SERVICES
```
If it's set, those services come from a config file, not real discovery.

---

## 5. Verify Each Provider

### 5.1 Docker Provider

**Prerequisites:** Docker Desktop running.

```powershell
# Check if Docker is running
docker ps

# Should show containers like:
# CONTAINER ID   IMAGE              PORTS
# abc123         postgres:15        0.0.0.0:5432->5432/tcp
# def456         redis:7            0.0.0.0:6379->6379/tcp
```

**Verify in SignalForge:**
```bash
curl http://localhost:8000/services/discovered | findstr docker
```

**If not found:**
- Windows: Docker Desktop must be running with WSL2 backend
- Linux: The user needs access to `/var/run/docker.sock` (add to `docker` group)
- The `docker` Python package must be installed: `pip install docker`

### 5.2 Process Provider

**Works on all platforms** — no prerequisites.

```powershell
# Check what processes are running on known ports
# PowerShell:
Get-NetTCPConnection -LocalPort 8000, 5173, 5432, 6379 | Select-Object LocalPort, OwningProcess

# Or use netstat:
netstat -ano | findstr "8000 5173 5432 6379"
```

**Verify in SignalForge:**
```bash
curl http://localhost:8000/services/discovered | findstr process
```

**If not found:**
- `psutil` must be installed: `pip install psutil`
- Windows system processes are filtered (by design — `svchost`, `explorer`, etc. are skipped)
- The process must have an open TCP port to be detected

### 5.3 Kubernetes Provider

**Only works inside a K8s cluster.**

```bash
# Check if K8s env vars are present
curl http://localhost:8000/services/discovered | findstr kubernetes
```

**If not found:** Expected for local dev. Only works when deployed via Helm chart.

### 5.4 Config Provider

**Checks if hardcoded services exist.**

```powershell
# Check if config env var is set
$env:SIGNALFORGE_SERVICES
$env:SIGNALFORGE_SERVICES_CONFIG
```

If either is set, the provider reads from that source. If you want **only real discovery**, unset these:
```powershell
Remove-Item Env:SIGNALFORGE_SERVICES
Remove-Item Env:SIGNALFORGE_SERVICES_CONFIG
```

---

## 6. The "Fresh Database" Test

This is the definitive test: start with an empty database and see what discovery finds on its own.

```powershell
# Terminal 1: Backend
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\backend"
.venv\Scripts\Activate.ps1

# Delete the database (fresh start)
Remove-Item -Force signforge.db

# Recreate tables
.venv\Scripts\alembic.exe upgrade head

# Start backend
.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Wait **30 seconds** for the first background discovery run, then:

```bash
# Terminal 2: Check what was found
curl http://localhost:8000/services/discovered
```

**Expected results:**

| Your Setup | Expected Discovery Source | Expected Services |
|---|---|---|
| Docker Desktop running + backend/frontend running | `docker` + `process` | postgres, redis, python, node |
| Docker Desktop running only | `docker` | postgres, redis |
| No Docker, backend/frontend running | `process` | python, node |
| Nothing running | none | empty list |

If you see services with `discovery_source: "config"` after a fresh start, those are **hardcoded** — check `SIGNALFORGE_SERVICES` env var.

---

## 7. Common Issues & Fixes

| Issue | Cause | Fix |
|---|---|---|
| **0 services found** | Docker not running + psutil not installed | Start Docker Desktop; `pip install psutil` |
| **Only config services** | `SIGNALFORGE_SERVICES` env var set | `Remove-Item Env:SIGNALFORGE_SERVICES` |
| **Docker not found** | Docker Desktop not running or socket inaccessible | Start Docker Desktop; on Linux: `sudo usermod -aG docker $USER` |
| **Process provider empty** | All processes filtered (system processes) | Expected — only user processes with open ports are detected |
| **K8s not found** | Not running in a K8s pod | Expected for local dev — only works inside cluster |
| **Old timestamps** | Database was not deleted | Run `Remove-Item -Force signforge.db` and restart |
| **Health all "unknown"** | Health prober hasn't run yet or no endpoints respond | Wait 30 seconds; check `/health` endpoints exist on services |

---

## Quick Reference Commands

> **Prerequisite:** Backend must be running on `http://localhost:8000`.
> Run these in **PowerShell** or **Git Bash** while the backend is running.

```bash
# Check discovered services (with source)
curl http://localhost:8000/services/discovered | python -m json.tool

# Trigger discovery manually
curl -X POST http://localhost:8000/services/discover

# Check only Docker-discovered services (PowerShell)
curl http://localhost:8000/services/discovered | findstr "docker"

# Check only process-discovered services (PowerShell)
curl http://localhost:8000/services/discovered | findstr "process"

# Check health of all services
curl http://localhost:8000/services/health

# Check dependency graph
curl http://localhost:8000/dependencies/graph

# Check backend health
curl http://localhost:8000/health
```

**PowerShell alternatives (no curl installed):**

```powershell
# Using Invoke-RestMethod (built into PowerShell)
Invoke-RestMethod -Uri http://localhost:8000/services/discovered | ConvertTo-Json -Depth 3

# Trigger discovery
Invoke-RestMethod -Uri http://localhost:8000/services/discover -Method POST

# Check health
Invoke-RestMethod -Uri http://localhost:8000/health
```

---

## Summary

| Question | How to Verify |
|---|---|
| Is discovery running? | `curl http://localhost:8000/services/discovered` → should return services |
| Is it real or fake? | Check `discovery_source` field → `"docker"`/`"process"` = real, `"config"` = maybe hardcoded |
| Which providers found services? | Check backend logs or `discovery_source` in each service |
| Why are there 0 services? | Check if Docker Desktop is running; check `pip install psutil` |
| Why are they all "config"? | Check `$env:SIGNALFORGE_SERVICES` — unset if you want real discovery |

*SignalForge v0.1.0 — Auto-discovery engine: Docker, Kubernetes, Process, Config, Cloud*
