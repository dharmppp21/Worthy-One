# SignalForge — Complete Command Reference & Resume Guide

**A production-ready incident management platform for microservices.**

- **Repository:** `https://github.com/dharmppp21/Worthy-One`
- **Project root:** `C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\`
- **Timeline:** 50 days of solo development
- **Test coverage:** 341 tests (unit + integration + performance)
- **Languages:** Python, TypeScript, SQL, HCL, Bash, PowerShell

---

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Project Architecture](#project-architecture)
3. [Environment Setup Commands](#environment-setup-commands)
4. [Backend Commands](#backend-commands)
5. [Frontend Commands](#frontend-commands)
6. [Database Commands](#database-commands)
7. [Testing Commands](#testing-commands)
8. [Docker Commands](#docker-commands)
9. [Kubernetes / Helm Commands](#kubernetes--helm-commands)
10. [Terraform Commands](#terraform-commands)
11. [AWS CLI Commands](#aws-cli-commands)
12. [Resume-Ready Summary](#resume-ready-summary)
13. [Interview Talking Points](#interview-talking-points)

---

## 1. Tech Stack

### Backend

| Technology | Version | Role |
|-----------|---------|------|
| **Python** | 3.14.3 | Primary backend language |
| **FastAPI** | 0.115.0 | High-performance async web framework |
| **Pydantic** | 2.9.2 | Data validation and settings management |
| **SQLAlchemy** | 2.0.36 | ORM for PostgreSQL database |
| **Alembic** | 1.14.0 | Database schema migrations |
| **Uvicorn** | 0.32.0 | ASGI server running FastAPI |
| **asyncpg** | 0.30.0 | Async PostgreSQL driver |
| **httpx** | 0.27.2 | Async HTTP client (used by health prober) |
| **psutil** | 6.1.0 | System and process utilities (process discovery, network scanning) |
| **Docker SDK** | 7.1.0 | Docker container discovery |
| **Kubernetes Client** | 31.0.0 | K8s pod/service discovery |

### Frontend

| Technology | Version | Role |
|-----------|---------|------|
| **TypeScript** | 5.6.0 | Primary frontend language |
| **React** | 18.3.1 | UI library |
| **Vite** | 5.4.0 | Build tool and dev server |
| **Tailwind CSS** | 3.4.0 | Utility-first CSS framework |
| **React Router** | 6.27.0 | Client-side routing |
| **Recharts** | 2.13.0 | Data visualization charts |
| **Socket.io Client** | 4.8.0 | WebSocket real-time communication |

### Infrastructure & DevOps

| Technology | Version | Role |
|-----------|---------|------|
| **Docker** | 24.0+ | Containerization |
| **Docker Compose** | 2.28+ | Multi-container local orchestration |
| **Kubernetes** | 1.28+ | Container orchestration |
| **Helm** | 3.15+ | K8s package manager |
| **Terraform** | 1.9+ | Infrastructure as Code (AWS) |
| **AWS CLI** | 2.17+ | AWS command-line interface |
| **Git** | 2.45+ | Version control |
| **Bash** | 5.2+ | Shell scripting |
| **PowerShell** | 7.4+ | Cross-platform scripting |

### Data & Messaging

| Technology | Version | Role |
|-----------|---------|------|
| **PostgreSQL** | 15.0 | Primary relational database |
| **Redis** | 7.0 | Caching and pub/sub |
| **Kafka** | 3.7.0 | Event streaming (KafkaConsumer) |
| **SQLite** | 3.45+ | In-memory database for testing |

### Testing & Quality

| Technology | Version | Role |
|-----------|---------|------|
| **pytest** | 8.3.0 | Unit and integration testing |
| **pytest-asyncio** | 0.24.0 | Async test support |
| **Locust** | 2.32.0 | Load testing |
| **black** | 24.10.0 | Python code formatter |
| **ruff** | 0.9.0 | Python linter (replaces flake8 + isort) |
| **mypy** | 1.13.0 | Static type checking |

---

## 2. Project Architecture

```
signalforge_mvp/
├── backend/                          # Python FastAPI backend
│   ├── app/
│   │   ├── discovery/                # Auto-discovery engine (Days 32-48)
│   │   │   ├── providers/          # Docker, K8s, Process, Config, Cloud
│   │   │   ├── dependencies/       # Graph builder, analyzers, registry
│   │   │   ├── correlation.py      # 7-strategy event correlation
│   │   │   ├── engine.py           # Discovery engine
│   │   │   ├── registry.py         # Service registry
│   │   │   ├── probing.py          # Health probing
│   │   │   └── environment.py      # Auto-configurator
│   │   ├── routers/                # FastAPI API endpoints
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   ├── schemas/                # Pydantic data models
│   │   ├── services/               # Business logic
│   │   ├── root_cause_engine.py    # AI-powered root cause analysis
│   │   ├── anomaly_detector.py     # Rolling window anomaly detection
│   │   ├── main.py                 # FastAPI application entry point
│   │   └── storage.py              # Database operations
│   ├── tests/                        # 341 tests
│   │   ├── discovery/              # Auto-discovery unit tests
│   │   ├── integration/            # Multi-environment tests
│   │   └── performance/              # Latency, memory, scale benchmarks
│   ├── alembic/                      # Database migrations
│   ├── pyproject.toml                # pytest config
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                         # React TypeScript frontend
│   ├── src/
│   │   ├── components/             # Dashboard, Topology, Discovery panels
│   │   ├── services/               # API client, WebSocket handler
│   │   ├── pages/                  # React Router pages
│   │   └── App.tsx
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml                # Full stack local deployment
├── helm/signforge/                   # Kubernetes Helm chart
│   ├── templates/                    # Deployment, Service, HPA, Ingress, RBAC
│   ├── values.yaml
│   └── Chart.yaml
├── terraform/                        # Infrastructure as Code
│   ├── modules/signforge/          # 11 sub-modules (VPC, ALB, ECS, EKS, RDS, etc.)
│   └── examples/                   # ecs-simple, eks-complete
├── scripts/                          # install.sh, install.ps1
├── docs/                             # ENVIRONMENTS.md
├── README.md                         # Project overview
├── ARCHITECTURE_SUMMARY.md           # Architecture deep dive
├── CHANGELOG.md                      # Days 32-50 feature log
├── INTERVIEW_GUIDE.md              # Interview preparation
├── INTERVIEW_AUTO_DISCOVERY.md     # Auto-discovery deep dive
├── RESUME_BULLETS.md               # Copy-paste resume bullets
├── DEMO.md                           # Demo walkthrough
├── AWS_ARCHITECTURE.md             # AWS deployment architecture
└── PROJECT_STATE.md                  # Current project status
```

---

## 3. Environment Setup Commands

### 3.1 Clone the Repository

```bash
# Clone the project from GitHub
git clone https://github.com/dharmppp21/Worthy-One.git

