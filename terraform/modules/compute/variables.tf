variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_alb_id" {
  type = string
}

variable "sg_ec2_id" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "asg_min_size" {
  type    = number
  default = 2
}

variable "asg_max_size" {
  type    = number
  default = 20
}

variable "asg_desired_capacity" {
  type    = number
  default = 2
}

variable "rds_proxy_endpoint" {
  type = string
}

variable "elasticache_endpoint" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_secret_arn" {
  type = string
}

variable "app_source_path" {
  type        = string
  description = "Local path to app.py — uploaded to S3 and pulled by every EC2 instance at boot"
}

variable "app_ami_id" {
  type        = string
  default     = ""
  description = "Pre-baked AMI with Python packages pre-installed. If empty, falls back to latest AL2023 AMI."
}
