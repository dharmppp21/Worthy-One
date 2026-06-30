output "endpoint" {
  description = "ElastiCache Redis endpoint."
  value       = aws_elasticache_cluster.main.cache_nodes[0].address
}

output "port" {
  description = "ElastiCache Redis port."
  value       = aws_elasticache_cluster.main.port
}

output "cluster_id" {
  description = "ElastiCache cluster ID."
  value       = aws_elasticache_cluster.main.id
}
