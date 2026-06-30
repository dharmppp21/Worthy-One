resource "aws_db_subnet_group" "main" {
  name       = "${var.cluster_name}-db-subnet"
  subnet_ids = var.private_subnet_ids

  tags = merge(
    { Name = "${var.cluster_name}-db-subnet" },
    var.tags
  )
}

resource "random_password" "db_master" {
  length           = 32
  special          = true
  override_special = "!#%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.cluster_name}-db-password"
  description             = "Master password for the ${var.cluster_name} RDS instance"
  recovery_window_in_days = 7

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db_master.result
}

resource "aws_db_instance" "main" {
  identifier              = var.cluster_name
  engine                  = "postgres"
  engine_version          = "15"
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  max_allocated_storage   = var.db_allocated_storage * 2
  db_name                 = "signforge"
  username                = "signforge"
  password                = random_password.db_master.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [var.security_group_id]
  multi_az                = var.db_multi_az
  storage_encrypted       = true
  backup_retention_period = 7
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.cluster_name}-final"
  deletion_protection     = false

  tags = merge(
    { Name = "${var.cluster_name}-db" },
    var.tags
  )
}
