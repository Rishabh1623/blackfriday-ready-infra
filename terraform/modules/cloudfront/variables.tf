variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "certificate_arn" {
  type        = string
  default     = ""
  description = "ACM certificate ARN for a custom domain on CloudFront. Empty = use default cloudfront.net certificate."
}

variable "domain_name" {
  type        = string
  default     = ""
  description = "Custom domain (e.g. cdn.example.com) to attach to the distribution. Empty = use cloudfront.net domain."
}

variable "alb_https_enabled" {
  type        = bool
  default     = false
  description = "Set true when the ALB has an HTTPS listener, so CloudFront connects to origin over HTTPS."
}

