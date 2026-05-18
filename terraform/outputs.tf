output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "kubeconfig_command" {
  description = "Command to write a kubeconfig entry for this cluster"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "ecr_repository_url" {
  description = "ECR URL — push the agent image to this address"
  value       = module.ecr.repository_url
}

output "kagent_irsa_role_arn" {
  description = "IRSA role ARN to annotate on the kagent-healer service account"
  value       = module.iam.irsa_role_arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "aws_account_id" {
  description = "AWS account ID used by this deployment"
  value       = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "gemini_secret_arn" {
  description = "ARN of the Gemini API key secret in AWS Secrets Manager"
  value       = module.iam.gemini_secret_arn
}
