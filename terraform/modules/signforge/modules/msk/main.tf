resource "aws_msk_cluster" "main" {
  cluster_name           = var.cluster_name
  kafka_version          = "3.5.1"
  number_of_broker_nodes = length(var.private_subnet_ids)

  broker_node_group_info {
    instance_type = "kafka.t3.small"
    client_subnets  = var.private_subnet_ids
    security_groups = [var.security_group_id]

    storage_info {
      ebs_storage_info {
        volume_size = 100
      }
    }
  }

  tags = var.tags
}
