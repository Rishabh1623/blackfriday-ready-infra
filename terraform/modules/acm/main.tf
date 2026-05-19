locals {
  name    = "${var.project_name}-${var.environment}"
  enabled = var.domain_name != ""
  with_r53 = local.enabled && var.route53_zone_id != ""
}

resource "aws_acm_certificate" "main" {
  count = local.enabled ? 1 : 0

  domain_name               = var.domain_name
  subject_alternative_names = ["*.${var.domain_name}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${local.name}-cert" }
}

# Automatically create Route53 DNS validation records when a hosted zone is provided.
# If you manage DNS outside AWS, add these records manually using the
# `certificate_validation_options` output, then set route53_zone_id = "".
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in (local.with_r53 ? aws_acm_certificate.main[0].domain_validation_options : toset([])) :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  zone_id         = var.route53_zone_id
  name            = each.value.name
  records         = [each.value.record]
  type            = each.value.type
  ttl             = 60
}

# Waits until ACM reports the certificate as ISSUED — blocks dependent resources
# (ALB HTTPS listener) from being created with an unvalidated cert.
resource "aws_acm_certificate_validation" "main" {
  count = local.with_r53 ? 1 : 0

  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
