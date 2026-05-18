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

  project_name = var.project_name
  environment  = var.environment
  alb_dns_name = module.compute.alb_dns_name
}
