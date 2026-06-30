output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.main.arn
}

output "service_arn" {
  description = "ECS service ARN."
  value       = aws_ecs_service.main.id
}

output "task_definition_arn" {
  description = "ECS task definition ARN."
  value       = aws_ecs_task_definition.main.arn
}
