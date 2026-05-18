variable "project_name" {
  description = "Prefix applied to all resource names"
  type        = string
  default     = "blackfriday"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "azs" {
  description = "Availability zones (must be 3)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (ALB)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (EC2, RDS, ElastiCache)"
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "instance_type" {
  description = "EC2 instance type for application servers"
  type        = string
  default     = "t3.medium"
}

variable "asg_min_size" {
  description = "ASG minimum instance count"
  type        = number
  default     = 2
}

variable "asg_max_size" {
  description = "ASG maximum instance count"
  type        = number
  default     = 20
}

variable "asg_desired_capacity" {
  description = "ASG desired instance count"
  type        = number
  default     = 2
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "blackfriday"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "blackfridayadmin"
}

variable "cache_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "app_ami_id" {
  description = "Pre-baked AMI with Python packages pre-installed. Empty string falls back to latest AL2023."
  type        = string
  default     = "ami-0940d2c40616b4152"
}
