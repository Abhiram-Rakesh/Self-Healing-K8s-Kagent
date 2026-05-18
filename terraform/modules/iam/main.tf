terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

# ---------------------------------------------------------------------------
# AWS Secrets Manager — stores Gemini API key and Slack webhook
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "gemini" {
  name                    = "kagent/gemini-api-key"
  description             = "Google Gemini API key for the self-healing agent"
  recovery_window_in_days = 0
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "gemini" {
  secret_id     = aws_secretsmanager_secret.gemini.id
  secret_string = var.gemini_api_key
}

resource "aws_secretsmanager_secret" "slack" {
  count                   = var.slack_webhook_url == "" ? 0 : 1
  name                    = "kagent/slack-webhook"
  description             = "Slack webhook URL for self-healing notifications"
  recovery_window_in_days = 0
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "slack" {
  count         = var.slack_webhook_url == "" ? 0 : 1
  secret_id     = aws_secretsmanager_secret.slack[0].id
  secret_string = var.slack_webhook_url
}

# ---------------------------------------------------------------------------
# IRSA role for the agent
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "irsa_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account_name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "irsa" {
  name               = "kagent-healer-irsa"
  description        = "IRSA role for the kagent-healer agent"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "irsa_policy" {
  statement {
    sid     = "ReadKAgentSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:kagent/*",
    ]
  }

  statement {
    sid    = "WriteCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${var.cluster_name}/*",
    ]
  }

  statement {
    sid       = "PublishCloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["KAgent/HealingEvents"]
    }
  }
}

resource "aws_iam_policy" "irsa" {
  name        = "kagent-healer-irsa-policy"
  description = "Permissions for the kagent-healer agent"
  policy      = data.aws_iam_policy_document.irsa_policy.json
  tags        = var.tags
}

resource "aws_iam_role_policy_attachment" "irsa" {
  role       = aws_iam_role.irsa.name
  policy_arn = aws_iam_policy.irsa.arn
}
