resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.cluster_name}-redis-subnet"
  subnet_ids = var.private_subnet_ids

  tags = var.tags
}

resource "aws_elasticache_cluster" "main" {
  cluster_id           = "${var.cluster_name}-redis"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [var.security_group_id]
  apply_immediately    = true

  tags = merge(
    { Name = "${var.cluster_name}-redis" },
    var.tags
  )
}
