# Terraform backend configuration example
# This file shows all possible variable values and their meanings.

# --- Core ---
cluster_name       = "signforge"
vpc_id             = "" # Empty = create new VPC
private_subnet_ids = [] # Empty = create new subnets
public_subnet_ids  = [] # Empty = create new subnets

# --- Compute ---
enable_eks = true
enable_ecs = false

# --- Data Stores ---
enable_rds         = true
enable_elasticache = true
enable_msk         = false

# --- Networking ---
enable_alb        = true
enable_cloudfront = false

# --- EKS ---
eks_node_instance_types = ["t3.medium"]
eks_desired_capacity    = 2
eks_min_capacity        = 1
eks_max_capacity        = 5

# --- ECS ---
ecs_task_cpu    = 512
ecs_task_memory = 1024
container_image = "ghcr.io/dharmppp21/signforge:latest"

# --- RDS ---
db_instance_class    = "db.t3.medium"
db_allocated_storage = 20
db_multi_az          = false

# --- ElastiCache ---
redis_node_type = "cache.t3.micro"

# --- Tags ---
tags = {
  Environment = "production"
  Team        = "platform"
}
