variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the MSK cluster."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID for the MSK cluster."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
