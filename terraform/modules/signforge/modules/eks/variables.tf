variable "cluster_name" {
  description = "Name of the SignForge cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the EKS cluster."
  type        = list(string)
}

variable "eks_node_instance_types" {
  description = "EKS managed node group instance types."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "eks_desired_capacity" {
  description = "Desired number of EKS worker nodes."
  type        = number
  default     = 2
}

variable "eks_min_capacity" {
  description = "Minimum number of EKS worker nodes."
  type        = number
  default     = 1
}

variable "eks_max_capacity" {
  description = "Maximum number of EKS worker nodes."
  type        = number
  default     = 5
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
