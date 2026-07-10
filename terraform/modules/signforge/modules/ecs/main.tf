resource "aws_ecs_cluster" "main" {
  name = var.cluster_name

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "main" {
  name              = "/ecs/${var.cluster_name}"
  retention_in_days = 7

  tags = var.tags
}

resource "aws_ecs_task_definition" "main" {
  family                   = var.cluster_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "signforge"
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.main.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "ecs"
        }
      }
      environment = [
        { name = "SERVICE_PORT", value = "8000" }
      ]
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "main" {
  name            = var.cluster_name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.main.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  tags = var.tags
}

data "aws_region" "current" {}
