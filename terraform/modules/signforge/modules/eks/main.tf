module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.29"

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnet_ids

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  enable_irsa = true

  eks_managed_node_groups = {
    main = {
      desired_size = var.eks_desired_capacity
      min_size     = var.eks_min_capacity
      max_size     = var.eks_max_capacity

      instance_types = var.eks_node_instance_types
      capacity_type  = "ON_DEMAND"

      tags = var.tags
    }
  }

  tags = var.tags
}
