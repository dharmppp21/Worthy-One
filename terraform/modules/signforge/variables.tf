variable "cluster_name" {
  description = "Name of the SignForge cluster. Used as a prefix for most resources."
  type        = string
}

variable "vpc_id" {
  description = "ID of an existing VPC. If empty, a new VPC will be created."
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for backend workloads."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for ALB / CloudFront origins. Optional."
  type        = list(string)
  default     = []
}

variable "enable_eks" {
  description = "Deploy an EKS cluster for the backend."
  type        = bool
  default     = true
}

variable "enable_ecs" {
  description = "Deploy an ECS Fargate cluster for the backend."
  type        = bool
  default     = false
}

variable "enable_rds" {
  description = "Create an RDS PostgreSQL instance."
  type        = bool
  default     = true
}

variable "enable_elasticache" {
  description = "Create an ElastiCache Redis cluster."
  type        = bool
  default     = true
}

variable "enable_msk" {
  description = "Create an MSK (Managed Kafka) cluster."
  type        = bool
  default     = false
}

variable "enable_alb" {
  description = "Create an Application Load Balancer."
  type        = bool
  default     = true
}

variable "enable_cloudfront" {
  description = "Create a CloudFront distribution for the frontend."
  type        = bool
  default     = false
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.medium"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 20
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "ecs_task_cpu" {
  description = "ECS Fargate task CPU units."
  type        = number
  default     = 512
}

variable "ecs_task_memory" {
  description = "ECS Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "eks_node_instance_types" {
  description = "EKS managed node group instance types."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "eks_desired_capacity" {
  description = "Desired number of EKS worker nodes."
  type        = number
  default     = 2
}

variable "eks_min_capacity" {
  description = "Minimum number of EKS worker nodes."
  type        = number
  default     = 1
}

variable "eks_max_capacity" {
  description = "Maximum number of EKS worker nodes."
  type        = number
  default     = 5
}

variable "container_image" {
  description = "SignalForge container image."
  type        = string
  default     = "ghcr.io/dharmppp21/signforge:latest"
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
