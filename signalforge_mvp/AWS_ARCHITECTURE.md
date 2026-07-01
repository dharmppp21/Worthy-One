# SignalForge — AWS Architecture Notes

A production deployment guide for SignalForge on AWS. This is designed as an
interview reference: you can explain the architecture, justify each decision,
and point to the actual code that supports it.

---

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│  CloudFront │────▶│  ALB (HTTPS)│────▶│  ECS Fargate    │
│  (CDN + SSL)│     │  (Path rules) │     │  Frontend (Nginx)│
└─────────────┘     └─────────────┘     └─────────────────┘
                                                │
                                                │ /api/*
                                                ▼
                                       ┌─────────────────┐
                                       │  ECS Fargate    │
                                       │  Backend (FastAPI)│
                                       │  (3+ tasks)       │
                                       └─────────────────┘
                                                │
                    ┌───────────────────────────┼───────────┐
                    ▼                           ▼           ▼
            ┌─────────────┐            ┌─────────────┐  ┌─────────────┐
            │ RDS         │            │ ElastiCache │  │ MSK /       │
            │ PostgreSQL  │            │ Redis       │  │ Kafka       │
            │ (Multi-AZ)  │            │ (Cluster)   │  │ (Managed)   │
            └─────────────┘            └─────────────┘  └─────────────┘
```

---

## Component Breakdown

### 1. Frontend — CloudFront + S3 (or ECS Fargate + Nginx)

**Option A: Static hosting (cheaper, simpler)**
- Build the React app with `npm run build`
- Upload `dist/` to an S3 bucket configured for static website hosting
- Put CloudFront in front for SSL, edge caching, and custom domain
- CloudFront origin path: `/` serves the SPA, `index.html` for all routes
- Estimated cost: ~$5-15/month for low traffic

**Option B: ECS Fargate (what docker-compose uses)**
- Nginx container serves the built SPA + proxies `/api/*` to the backend
- Useful if you need server-side rendering or dynamic config injection
- Estimated cost: ~$30-50/month for 1 task (0.25 vCPU, 0.5 GB)

**Why both options?** "For a dashboard SPA, S3 + CloudFront is the standard
pattern. It's serverless, scales to millions of users, and costs pennies. I
included the ECS Fargate option in the docker-compose because it's simpler for
local development and gives us a single entry point."

### 2. Backend — ECS Fargate (FastAPI)

- **Service**: ECS Fargate with 3 tasks minimum (for high availability across AZs)
- **Task definition**: 0.5 vCPU, 1 GB RAM per task (adjust based on load)
- **Scaling**: Target tracking on CPU utilization (target 70%), scale 3-20 tasks
- **Health checks**: ALB health checks on `/health` (expects 200, timeout 5s)
- **Environment**: `ENVIRONMENT=production`, `LOG_LEVEL=INFO`
- **Secrets**: Database password, API keys in AWS Secrets Manager, referenced via
  `secrets` in task definition (not env vars)
- **Discovery**: `SIGNALFORGE_DISCOVERY_ENABLED=true`,
  `SIGNALFORGE_DISCOVERY_PROVIDERS=cloud,config` (Docker/Process disabled in Fargate)

**Why ECS Fargate?** "It's serverless containers — no EC2 to manage. Fargate
handles the infrastructure, patching, and scaling. For a Python backend with
stateless request handling, it's the right balance of control and simplicity."

**Why not Lambda?** "FastAPI with WebSocket support and background Kafka
consumers doesn't fit Lambda's execution model well. Lambda has a 15-minute
max duration and no native WebSocket persistence. ECS Fargate is the right
call for a long-running service with background workers."

**ECS Service Discovery:** In production, the backend uses the `cloud` discovery
provider to read ECS task metadata and AWS Cloud Map service registries. The
`SIGNALFORGE_DISCOVERY_PROVIDERS=cloud,config` environment variable disables
Docker and process discovery (security risk in Fargate) and enables cloud-native
service discovery. The ECS task metadata v4 endpoint (`169.254.170.2`) provides
task family, IP address, and container image information without requiring the
Docker socket.

### 3. Database — RDS PostgreSQL (Multi-AZ)

- **Instance**: db.t3.medium or db.t3.large (start small, scale up)
- **Multi-AZ**: Enabled for automatic failover
- **Storage**: 20 GB gp3 with autoscaling enabled
- **Backups**: 7-day retention, daily snapshots
- **Encryption**: At-rest with AWS KMS, in-transit with SSL
- **pgvector**: Extension installed for semantic search
- **Connection pooling**: Use RDS Proxy or PgBouncer if >100 connections

**Why RDS over Aurora?** "Aurora is great for very high write throughput. For
our workload — mostly reads with periodic writes — RDS PostgreSQL is cheaper and
simpler. Aurora Serverless v2 is an option if traffic is very spiky."

### 4. Hot State — ElastiCache Redis (Cluster Mode)

- **Cluster mode**: Enabled for horizontal scaling
- **Node type**: cache.t3.micro (1 node) for dev, cache.t3.medium (3 shards) for prod
- **Engine**: Redis 7 with cluster mode enabled
- **Persistence**: AOF enabled (append-only file) for durability
- **Security**: VPC security group, no public access, auth token

**Why ElastiCache?** "Redis is already our hot state layer. ElastiCache is
managed Redis — no cluster management, automatic patching, and multi-AZ failover.
For a single-node setup, it's ~$15/month. For cluster mode with 3 shards, ~$100/month."

### 5. Event Streaming — Amazon MSK (Managed Kafka)

- **Cluster type**: MSK Serverless (pay per throughput, no cluster management)
  or MSK Provisioned (1 broker, t3.small for dev)
- **Topics**: `telemetry_events`, `telemetry_events_dead_letter`
- **Retention**: 7 days for telemetry, 30 days for dead letter
- **Security**: IAM authentication (no plaintext credentials), TLS encryption

**Why MSK over self-hosted Kafka?** "Self-hosted Kafka on EC2 requires ZooKeeper,
rebalancing, patching, and monitoring. MSK Serverless handles all of that. For a
demo, even a single-node Redpanda container is fine. But in production, MSK
is the managed service that scales with zero operational overhead."

**Why not Kinesis?** "Kinesis is AWS's native streaming. It's great for simple
fan-out. But Kafka has better consumer group semantics, exactly-once processing,
and wider ecosystem support. Since we already use `kafka-python` and the
consumer group pattern, MSK is the direct migration path."

### 6. Load Balancer — ALB with Path Rules

- **HTTPS**: ACM certificate (free), TLS 1.2+
- **Path rules**:
  - `/*` → Frontend target group (or CloudFront origin)
  - `/api/*` → Backend target group (strip `/api` prefix or handle in backend)
- **Health checks**: `/health` on backend target group
- **Stickiness**: Not needed (stateless backend)
- **WebSocket**: ALB supports WebSocket natively (no extra config needed)

**Why ALB over NLB?** "ALB operates at Layer 7, so it can do path-based routing,
SSL termination, and WebSocket support. NLB is faster but simpler. For a web
app with API routing, ALB is the right choice."

### 7. Secrets — AWS Secrets Manager

Store all sensitive configuration:
- `signforge/database`: RDS master password
- `signforge/openai`: OpenAI API key
- `signforge/api-keys`: JSON mapping of API key → tenant_id

**Why Secrets Manager?** "Environment variables are visible in container
inspect, CloudTrail logs, and process listings. Secrets Manager rotates
credentials automatically and provides fine-grained IAM access. In ECS, you
reference a secret by ARN and the value is injected at runtime — not visible
in the task definition."

### 8. Monitoring — CloudWatch + X-Ray

- **CloudWatch Logs**: Structured logs from backend (already key=value format)
- **CloudWatch Metrics**: Custom metrics for `incidents_created`, `events_ingested_rps`,
  `detection_delay_ms`, `api_latency_p99`
- **CloudWatch Alarms**: 
  - `health_check_failures > 2` for 2 minutes → alert SNS
  - `db_connections > 80%` of max → alert SNS
  - `kafka_consumer_lag > 1000` for 5 minutes → alert SNS
- **X-Ray**: Trace requests from ALB → backend → RDS → Redis (optional but impressive)

**Why not Datadog/New Relic?** "CloudWatch is included with AWS and has no
per-host cost. For a demo, it's sufficient. Datadog is ~$15/host/month and
is the upgrade path when you need more sophisticated dashboards and correlation."

---

## Cost Estimate (Monthly, us-east-1)

| Component | Dev (small) | Prod (medium) |
|-----------|-------------|---------------|
| CloudFront | $5 | $20 |
| S3 (frontend) | $1 | $5 |
| ALB | $16 | $16 |
| ECS Fargate (backend, 3 tasks) | $30 | $120 |
| RDS PostgreSQL (db.t3.medium, Multi-AZ) | $60 | $120 |
| ElastiCache Redis (1 node) | $15 | $50 |
| MSK Serverless | $0 (no traffic) | $50 |
| Secrets Manager | $0.40 | $0.40 |
| CloudWatch | $5 | $20 |
| **Total** | **~$130** | **~$400** |

Notes:
- Dev assumes minimal traffic, no MSK charges (idle)
- Prod assumes moderate traffic, 3 backend tasks, 3 Redis shards
- Costs scale with traffic; add 50% buffer for data transfer
- Reserved instances for RDS/ElastiCache can save 30-40% for 1-year commitments

---

## Deployment Pipeline (CI/CD)

```
GitHub Push → GitHub Actions → Build + Test → Push to ECR → ECS Deploy
```

### GitHub Actions workflow (`.github/workflows/deploy.yml`):

```yaml
name: Deploy to AWS
on:
  push:
    branches: [main]
jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      
      - name: Login to ECR
        uses: aws-actions/amazon-ecr-login@v2
      
      - name: Build and push backend
        run: |
          docker build -t $ECR_REGISTRY/signforge-backend:$GITHUB_SHA ./backend
          docker push $ECR_REGISTRY/signforge-backend:$GITHUB_SHA
      
      - name: Build and push frontend
        run: |
          docker build -t $ECR_REGISTRY/signforge-frontend:$GITHUB_SHA ./frontend
          docker push $ECR_REGISTRY/signforge-frontend:$GITHUB_SHA
      
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster signforge-prod \
            --service backend \
            --force-new-deployment
```

**Why GitHub Actions?** "It's free for public repos, integrates with AWS via
OIDC (no long-lived credentials), and has a large ecosystem of actions. For a
demo, it's the fastest path. AWS CodePipeline is the enterprise alternative."

---

## Terraform Module Structure (conceptual)

```
terraform/
├── modules/
│   ├── vpc/           # VPC, subnets, NAT gateway, IGW
│   ├── ecs/           # ECS cluster, task definitions, services
│   ├── rds/           # RDS PostgreSQL instance, subnet group, security group
│   ├── elasticache/   # Redis cluster, subnet group, security group
│   ├── msk/           # Kafka cluster, security group
│   ├── alb/           # ALB, target groups, listeners, ACM cert
│   ├── cloudfront/    # CloudFront distribution, S3 origin, OAI
│   └── secrets/       # Secrets Manager entries
├── environments/
│   ├── dev/           # Small instances, single AZ, no Multi-AZ
│   └── prod/          # Full HA, Multi-AZ, cluster mode, autoscaling
└── main.tf            # Module composition
```

**Why Terraform?** "Terraform is the industry standard for infrastructure as
code. It defines the desired state, and the provider reconciles it. For interviews,
being able to say 'I use Terraform to manage all AWS resources' shows you
understand IaC, drift detection, and reproducible environments."

---

## Interview Talking Points

### Why ECS Fargate over EKS?
"EKS is Kubernetes — powerful but complex. For a Python backend with 3-20
tasks, Fargate is simpler: no control plane, no node management, no kubectl.
The trade-off is less flexibility (no DaemonSets, limited sidecar patterns).
If we needed complex service mesh or custom networking, EKS would be the next step.

> **EKS Discovery:** If using EKS, the `kubernetes` discovery provider scans pods
> and services in the cluster. The Helm chart includes RBAC (ClusterRole or Role)
> for the service account. The `cloud` provider also runs to enrich discovered
> services with AWS metadata (instance tags, region, account ID). This dual
> provider approach gives both K8s-native and cloud-native context."

### How do you handle zero-downtime deployments?
"ECS rolling updates: the service starts new tasks with the new image, waits
for ALB health checks to pass, then drains old tasks. The ALB connection
draining gives in-flight requests 30 seconds to complete. FastAPI startup is
~2 seconds, so the transition is smooth. For database migrations, we run
Alembic as a one-off ECS task before the deployment, with a lock to prevent
concurrent migrations."

### How do you scale from 100 to 10,000 RPS?
"1. Scale backend tasks: ECS target tracking scales from 3 to 20 tasks based on
CPU. 2. Scale RDS: move from db.t3.medium to db.r6g.xlarge, enable read replicas
for query-heavy endpoints. 3. Scale Redis: ElastiCache cluster mode adds shards.
4. Scale Kafka: MSK Serverless auto-scales partitions. 5. Add caching: CloudFront
for static assets, API response caching for `/incidents` and `/graph`. 6. Database
connection pooling: RDS Proxy handles 1000+ connections. 7. Scale discovery: use
AWS Cloud Map for cross-service discovery instead of per-task scanning. Each step
is independent — we can scale components as needed."

### How do you handle secrets in a 12-factor app?
"The 12-factor app says config in env vars. But AWS best practice is: use Secrets
Manager for sensitive values, env vars for non-sensitive config. In ECS, you
reference a secret by ARN and the agent injects it at runtime. The container
never sees the ARN, just the value. For local development, we use `.env` files
(never committed). For CI/CD, we use GitHub encrypted secrets."

### What happens if the database goes down?
"RDS Multi-AZ has automatic failover: the standby instance is promoted in
60-120 seconds. The backend health check will fail, ALB stops routing traffic,
and ECS keeps the old tasks running. When the DB recovers, the health checks
pass and traffic resumes. During the outage, events ingested via Kafka are
buffered in the topic (7-day retention), so no data is lost. The worker
consumers resume from their last committed offset when the DB is back."

### How do you monitor and alert?
"CloudWatch Logs for structured logs (we already output key=value pairs).
CloudWatch Metrics for custom metrics: `events_ingested`, `incidents_created`,
`detection_delay_ms`. CloudWatch Alarms for anomaly detection: if the backend
health check fails 2+ times in 2 minutes, SNS sends an email to the on-call.
For a demo, SNS → email is fine. For production, SNS → PagerDuty."

### Why not serverless everything (Lambda + API Gateway)?
"Lambda is great for event-driven, short-lived tasks. But our backend has
WebSocket connections, background Kafka consumers, and in-memory state. Lambda
has a 15-minute max duration and no native WebSocket support. ECS Fargate is
the right abstraction for a long-running service. We could use Lambda for
one-off tasks: image processing, batch embedding generation, or periodic
cleanup jobs."
