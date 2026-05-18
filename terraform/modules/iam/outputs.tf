output "irsa_role_arn" {
  description = "ARN of the IRSA role used by the kagent-healer service account"
  value       = aws_iam_role.irsa.arn
}

output "irsa_role_name" {
  description = "Name of the IRSA role"
  value       = aws_iam_role.irsa.name
}

output "gemini_secret_arn" {
  description = "ARN of the Gemini API key secret"
  value       = aws_secretsmanager_secret.gemini.arn
}

output "slack_secret_arn" {
  description = "ARN of the Slack webhook secret (empty if not provided)"
  value       = try(aws_secretsmanager_secret.slack[0].arn, "")
}
