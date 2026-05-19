output "certificate_arn" {
  description = "Validated ACM certificate ARN. Empty string when no domain is configured."
  value = (
    local.with_r53
    ? aws_acm_certificate_validation.main[0].certificate_arn
    : (local.enabled ? aws_acm_certificate.main[0].arn : "")
  )
}

output "certificate_validation_options" {
  description = "DNS records required to validate the certificate (use when route53_zone_id is empty)."
  value       = local.enabled ? aws_acm_certificate.main[0].domain_validation_options : toset([])
}
