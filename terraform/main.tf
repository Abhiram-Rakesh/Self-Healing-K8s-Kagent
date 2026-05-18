data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Environment = var.environment
    Cluster     = var.cluster_name
  })
}

module "vpc" {
  source = "./modules/vpc"

  cluster_name  = var.cluster_name
  enable_ha_nat = var.enable_ha_nat
  tags          = local.common_tags
}

module "eks" {
  source = "./modules/eks"

  cluster_name        = var.cluster_name
  cluster_version     = var.cluster_version
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  public_subnet_ids   = module.vpc.public_subnet_ids
  system_node_type    = var.system_node_type
  system_node_count   = var.system_node_count
  workload_node_type  = var.workload_node_type
  workload_node_count = var.workload_node_count
  tags                = local.common_tags
}

module "ecr" {
  source = "./modules/ecr"

  repository_name = "kagent-healer"
  tags            = local.common_tags
}

module "iam" {
  source = "./modules/iam"

  cluster_name      = var.cluster_name
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url
  gemini_api_key    = var.gemini_api_key
  slack_webhook_url = var.slack_webhook_url
  tags              = local.common_tags
}
