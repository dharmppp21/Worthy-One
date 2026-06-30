output "backend_sg_id" {
  description = "Backend security group ID."
  value       = aws_security_group.backend.id
}

output "database_sg_id" {
  description = "Database security group ID."
  value       = aws_security_group.database.id
}

output "redis_sg_id" {
  description = "Redis security group ID."
  value       = aws_security_group.redis.id
}

output "kafka_sg_id" {
  description = "Kafka security group ID."
  value       = aws_security_group.kafka.id
}

output "alb_sg_id" {
  description = "ALB security group ID."
  value       = aws_security_group.alb.id
}