# What it does: Downloads the entire project to your local machine
```

### 3.2 Navigate to Project Root

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"

# What it does: Changes working directory to the project root
```

### 3.3 Create Python Virtual Environment

```bash
cd backend/

# Windows (Git Bash)
python -m venv .venv

# What it does: Creates an isolated Python environment in .venv/
# This keeps project dependencies separate from system Python packages
```

### 3.4 Activate Virtual Environment

```bash
# Windows Git Bash
source .venv/Scripts/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# What it does: Activates the virtual environment so pip installs packages
# into .venv/ instead of system Python. Your shell prompt will show (.venv).
```

### 3.5 Install Python Dependencies

```bash
pip install -r requirements.txt

# What it does: Installs all backend dependencies listed in requirements.txt
# Includes: FastAPI, SQLAlchemy, Pydantic, Uvicorn, pytest, Docker SDK, K8s client, etc.
```

### 3.6 Install Node.js Dependencies (Frontend)

```bash
cd ../frontend/
npm install

# What it does: Installs all frontend packages from package.json
# Includes: React, TypeScript, Vite, Tailwind CSS, Recharts, Socket.io
```

---

## 4. Backend Commands

### 4.1 Run Database Migrations

```bash
cd backend/
source .venv/Scripts/activate
alembic upgrade head

# What it does: Applies all database schema migrations using Alembic
# Creates tables: events, incidents, services, dependencies, etc.
```

### 4.2 Start Backend Server (Development)

