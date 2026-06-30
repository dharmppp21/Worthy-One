variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
