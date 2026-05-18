output "web_acl_arn" {
  description = "WAF Web ACL ARN"
  value       = aws_wafv2_web_acl.main.arn
}

output "web_acl_id" {
  value = aws_wafv2_web_acl.main.id
}
