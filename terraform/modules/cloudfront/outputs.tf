output "distribution_domain_name" {
  description = "CloudFront distribution domain — use as BASE_URL for load tests"
  value       = aws_cloudfront_distribution.main.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "distribution_arn" {
  value = aws_cloudfront_distribution.main.arn
}