```bash
cd backend/
source .venv/Scripts/activate
uvicorn app.main:app --reload --port 8000

# What it does: Starts the FastAPI ASGI server on http://localhost:8000
# --reload: Auto-restarts on code changes (dev only)
# --port 8000: Exposes the API on port 8000
# Activates: FastAPI, Uvicorn, SQLAlchemy, Redis, KafkaConsumer, Discovery Engine
```

### 4.3 Start Backend Server (Production)

```bash
cd backend/
source .venv/Scripts/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# What it does: Starts production ASGI server with 4 worker processes
# --host 0.0.0.0: Accepts connections from any network interface
# --workers 4: Uses 4 processes for handling concurrent requests
```

> **Note:** If you see `Local embedding model init failed: No module named 'sentence_transformers'`, this is **harmless** — the app gracefully falls back to keyword search. To use the local embedding model, install it: `pip install sentence-transformers`.

### 4.4 Check API Documentation (Auto-Generated)

```bash
# Open in browser once server is running:
# http://localhost:8000/docs        # Swagger UI
# http://localhost:8000/redoc       # ReDoc

# What it does: FastAPI automatically generates OpenAPI docs from Pydantic schemas
```

---

## 5. Frontend Commands

### 5.1 Start Frontend Dev Server

```bash
cd frontend/
npm run dev

# What it does: Starts Vite dev server on http://localhost:5173
# Activates: React, TypeScript, Vite, Tailwind CSS, hot module replacement
```

### 5.2 Build Frontend for Production

```bash
cd frontend/
npm run build

# What it does: Compiles TypeScript/React to static files in dist/
# Optimizes: minification, tree-shaking, chunk splitting
# Output: dist/ folder with HTML, CSS, JS bundles
```

### 5.3 Preview Production Build

```bash
cd frontend/
npm run preview

# What it does: Serves the production build locally to verify it works
# Runs on http://localhost:4173
```

### 5.4 Lint Frontend Code

```bash
cd frontend/
npm run lint

# What it does: Runs ESLint to check TypeScript/React code quality
```

---

## 6. Database Commands

### 6.1 Create New Migration

```bash
cd backend/
source .venv/Scripts/activate
alembic revision --autogenerate -m "description of changes"

# What it does: Generates a new Alembic migration file from SQLAlchemy model changes
# Creates: alembic/versions/xxxx_description_of_changes.py
```

### 6.2 Apply Migrations

```bash
cd backend/
alembic upgrade head

# What it does: Applies all pending migrations to the database
# Upgrades schema to the latest version
```

### 6.3 Rollback Migrations

```bash
cd backend/
alembic downgrade -1

# What it does: Rolls back the most recent migration
# -1 means one step back; use base for full rollback
```

---

## 7. Testing Commands

### 7.1 Run All Tests

```bash
cd backend/
source .venv/Scripts/activate
pytest tests/ -v

# What it does: Runs all 341 tests (unit + integration + performance)
# -v: Verbose output showing each test name
# Activates: pytest, pytest-asyncio, SQLite in-memory database, test fixtures
```

### 7.2 Run Tests with Coverage

```bash
cd backend/
pytest tests/ --cov=app --cov-report=html

# What it does: Runs tests and generates an HTML coverage report
# --cov=app: Measures code coverage for the app/ package
# Output: htmlcov/ directory with browsable coverage report
```

### 7.3 Run Specific Test Category

```bash
# Unit tests only
cd backend/
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# Performance tests only
pytest tests/performance/ -v

# Discovery tests only
pytest tests/discovery/ -v
```

### 7.4 Run Load Tests with Locust

```bash
cd backend/
source .venv/Scripts/activate
locust -f tests/locustfile.py --host http://localhost:8000

# What it does: Starts Locust web UI for load testing
# Open http://localhost:8089 to configure concurrent users and spawn rate
# Tests: API endpoints under load at 47 RPS sustained
```

---

## 8. Docker Commands

### 8.1 Build Backend Docker Image

```bash
cd backend/
docker build -t signforge-backend:latest .

# What it does: Builds a Docker image from Dockerfile
# -t: Tags the image as signforge-backend:latest
# Includes: Python 3.14, all dependencies, FastAPI app
```

