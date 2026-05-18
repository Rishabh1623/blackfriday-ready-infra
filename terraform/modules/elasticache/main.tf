locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name}-cache-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = { Name = "${local.name}-cache-subnet-group" }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name}-redis"
  description          = "BlackFriday Redis - 1 primary + 1 replica"

  engine               = "redis"
  engine_version       = "7.0"
  node_type            = var.cache_node_type
  num_cache_clusters   = 2
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [var.sg_elasticache_id]

  automatic_failover_enabled = true
  multi_az_enabled           = false

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  snapshot_retention_limit = 1
  snapshot_window          = "05:00-06:00"

  tags = { Name = "${local.name}-redis" }
}
