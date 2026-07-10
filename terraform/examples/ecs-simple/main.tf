terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

module "signforge" {
  source = "../../modules/signforge"

  cluster_name = "signforge-dev"
  vpc_id       = "" # Leave empty to create a new VPC

  # No existing subnets — the VPC module will create them
  private_subnet_ids = []
  public_subnet_ids  = []

  # ECS Fargate only (cheaper for dev)
  enable_eks = false
  enable_ecs = true

  # RDS and Redis for data stores
  enable_rds         = true
  enable_elasticache = true
  enable_msk         = false

  # ALB only
  enable_alb        = true
  enable_cloudfront = false

  # ECS sizing (small for dev)
  ecs_task_cpu    = 256
  ecs_task_memory = 512

  # DB sizing (smallest for dev)
  db_instance_class    = "db.t3.micro"
  db_allocated_storage = 20
  db_multi_az          = false

  # Redis sizing (smallest for dev)
  redis_node_type = "cache.t3.micro"

  tags = {
    Environment = "development"
    Team        = "platform"
  }
}

output "service_url" {
  description = "Service URL via ALB."
  value       = module.signforge.service_url
}

output "database_endpoint" {
  description = "RDS endpoint."
  value       = module.signforge.database_endpoint
}

output "redis_endpoint" {
  description = "Redis endpoint."
  value       = module.signforge.redis_endpoint
}

output "ecs_service_arn" {
  description = "ECS service ARN."
  value       = module.signforge.ecs_service_arn
}
