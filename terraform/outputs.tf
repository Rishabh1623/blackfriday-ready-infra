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

output "asg_name" {
  description = "Auto Scaling Group name — used by GitHub Actions instance refresh step"
  value       = module.compute.asg_name
}

output "app_bucket_name" {
  description = "S3 bucket holding the app.py artifact — used by GitHub Actions deploy step"
  value       = module.compute.app_bucket_name
}

output "sns_alerts_topic_arn" {
  description = "SNS topic ARN receiving all CloudWatch alarm notifications"
  value       = module.monitoring.sns_topic_arn
}

output "acm_certificate_arn" {
  description = "ACM certificate ARN (empty when no domain is configured)"
  value       = module.acm.certificate_arn
}

output "acm_certificate_validation_options" {
  description = "DNS records to add for manual ACM certificate validation (only relevant when route53_zone_id is empty)"
  value       = module.acm.certificate_validation_options
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC — set as AWS_DEPLOY_ROLE_ARN secret in GitHub"
  value       = var.github_repo != "" ? aws_iam_role.github_actions[0].arn : ""
}
