locals {
  create_vpc = var.vpc_id == "" ? true : false
  vpc_id     = local.create_vpc ? module.vpc[0].vpc_id : var.vpc_id
  private_subnet_ids = local.create_vpc ? module.vpc[0].private_subnet_ids : var.private_subnet_ids
  public_subnet_ids  = local.create_vpc ? module.vpc[0].public_subnet_ids : var.public_subnet_ids

  default_tags = merge(
    {
      Name        = var.cluster_name
      Environment = "production"
      ManagedBy   = "terraform"
    },
    var.tags
  )
}

# ------------------------------------------------------------------
# VPC (data source or create)
# ------------------------------------------------------------------
module "vpc" {
  source = "./modules/vpc"
  count  = local.create_vpc ? 1 : 0

  cluster_name = var.cluster_name
  tags         = local.default_tags
}

# ------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------
module "security_groups" {
  source = "./modules/security_groups"

  cluster_name = var.cluster_name
  vpc_id       = local.vpc_id
  tags         = local.default_tags
}

# ------------------------------------------------------------------
# IAM Roles
# ------------------------------------------------------------------
module "iam" {
  source = "./modules/iam"

  cluster_name = var.cluster_name
  tags         = local.default_tags
}

# ------------------------------------------------------------------
# RDS PostgreSQL
# ------------------------------------------------------------------
module "rds" {
  source = "./modules/rds"
  count  = var.enable_rds ? 1 : 0

  cluster_name         = var.cluster_name
  vpc_id               = local.vpc_id
  private_subnet_ids   = local.private_subnet_ids
  db_instance_class    = var.db_instance_class
  db_allocated_storage = var.db_allocated_storage
  db_multi_az          = var.db_multi_az
  security_group_id    = module.security_groups.database_sg_id
  tags                 = local.default_tags
}

# ------------------------------------------------------------------
# ElastiCache Redis
# ------------------------------------------------------------------
module "elasticache" {
  source = "./modules/elasticache"
  count  = var.enable_elasticache ? 1 : 0

  cluster_name      = var.cluster_name
  vpc_id            = local.vpc_id
  private_subnet_ids = local.private_subnet_ids
  redis_node_type   = var.redis_node_type
  security_group_id = module.security_groups.redis_sg_id
  tags              = local.default_tags
}

# ------------------------------------------------------------------
# MSK Kafka
# ------------------------------------------------------------------
module "msk" {
  source = "./modules/msk"
  count  = var.enable_msk ? 1 : 0

  cluster_name      = var.cluster_name
  vpc_id            = local.vpc_id
  private_subnet_ids = local.private_subnet_ids
  security_group_id = module.security_groups.kafka_sg_id
  tags              = local.default_tags
}

# ------------------------------------------------------------------
# EKS
# ------------------------------------------------------------------
module "eks" {
  source = "./modules/eks"
  count  = var.enable_eks ? 1 : 0

  cluster_name             = var.cluster_name
  vpc_id                   = local.vpc_id
  private_subnet_ids       = local.private_subnet_ids
  eks_node_instance_types  = var.eks_node_instance_types
  eks_desired_capacity     = var.eks_desired_capacity
  eks_min_capacity         = var.eks_min_capacity
  eks_max_capacity         = var.eks_max_capacity
  tags                     = local.default_tags
}

# ------------------------------------------------------------------
# ECS
# ------------------------------------------------------------------
module "ecs" {
  source = "./modules/ecs"
  count  = var.enable_ecs ? 1 : 0

  cluster_name       = var.cluster_name
  vpc_id             = local.vpc_id
  private_subnet_ids = local.private_subnet_ids
  container_image    = var.container_image
  ecs_task_cpu       = var.ecs_task_cpu
  ecs_task_memory    = var.ecs_task_memory
  task_execution_role_arn = module.iam.ecs_execution_role_arn
  task_role_arn       = module.iam.ecs_task_role_arn
  security_group_id  = module.security_groups.backend_sg_id
  tags               = local.default_tags
}

# ------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------
module "alb" {
  source = "./modules/alb"
  count  = var.enable_alb ? 1 : 0

  cluster_name       = var.cluster_name
  vpc_id             = local.vpc_id
  public_subnet_ids  = local.public_subnet_ids
  private_subnet_ids = local.private_subnet_ids
  security_group_id  = module.security_groups.alb_sg_id
  tags               = local.default_tags
}

# ------------------------------------------------------------------
# CloudFront
# ------------------------------------------------------------------
module "cloudfront" {
  source = "./modules/cloudfront"
  count  = var.enable_cloudfront ? 1 : 0

  cluster_name       = var.cluster_name
  alb_dns_name       = var.enable_alb ? module.alb[0].dns_name : ""
  tags               = local.default_tags
}
