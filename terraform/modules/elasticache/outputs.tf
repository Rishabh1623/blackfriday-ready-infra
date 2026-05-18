output "primary_endpoint" {
  description = "Redis primary endpoint address"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "reader_endpoint" {
  description = "Redis reader endpoint address (for read-only operations)"
  value       = aws_elasticache_replication_group.main.reader_endpoint_address
}

output "port" {
  value = aws_elasticache_replication_group.main.port
}

output "replication_group_id" {
  value = aws_elasticache_replication_group.main.id
}
