# SignalForge AWS Architecture

> Infrastructure-as-Code reference for deploying SignalForge on AWS.

## Table of Contents

- [Overview](#overview)
- [Module Structure](#module-structure)
- [Sub-Modules](#sub-modules)
- [Examples](#examples)
- [Quick Start](#quick-start)
- [Architecture Diagram](#architecture-diagram)
- [Security](#security)

---

## Overview

The Terraform modules in `terraform/modules/signforge/` provision a complete SignalForge environment on AWS. You choose between **EKS** (managed Kubernetes) or **ECS Fargate** (serverless containers) for the compute layer, and between managed or self-hosted data stores.

All resources are created with least-privilege IAM roles, security groups, and encryption at rest.

## Module Structure

```
terraform/modules/signforge/
├── versions.tf          # Terraform >= 1.0, AWS provider >= 5.0
├── variables.tf         # All input variables with sensible defaults
├── main.tf              # Orchestrates sub-modules with conditional count
├── outputs.tf           # Service URL, DB endpoint, Redis endpoint, etc.
└── modules/
    ├── vpc/             # VPC, subnets, NAT, IGW (or data sources)
    ├── security_groups/ # Least-privilege SGs for backend, DB, Redis, ALB
    ├── iam/             # ECS execution/task roles, EKS IRSA role
    ├── eks/             # EKS cluster with managed node groups (IRSA enabled)
    ├── ecs/             # ECS Fargate cluster, task definition, service
    ├── rds/             # PostgreSQL RDS with Secrets Manager password
    ├── elasticache/     # Redis cluster with subnet group
    ├── msk/             # Managed Kafka cluster (optional)
    ├── alb/             # Application Load Balancer with health checks
    └── cloudfront/      # CloudFront distribution + S3 frontend bucket (optional)
```

## Sub-Modules

### VPC (`modules/vpc/`)

Creates a new VPC with public and private subnets across 3 AZs, NAT gateway, and internet gateway. If `vpc_id` is provided, uses data sources instead.

| Output | Description |
|--------|-------------|
| `vpc_id` | VPC ID |
| `private_subnet_ids` | Private subnet IDs |
| `public_subnet_ids` | Public subnet IDs |

### Security Groups (`modules/security_groups/`)

Creates dedicated security groups for each service tier:

- **Backend SG**: ingress from ALB on 8000, egress to all
- **Database SG**: ingress from backend on 5432
- **Redis SG**: ingress from backend on 6379
- **Kafka SG**: ingress from backend on 9092
- **ALB SG**: ingress from internet on 80/443

### IAM (`modules/iam/`)

| Role | Purpose | Permissions |
|------|---------|-------------|
| `ecs_execution` | ECS task execution | ECR pull, CloudWatch Logs, Secrets Manager read |
| `ecs_task` | ECS task runtime | RDS, ElastiCache, MSK, Secrets Manager read |
| `eks_irsa` | EKS pod identity via IRSA | Same as ECS task role, assumed via OIDC |

### EKS (`modules/eks/`)

Uses the official `terraform-aws-modules/eks/aws` module to create an EKS 1.29 cluster with:

- Managed node groups (desired/min/max capacity)
- IRSA (IAM Roles for Service Accounts) enabled
- Public and private endpoint access
- OIDC provider for pod identity

### ECS (`modules/ecs/`)

Creates an ECS Fargate cluster with:

- Task definition with configurable CPU/memory
- CloudWatch Log Group
- Service with desired count
- Fargate launch type (no EC2 management)

### RDS (`modules/rds/`)

Creates a PostgreSQL RDS instance with:

- DB subnet group in private subnets
- Security group allowing backend access
- Master password stored in AWS Secrets Manager
- Multi-AZ support (optional)
- Encryption at rest
- Backup retention (7 days)

### ElastiCache (`modules/elasticache/`)

Creates a Redis cluster with:

- Subnet group in private subnets
- Security group allowing backend access
- Configurable node type

### MSK (`modules/msk/`)

Creates a Managed Kafka cluster with:

- 3 broker nodes across private subnets
- EBS storage (100GB per broker)
- Security group allowing backend access on 9092

### ALB (`modules/alb/`)

Creates an Application Load Balancer with:

- HTTP listener on port 80
- Target group with health checks on `/health`
- Optional HTTPS listener (port 443) with ACM certificate

### CloudFront (`modules/cloudfront/`)

Creates a CloudFront distribution with:

- S3 origin for frontend static assets
- ALB origin for API/backend
- OAI (Origin Access Identity) for S3 access
- Separate cache behaviors for API and static content

## Examples

### EKS Complete (`examples/eks-complete/`)

Full production deployment on EKS with managed data stores.

```bash
cd terraform/examples/eks-complete
terraform init
terraform plan
terraform apply
```

Creates: VPC, EKS cluster, RDS, Redis, ALB.

### ECS Simple (`examples/ecs-simple/`)

Cheaper dev environment on ECS Fargate.

```bash
cd terraform/examples/ecs-simple
terraform init
terraform plan
terraform apply
```

Creates: VPC, ECS cluster, RDS, Redis, ALB (smaller instance sizes).

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/dharmppp21/Worthy-One.git
cd Worthy-One

# 2. Choose an example
cd terraform/examples/eks-complete

# 3. Initialize Terraform
terraform init

# 4. Review the plan
terraform plan

# 5. Apply
terraform apply

# 6. Access the service
terraform output service_url
```

## Architecture Diagram

```
                    ┌─────────────┐
                    │   Internet  │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │    ALB      │  (port 80/443)
                    │  (optional) │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────┴──────┐ ┌───┴────┐ ┌────┴─────┐
       │    EKS      │ │  ECS   │ │ CloudFront│
       │ (optional)  │ │(optional)│(optional)│
       └──────┬──────┘ └───┬────┘ └────┬──────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────┴──────┐
                    │   Backend   │  (port 8000)
                    │   Service   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
   ┌─────┴─────┐     ┌─────┴─────┐     ┌─────┴─────┐
   │   RDS     │     │ElastiCache│     │    MSK    │
   │PostgreSQL │     │  Redis   │     │  Kafka    │
   │(optional) │     │(optional)│     │(optional)│
   └───────────┘     └───────────┘     └───────────┘
```

## Security

- **Least-privilege IAM**: Each service has its own role with only the permissions it needs.
- **Security groups**: Backend can talk to DB/Redis/Kafka, but DB cannot talk to the internet.
- **Private subnets**: All data stores and backend tasks run in private subnets with no public IP.
- **Encryption**: RDS storage is encrypted at rest. Secrets Manager encrypts the DB password.
- **IRSA**: EKS pods use IAM roles without long-lived credentials (OIDC-based).
- **Secrets**: Database passwords are generated by Terraform and stored in AWS Secrets Manager, never in source control.
