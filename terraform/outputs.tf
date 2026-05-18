output "alb_dns_name" {
  description = "ALB DNS name — use this for direct API calls and seed.py"
  value       = module.compute.alb_dns_name
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain — use this as BASE_URL for k6 load tests"
  value       = module.cloudfront.distribution_domain_name
}

output "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint for application database connections"
  value       = module.rds.proxy_endpoint
}

output "elasticache_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = module.elasticache.primary_endpoint
}

output "db_secret_arn" {
  description = "Secrets Manager ARN containing DB credentials"
  value       = module.rds.secret_arn
  sensitive   = true
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "cloudwatch_dashboard_name" {
  description = "CloudWatch dashboard name"
  value       = "BlackFriday-Ops"
}
