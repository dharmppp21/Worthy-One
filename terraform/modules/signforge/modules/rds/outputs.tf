output "endpoint" {
  description = "RDS endpoint address."
  value       = aws_db_instance.main.address
}

output "port" {
  description = "RDS port."
  value       = aws_db_instance.main.port
}

output "db_name" {
  description = "RDS database name."
  value       = aws_db_instance.main.db_name
}

output "secret_arn" {
  description = "Secrets Manager ARN for the DB password."
  value       = aws_secretsmanager_secret.db_password.arn
}
