terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

module "signforge" {
  source = "../../modules/signforge"

  cluster_name = "signforge-prod"
  vpc_id       = "" # Leave empty to create a new VPC

  # No existing subnets — the VPC module will create them
  private_subnet_ids = []
  public_subnet_ids  = []

  # EKS enabled with managed node groups
  enable_eks = true
  enable_ecs = false

  # Managed data stores
  enable_rds         = true
  enable_elasticache = true
  enable_msk         = false

  # Networking
  enable_alb       = true
  enable_cloudfront = false

  # EKS sizing
  eks_node_instance_types = ["t3.medium"]
  eks_desired_capacity    = 3
  eks_min_capacity        = 2
  eks_max_capacity        = 6

  # DB sizing
  db_instance_class    = "db.t3.medium"
  db_allocated_storage = 20
  db_multi_az          = true

  # Redis sizing
  redis_node_type = "cache.t3.micro"

  tags = {
    Environment = "production"
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

output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint."
  value       = module.signforge.eks_cluster_endpoint
}
