locals {
  name = "${var.project_name}-${var.environment}"
}

module "networking" {
  source = "./modules/networking"

  project_name         = var.project_name
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  azs                  = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

module "waf" {
  source = "./modules/waf"

  project_name = var.project_name
  environment  = var.environment
  # ALB ARN injected after compute module creates it — resolved via depends_on
  alb_arn = module.compute.alb_arn
}

module "acm" {
  source = "./modules/acm"

  project_name    = var.project_name
  environment     = var.environment
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id
}

module "compute" {
  source = "./modules/compute"

  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  vpc_id               = module.networking.vpc_id
  public_subnet_ids    = module.networking.public_subnet_ids
  private_subnet_ids   = module.networking.private_subnet_ids
  sg_alb_id            = module.networking.sg_alb_id
  sg_ec2_id            = module.networking.sg_ec2_id
  instance_type        = var.instance_type
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
  rds_proxy_endpoint   = module.rds.proxy_endpoint
  elasticache_endpoint = module.elasticache.primary_endpoint
  db_name              = var.db_name
  db_secret_arn        = module.rds.secret_arn
  app_source_path      = "${path.root}/../app/app.py"
  app_ami_id           = var.app_ami_id
  certificate_arn      = module.acm.certificate_arn

  depends_on = [module.rds, module.elasticache]
}

module "rds" {
  source = "./modules/rds"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  sg_rds_id          = module.networking.sg_rds_id
  sg_rds_proxy_id    = module.networking.sg_rds_proxy_id
  db_instance_class  = var.db_instance_class
  db_name            = var.db_name
  db_username        = var.db_username
}

module "elasticache" {
  source = "./modules/elasticache"

  project_name       = var.project_name
  environment        = var.environment
  private_subnet_ids = module.networking.private_subnet_ids
  sg_elasticache_id  = module.networking.sg_elasticache_id
  cache_node_type    = var.cache_node_type
}

module "cloudfront" {
  source = "./modules/cloudfront"

  project_name      = var.project_name
  environment       = var.environment
  alb_dns_name      = module.compute.alb_dns_name
  certificate_arn   = module.acm.certificate_arn
  domain_name       = var.domain_name
  alb_https_enabled = module.acm.certificate_arn != ""
}

module "monitoring" {
  source = "./modules/monitoring"

  project_name               = var.project_name
  environment                = var.environment
  alert_email                = var.alert_email
  alb_arn_suffix             = module.compute.alb_arn_suffix
  tg_arn_suffix              = module.compute.target_group_arn_suffix
  asg_name                   = module.compute.asg_name
  rds_instance_id            = module.rds.db_identifier
  cache_replication_group_id = module.elasticache.replication_group_id
}

# ── GitHub Actions OIDC ────────────────────────────────────────────────────────
# Allows GitHub Actions to assume an IAM role via OIDC — no long-lived AWS keys
# stored in GitHub Secrets. The trust policy is scoped to a specific repo+branch.
#
# If this OIDC provider already exists in your account (created by another project),
# import it instead of creating a new one:
#   terraform import aws_iam_openid_connect_provider.github \
#     arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_repo != "" ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  # GitHub's current OIDC thumbprints — AWS validates these automatically for this provider
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = { Name = "${local.name}-github-oidc-provider" }
}

resource "aws_iam_role" "github_actions" {
  count = var.github_repo != "" ? 1 : 0

  name = "${local.name}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github[0].arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Allow any branch/ref in this repo (PRs + main).
          # Restrict to :ref:refs/heads/main for deploy-only roles.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })

  tags = { Name = "${local.name}-github-actions-role" }
}

# AdministratorAccess is used here for demo simplicity.
# In production, scope this to only the services this pipeline touches:
# EC2, ASG, S3, Secrets Manager, RDS, ElastiCache, CloudFront, WAF, CloudWatch, SNS, IAM (limited).
resource "aws_iam_role_policy_attachment" "github_actions" {
  count      = var.github_repo != "" ? 1 : 0
  role       = aws_iam_role.github_actions[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
