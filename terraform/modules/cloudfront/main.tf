locals {
  name          = "${var.project_name}-${var.environment}"
  alb_origin_id = "${local.name}-alb-origin"
  has_cert      = var.certificate_arn != "" && var.domain_name != ""
}

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "BlackFriday CDN - caches product catalog, bypasses inventory/checkout"
  price_class     = "PriceClass_100"

  # Custom domain alias — only set when a certificate and domain are provided.
  # With no custom domain, the distribution is reachable via its cloudfront.net hostname.
  aliases = local.has_cert ? [var.domain_name, "www.${var.domain_name}"] : []

  # WAF CLOUDFRONT-scope WebACL must be created in us-east-1 (separate from the
  # REGIONAL ALB WebACL). Left as a future enhancement.

  origin {
    domain_name = var.alb_dns_name
    origin_id   = local.alb_origin_id

    custom_origin_config {
      http_port  = 80
      https_port = 443
      # Use HTTPS to origin when ALB has a validated cert; HTTP-only otherwise.
      origin_protocol_policy = var.alb_https_enabled ? "https-only" : "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Cache product listings for 5 minutes — reduces origin load for the most-read path
  ordered_cache_behavior {
    path_pattern     = "/api/products*"
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.alb_origin_id

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
      headers = ["X-Cache"]
    }

    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 300

    viewer_protocol_policy = "redirect-to-https"
    compress               = true
  }

  # Never cache inventory — always show live stock levels
  ordered_cache_behavior {
    path_pattern     = "/api/inventory*"
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.alb_origin_id

    forwarded_values {
      query_string = true
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0

    viewer_protocol_policy = "redirect-to-https"
  }

  # Never cache checkout — stateful POST endpoint
  ordered_cache_behavior {
    path_pattern     = "/api/checkout*"
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.alb_origin_id

    forwarded_values {
      query_string = true
      cookies { forward = "all" }
      headers      = ["*"]
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0

    viewer_protocol_policy = "redirect-to-https"
  }

  # Default — pass through everything else unchanged
  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.alb_origin_id

    forwarded_values {
      query_string = true
      cookies { forward = "all" }
      headers      = ["*"]
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0

    viewer_protocol_policy = "redirect-to-https"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.has_cert
    acm_certificate_arn            = local.has_cert ? var.certificate_arn : null
    ssl_support_method             = local.has_cert ? "sni-only" : null
    minimum_protocol_version       = local.has_cert ? "TLSv1.2_2021" : "TLSv1"
  }

  tags = { Name = "${local.name}-cloudfront" }
}
