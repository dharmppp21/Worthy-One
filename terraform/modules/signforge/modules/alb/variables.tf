variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for the ALB."
  type        = list(string)
  default     = []
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for internal ALB (if applicable)."
  type        = list(string)
  default     = []
}

variable "security_group_id" {
  description = "Security group ID for the ALB."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