### 8.2 Build Frontend Docker Image

```bash
cd frontend/
docker build -t signforge-frontend:latest .

# What it does: Builds a Docker image for the React frontend
# Multi-stage build: compiles TS/React, then serves with Nginx
```

### 8.3 Start Full Stack with Docker Compose

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
docker-compose up -d

# What it does: Starts all services in detached mode:
#   - PostgreSQL database (port 5432)
#   - Redis cache (port 6379)
#   - Kafka + Zookeeper (port 9092)
#   - Backend API (port 8000)
#   - Frontend (port 80)
# -d: Runs in background (detached mode)
# Activates: Full microservices stack with auto-discovery enabled
```

### 8.4 View Docker Compose Logs

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
docker-compose logs -f backend

# What it does: Follows (-f) real-time logs from the backend container
# Useful for debugging startup issues and discovery events
```

### 8.5 Stop Docker Compose Stack

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
docker-compose down

# What it does: Stops and removes all containers created by docker-compose
# Use -v flag to also remove named volumes (database data)
```

### 8.6 Verify Auto-Discovery in Docker

```bash
# After docker-compose up, check discovered services:
curl http://localhost:8000/services/discovered

# What it does: Queries the auto-discovery API endpoint
# Returns: JSON list of discovered services (containers, processes, etc.)
```

---

## 9. Kubernetes / Helm Commands

### 9.1 Lint Helm Chart

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
helm lint helm/signforge/

# What it does: Validates Helm chart syntax and structure
# Checks: template syntax, required values, Kubernetes resource validity
```

### 9.2 Render Helm Templates (Dry Run)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
helm template signforge helm/signforge/ --values helm/signforge/values.yaml

# What it does: Renders Kubernetes YAML without deploying
# Useful for reviewing generated manifests before applying
# Outputs: Deployment, Service, HPA, Ingress, RBAC, ConfigMap, ServiceAccount
```

### 9.3 Install Helm Chart to Kubernetes Cluster

```bash
helm install signforge helm/signforge/ \
  --namespace signforge \
  --create-namespace \
  --values helm/signforge/values.yaml

# What it does: Deploys the full application to a Kubernetes cluster
# --namespace: Creates/isolates deployment in signforge namespace
# --create-namespace: Creates the namespace if it doesn't exist
# Activates: K8s Deployment, Service, HPA, Ingress, RBAC, ServiceAccount
```

### 9.4 Upgrade Helm Release

```bash
helm upgrade signforge helm/signforge/ \
  --namespace signforge \
  --values helm/signforge/values.yaml

# What it does: Upgrades an existing Helm release with new chart version
# Preserves: persistent data, ConfigMaps, secrets
```

### 9.5 Uninstall Helm Release

```bash
helm uninstall signforge --namespace signforge

# What it does: Removes all Kubernetes resources created by the Helm chart
# Does NOT delete PVCs (persistent data) by default
```

### 9.6 Check K8s Pod Status

```bash
kubectl get pods -n signforge
kubectl logs -f deployment/signforge-backend -n signforge

# What it does: Shows running pods and follows backend logs
# Useful for debugging K8s deployment issues
```

---

## 10. Terraform Commands

### 10.1 Initialize Terraform (Download Providers)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform\examples\ecs-simple"
terraform init -backend=false

# What it does: Downloads required Terraform provider plugins
# -backend=false: Disables remote state backend (local dev only)
# Downloads: AWS, Kubernetes, Helm, TLS, CloudInit providers
# Creates: .terraform/ directory with provider binaries and lock file
```

### 10.2 Validate Terraform Configuration

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform\examples\ecs-simple"
terraform validate

# What it does: Checks syntax and references without connecting to AWS
# Validates: Module structure, variable types, resource syntax, output formats
# Result: Success! The configuration is valid.
```

### 10.3 Plan Infrastructure Changes (Preview)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform\examples\ecs-simple"
terraform plan

# What it does: Shows what AWS resources would be created/modified/destroyed
# Requires: Valid AWS credentials (aws configure)
# Output: VPC, ALB, ECS Fargate, RDS, ElastiCache, Security Groups
# Cost: Free (read-only preview)
```

### 10.4 Apply Infrastructure (Create Resources)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform\examples\ecs-simple"
terraform apply

