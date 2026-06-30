output "ecs_execution_role_arn" {
  description = "ECS task execution role ARN."
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ECS task role ARN."
  value       = aws_iam_role.ecs_task.arn
}

output "eks_irsa_role_arn" {
  description = "EKS IRSA role ARN."
  value       = aws_iam_role.eks_irsa.arn
}
