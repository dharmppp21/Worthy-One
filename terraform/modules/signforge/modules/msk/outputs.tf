output "bootstrap_brokers" {
  description = "MSK bootstrap brokers."
  value       = aws_msk_cluster.main.bootstrap_brokers
}

output "cluster_arn" {
  description = "MSK cluster ARN."
  value       = aws_msk_cluster.main.arn
}

output "cluster_id" {
  description = "MSK cluster ID."
  value       = aws_msk_cluster.main.id
}
