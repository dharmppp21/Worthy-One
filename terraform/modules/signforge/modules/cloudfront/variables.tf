variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "alb_dns_name" {
  description = "ALB DNS name for the CloudFront origin."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
