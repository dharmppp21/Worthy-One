data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# ------------------------------------------------------------------
# ECS Task Execution Role
# ------------------------------------------------------------------
resource "aws_iam_role" "ecs_execution" {
  name = "${var.cluster_name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "ecs_execution" {
  name = "${var.cluster_name}-ecs-execution-policy"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "secretsmanager:GetSecretValue"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------
# ECS Task Role
# ------------------------------------------------------------------
resource "aws_iam_role" "ecs_task" {
  name = "${var.cluster_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "ecs_task" {
  name = "${var.cluster_name}-ecs-task-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "elasticache:DescribeCacheClusters",
          "kafka:DescribeCluster",
          "secretsmanager:GetSecretValue",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------
# EKS IRSA Role
# ------------------------------------------------------------------
resource "aws_iam_role" "eks_irsa" {
  name = "${var.cluster_name}-eks-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${var.cluster_name}"
        }
        Condition = {
          StringEquals = {
            "${var.cluster_name}:sub" = "system:serviceaccount:default:signforge"
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "eks_irsa" {
  name = "${var.cluster_name}-eks-irsa-policy"
  role = aws_iam_role.eks_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "elasticache:DescribeCacheClusters",
          "kafka:DescribeCluster",
          "secretsmanager:GetSecretValue",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}
