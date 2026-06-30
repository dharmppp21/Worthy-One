# SignForge ECS Simple Example

This example deploys SignForge on ECS Fargate with RDS and ElastiCache.

## Quick Start

```bash
cd terraform/examples/ecs-simple

# 1. Initialize Terraform
terraform init

# 2. Review the plan
terraform plan

# 3. Apply
terraform apply
```

## What gets created

- A new VPC with 3 AZs (public + private subnets, NAT gateway, IGW)
- ECS Fargate cluster with a single task
- RDS PostgreSQL (t3.micro, 20GB, single-AZ)
- ElastiCache Redis (t3.micro)
- Application Load Balancer (HTTP on port 80)
- Security groups with least-privilege rules
- IAM roles for ECS task execution and task permissions

## Outputs

- `service_url` — ALB DNS name
- `database_endpoint` — RDS endpoint
- `redis_endpoint` — Redis endpoint
- `ecs_service_arn` — ECS service ARN

## Teardown

```bash
terraform destroy
```
