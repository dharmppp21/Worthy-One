output "service_url" {
  description = "URL to access the SignForge service."
  value       = var.enable_cloudfront ? (var.enable_cloudfront ? module.cloudfront[0].domain_name : "") : (var.enable_alb ? module.alb[0].dns_name : "")
}

output "database_endpoint" {
  description = "RDS PostgreSQL endpoint."
  value       = var.enable_rds ? module.rds[0].endpoint : ""
}

output "database_port" {
  description = "RDS PostgreSQL port."
  value       = var.enable_rds ? module.rds[0].port : ""
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint."
  value       = var.enable_elasticache ? module.elasticache[0].endpoint : ""
}

output "redis_port" {
  description = "ElastiCache Redis port."
  value       = var.enable_elasticache ? module.elasticache[0].port : ""
}

output "eks_cluster_endpoint" {
  description = "EKS cluster API endpoint."
  value       = var.enable_eks ? module.eks[0].cluster_endpoint : ""
}

output "eks_cluster_name" {
  description = "EKS cluster name."
  value       = var.enable_eks ? module.eks[0].cluster_name : ""
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN."
  value       = var.enable_ecs ? module.ecs[0].cluster_arn : ""
}

output "ecs_service_arn" {
  description = "ECS service ARN."
  value       = var.enable_ecs ? module.ecs[0].service_arn : ""
}

output "msk_bootstrap_brokers" {
  description = "MSK bootstrap brokers."
  value       = var.enable_msk ? module.msk[0].bootstrap_brokers : ""
}

output "alb_dns_name" {
  description = "ALB DNS name."
  value       = var.enable_alb ? module.alb[0].dns_name : ""
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name."
  value       = var.enable_cloudfront ? module.cloudfront[0].domain_name : ""
}
