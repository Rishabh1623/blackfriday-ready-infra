variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alb_arn" {
  type        = string
  description = "ALB ARN to associate with the WAF Web ACL"
}
