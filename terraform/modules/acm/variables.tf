variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "domain_name" {
  type        = string
  description = "Apex domain for the ACM certificate (e.g. example.com). Empty string skips cert creation."
  default     = ""
}

variable "route53_zone_id" {
  type        = string
  description = "Route53 hosted zone ID for automatic DNS validation. Leave empty for manual DNS validation."
  default     = ""
}
