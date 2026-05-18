locals {
  name           = "${var.project_name}-${var.environment}"
  alb_origin_id  = "${local.name}-alb-origin"
}

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "BlackFriday CDN - caches product catalog, bypasses inventory/checkout"
  price_class     = "PriceClass_100"
  # WAF is attached at the ALB layer (REGIONAL scope). CloudFront WAF requires
  # a separate CLOUDFRONT-scoped WebACL created in us-east-1 — out of scope here.

  origin {
    domain_name = var.alb_dns_name
    origin_id   = local.alb_origin_id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
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

    viewer_protocol_policy = "allow-all"
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

    viewer_protocol_policy = "allow-all"
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

    viewer_protocol_policy = "allow-all"
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

    viewer_protocol_policy = "allow-all"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Name = "${local.name}-cloudfront" }
}
