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

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_rds_id" {
  type = string
}

variable "sg_rds_proxy_id" {
  type = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "db_name" {
  type = string
}

variable "db_username" {
  type = string
}
