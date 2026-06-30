# SignForge EKS Complete Example

This example deploys SignForge on EKS with managed RDS, ElastiCache, and an ALB.

## Quick Start

```bash
cd terraform/examples/eks-complete

# 1. Initialize Terraform
terraform init

# 2. Review the plan
terraform plan

# 3. Apply
terraform apply
```

## What gets created

- A new VPC with 3 AZs (public + private subnets, NAT gateway, IGW)
- EKS cluster (1.29) with managed node groups (t3.medium)
- RDS PostgreSQL (Multi-AZ, t3.medium, 20GB)
- ElastiCache Redis (t3.micro)
- Application Load Balancer (HTTP on port 80)
- Security groups with least-privilege rules
- IAM roles (IRSA for EKS, ECS roles if needed)

## Outputs

- `service_url` — ALB DNS name
- `database_endpoint` — RDS endpoint
- `redis_endpoint` — Redis endpoint
- `eks_cluster_endpoint` — EKS API endpoint

## Teardown

```bash
terraform destroy
```
