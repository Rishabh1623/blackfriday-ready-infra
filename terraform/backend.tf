terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  backend "s3" {
    # Pre-create these resources before running terraform init:
    #   aws s3api create-bucket --bucket <bucket-name> --region us-east-1
    #   aws dynamodb create-table --table-name blackfriday-tfstate-lock \
    #     --attribute-definitions AttributeName=LockID,AttributeType=S \
    #     --key-schema AttributeName=LockID,KeyType=HASH \
    #     --billing-mode PAY_PER_REQUEST --region us-east-1
    bucket         = "blackfriday-tfstate-955510722779"
    key            = "blackfriday/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "blackfriday-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