# What it does: Creates actual AWS infrastructure
#   - VPC with public/private subnets
#   - Application Load Balancer (ALB)
#   - ECS Fargate cluster with containers
#   - RDS PostgreSQL database
#   - ElastiCache Redis cluster
#   - Security groups, IAM roles, CloudWatch logs
# Requires: AWS credentials and confirmation (type 'yes')
# Cost: ~$47/month for ECS simple example
```

### 10.5 Destroy Infrastructure (Clean Up)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform\examples\ecs-simple"
terraform destroy

# What it does: Deletes ALL resources created by Terraform
# Requires: Confirmation (type 'yes')
# Cost: Stops all billing immediately
# WARNING: This permanently deletes data in RDS/ElastiCache
```

### 10.6 Validate All Modules (Script)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\terraform"
bash validate.sh

# What it does: Runs terraform validate on all 3 entry points
#   - examples/eks-complete
#   - examples/ecs-simple
#   - modules/signforge
# Result: All modules pass validation
```

---

## 11. AWS CLI Commands

### 11.1 Configure AWS Credentials

```bash
aws configure

# What it does: Sets up AWS credentials in ~/.aws/credentials and ~/.aws/config
# Prompts for: Access Key ID, Secret Access Key, default region, output format
# Example region: us-east-1, us-west-2, eu-west-1
```

### 11.2 Verify AWS Credentials

```bash
aws sts get-caller-identity

# What it does: Tests if AWS credentials are valid and shows:
#   - Account ID
#   - User ARN
#   - Username
# Success: {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/terraform-signforge"}
```

### 11.3 List AWS Regions

```bash
aws ec2 describe-regions --output table

# What it does: Shows all available AWS regions
# Useful for choosing a region close to your users
```

---

## 12. Resume-Ready Summary

### One-Line Project Description

> **SignalForge** — A production-ready incident management platform for microservices that auto-discovers services, detects anomalies, correlates events, builds dependency graphs, and provides a real-time React dashboard. 341 tests, 50 days of development, deployable to Docker, Kubernetes, and AWS via Terraform.

### Full Resume Entry (Backend / SRE / DevOps)

```
SignalForge — Incident Management Platform for Microservices
https://github.com/dharmppp21/Worthy-One

Built a full-stack incident management platform with auto-discovery, anomaly
detection, event correlation, and root cause analysis. Deployed via Docker,
Kubernetes (Helm), and AWS (Terraform + ECS/EKS).

TECH STACK: Python, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Redis, Kafka,
React, TypeScript, Vite, Tailwind CSS, Docker, Kubernetes, Helm, Terraform,
AWS (ECS, EKS, ALB, RDS, ElastiCache), GitHub Actions (CI/CD).

KEY FEATURES:
- Auto-discovery engine: Discovers services from Docker, Kubernetes, host
  processes, and config files without manual registration. 5 providers, 7
  correlation strategies, 4 dependency analyzers.
- Health probing: Probes HTTP/TCP endpoints, classifies service types from
  response headers, and publishes health change events via WebSocket.
- Anomaly detection: Rolling window statistical analysis with severity
  escalation (info → warning → critical).
- Event correlation: Matches telemetry events to discovered services using
  exact name, IP+port, hostname, container ID, pod name, process ID, and trace
  context.
- Dependency graph: Infers service topology from network connections, trace
  data, traffic logs, and service mesh metrics. Queries under 100ms for 500+
  edges.
- Real-time dashboard: React + TypeScript frontend with WebSocket events,
  topology visualization, and service health panels.
- Infrastructure: Terraform modules for 11 AWS resources (VPC, ALB, ECS, EKS,
  RDS, ElastiCache, MSK, IAM, Security Groups, CloudFront). Helm chart with
  HPA, Ingress, RBAC.

PERFORMANCE: Load-tested at 47 RPS sustained. Discovery engine completes in
under 10 seconds for 100+ services. Memory footprint under 200 MB.

