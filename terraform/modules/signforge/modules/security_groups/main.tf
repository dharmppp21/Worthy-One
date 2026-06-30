resource "aws_security_group" "backend" {
  name_prefix = "${var.cluster_name}-backend-"
  description = "Security group for the SignForge backend service."
  vpc_id      = var.vpc_id

  tags = merge(
    { Name = "${var.cluster_name}-backend" },
    var.tags
  )
}

resource "aws_security_group_rule" "backend_ingress_alb" {
  type                     = "ingress"
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  security_group_id        = aws_security_group.backend.id
}

resource "aws_security_group_rule" "backend_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.backend.id
}

resource "aws_security_group" "database" {
  name_prefix = "${var.cluster_name}-db-"
  description = "Security group for the RDS PostgreSQL database."
  vpc_id      = var.vpc_id

  tags = merge(
    { Name = "${var.cluster_name}-db" },
    var.tags
  )
}

resource "aws_security_group_rule" "db_ingress_backend" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.backend.id
  security_group_id        = aws_security_group.database.id
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.cluster_name}-redis-"
  description = "Security group for the ElastiCache Redis cluster."
  vpc_id      = var.vpc_id

  tags = merge(
    { Name = "${var.cluster_name}-redis" },
    var.tags
  )
}

resource "aws_security_group_rule" "redis_ingress_backend" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.backend.id
  security_group_id        = aws_security_group.redis.id
}

resource "aws_security_group" "kafka" {
  name_prefix = "${var.cluster_name}-kafka-"
  description = "Security group for the MSK Kafka cluster."
  vpc_id      = var.vpc_id

  tags = merge(
    { Name = "${var.cluster_name}-kafka" },
    var.tags
  )
}

resource "aws_security_group_rule" "kafka_ingress_backend" {
  type                     = "ingress"
  from_port                = 9092
  to_port                  = 9092
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.backend.id
  security_group_id        = aws_security_group.kafka.id
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.cluster_name}-alb-"
  description = "Security group for the Application Load Balancer."
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(
    { Name = "${var.cluster_name}-alb" },
    var.tags
  )
}
