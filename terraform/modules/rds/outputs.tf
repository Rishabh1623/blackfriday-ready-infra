output "proxy_endpoint" {
  description = "RDS Proxy endpoint for application connections"
  value       = aws_db_proxy.main.endpoint
}

output "db_endpoint" {
  description = "Direct RDS instance endpoint (use only for admin/migration tasks)"
  value       = aws_db_instance.main.endpoint
}

output "secret_arn" {
  description = "Secrets Manager ARN containing DB credentials"
  value       = aws_secretsmanager_secret.db.arn
  sensitive   = true
}

output "db_name" {
  value = aws_db_instance.main.db_name
}

output "db_identifier" {
  description = "RDS instance identifier used as CloudWatch metric dimension"
  value       = aws_db_instance.main.identifier
}