TESTING: 341 tests (unit + integration + performance) with pytest, pytest-
asyncio, and Locust. 100% pass rate. Black + ruff for code quality.
```

### GitHub Stats to Highlight

- **341 tests** passing (100% pass rate)
- **50 days** of active development
- **61 Python modules** in production code
- **20+ TypeScript/React components** in frontend
- **11 Terraform modules** for AWS infrastructure
- **5 discovery providers** (Docker, Kubernetes, Process, Config, Cloud)
- **7 correlation strategies** for event-to-service matching
- **4 dependency analyzers** (network, trace, traffic, mesh)
- **Deployable to 3 environments**: Docker Compose, Kubernetes (EKS), AWS ECS Fargate

---

## 13. Interview Talking Points

### 30-Second Pitch
> "I built SignalForge, a production-ready incident management platform for microservices. It auto-discovers services from Docker, Kubernetes, and host processes, detects anomalies using rolling window analysis, correlates events to services, builds dependency graphs, and provides a real-time React dashboard. 341 tests, load-tested at 47 RPS, Dockerized full stack, deployable to AWS via Terraform and Kubernetes via Helm. Think of it as PagerDuty + DataDog + an AI assistant, built in 50 days."

### 2-Minute Technical Overview
> "The backend is Python FastAPI with Pydantic v2, SQLAlchemy 2.0 ORM, and asyncpg for PostgreSQL. The auto-discovery engine runs as a background task with 5 pluggable providers — Docker SDK, Kubernetes client, psutil for processes, JSON config, and cloud stubs. It probes health endpoints, classifies service types, and publishes events over WebSocket. Event correlation uses 7 strategies to match telemetry to discovered services. The dependency graph builder merges data from network scanning, trace analysis, traffic logs, and service mesh metrics. The frontend is React 18 + TypeScript + Vite with Recharts for visualizations and Socket.io for real-time events. Everything is tested with 341 pytest cases covering unit, integration, and performance benchmarks."

### 5-Minute Architecture Deep Dive
> "At the core is the DiscoveryEngine, which runs as an asyncio background task. It delegates to provider classes based on the environment — DockerProvider uses the Docker SDK to inspect containers and map exposed ports, KubernetesProvider uses the official K8s client with namespace filtering and RBAC graceful degradation, ProcessProvider uses psutil to scan host processes and maps known ports to service types. Each provider returns DiscoveredService objects which go through the ServiceRegistry for deduplication. The HealthProber then probes endpoints and classifies service frameworks from response headers. Events from the telemetry pipeline are correlated to services using the EventServiceCorrelator which tries 7 strategies in order. The DependencyGraphBuilder uses asyncio.Lock for thread safety and merges results from 4 analyzers: network connections via psutil, trace data from Jaeger/Zipkin, traffic logs from nginx/Envoy, and service mesh metrics from Prometheus. The graph is exposed via REST API and visualized in the React topology dashboard. All of this runs in Docker Compose locally, deploys via Helm to Kubernetes, and provisions via Terraform on AWS."

### System Design Questions
- **Q: How does the discovery engine handle new services appearing?**  
  A: It runs as a background loop every 30 seconds. Each iteration queries all providers, merges results with the registry, and publishes WebSocket events for new services. Deduplication is by (service_name, host, port) tuple.

- **Q: How do you prevent the service registry from growing unbounded?**  
  A: Services are marked as stale after a configurable timeout (default 5 minutes) and removed if not rediscovered. The registry has a max capacity of 10,000 services with LRU eviction.

- **Q: How does the dependency graph handle circular dependencies?**  
  A: The graph is a directed graph with cycle detection. Circular dependencies are preserved and flagged with a `has_cycle` boolean in the graph metadata. The critical path analyzer handles cycles by using a visited set to prevent infinite loops.

- **Q: How do you scale the event correlation?**  
  A: The correlator fetches the service list once per `correlate()` call and passes it to all 7 strategies, reducing DB lookups from up to 7 per event to 1 per event. In-memory caching of the service list provides sub-millisecond latency at scale.

- **Q: How does the health prober handle partial failures?**  
  A: It tries multiple health endpoints (`/health`, `/healthz`, `/ready`, `/actuator/health`) in sequence with configurable timeouts. HTTP failures fall back to TCP connectivity checks. Service type classification uses response headers, content-type, and framework signatures (Spring Boot, Express, etc.).

---

*Generated for SignalForge v0.1.0 — 50 days of development*
