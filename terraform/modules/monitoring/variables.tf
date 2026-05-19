variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Email address to receive CloudWatch alarm notifications via SNS"
}

variable "alb_arn_suffix" {
  type        = string
  description = "ALB ARN suffix (aws_lb.arn_suffix) used as CloudWatch metric dimension"
}

variable "tg_arn_suffix" {
  type        = string
  description = "Target group ARN suffix (aws_lb_target_group.arn_suffix) used as CloudWatch metric dimension"
}

variable "asg_name" {
  type        = string
  description = "Auto Scaling Group name used as CloudWatch metric dimension"
}

variable "rds_instance_id" {
  type        = string
  description = "RDS instance identifier used as CloudWatch metric dimension"
}

variable "cache_replication_group_id" {
  type        = string
  description = "ElastiCache replication group ID used as CloudWatch metric dimension"
}
