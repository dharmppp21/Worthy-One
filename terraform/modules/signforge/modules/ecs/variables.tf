variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks."
  type        = list(string)
}

variable "container_image" {
  description = "SignalForge container image."
  type        = string
  default     = "ghcr.io/dharmppp21/signforge:latest"
}

variable "ecs_task_cpu" {
  description = "ECS task CPU units."
  type        = number
  default     = 512
}

variable "ecs_task_memory" {
  description = "ECS task memory in MiB."
  type        = number
  default     = 1024
}

variable "task_execution_role_arn" {
  description = "ECS task execution role ARN."
  type        = string
}

variable "task_role_arn" {
  description = "ECS task role ARN."
  type        = string
}

variable "security_group_id" {
  description = "Security group ID for ECS tasks."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
