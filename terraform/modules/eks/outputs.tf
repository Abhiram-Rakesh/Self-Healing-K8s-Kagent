output "cluster_name" {
  description = "EKS cluster name"
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded cluster CA certificate"
  value       = aws_eks_cluster.this.certificate_authority[0].data
}

output "cluster_security_group_id" {
  description = "Security group attached to the EKS control plane"
  value       = aws_security_group.cluster.id
}

output "oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider for IRSA"
  value       = aws_iam_openid_connect_provider.oidc.arn
}

output "oidc_provider_url" {
  description = "OIDC issuer URL of the cluster (without https://)"
  value       = replace(aws_iam_openid_connect_provider.oidc.url, "https://", "")
}

output "node_role_arn" {
  description = "IAM role ARN used by managed node groups"
  value       = aws_iam_role.node.arn
}
