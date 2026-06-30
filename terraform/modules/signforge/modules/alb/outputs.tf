output "dns_name" {
  description = "ALB DNS name."
  value       = aws_lb.main.dns_name
}

output "arn" {
  description = "ALB ARN."
  value       = aws_lb.main.arn
}

output "target_group_arn" {
  description = "ALB target group ARN."
  value       = aws_lb_target_group.main.arn
}

output "http_listener_arn" {
  description = "HTTP listener ARN."
  value       = aws_lb_listener.http.arn
}
