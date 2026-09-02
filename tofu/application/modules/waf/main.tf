# AWS WAF Module (CloudFront scope)
# One CLOUDFRONT-scope web ACL attached to the site distribution via web_acl_id.
# Ephemeral environments pass create = false: zero WAF objects, zero cost.

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod, ephemeral run-id)"
  type        = string
}

variable "create" {
  description = "Whether to create the WAF resources (false = ephemeral opt-out)"
  type        = bool
  default     = true
}

variable "rate_limit" {
  description = "Maximum requests per IP per evaluation window before blocking"
  type        = number
  default     = 2000
}

variable "rate_evaluation_window" {
  description = "Rate rule evaluation window in seconds (60, 120, 300, or 600)"
  type        = number
  default     = 300
}

variable "rate_rule_action" {
  description = "Action for the per-IP rate-based rule (Block or Count)"
  type        = string
  default     = "Block"

  validation {
    condition     = contains(["Block", "Count"], var.rate_rule_action)
    error_message = "rate_rule_action must be Block or Count"
  }
}

variable "enable_core_managed_rules" {
  description = "Whether to include the AWS managed core rule set"
  type        = bool
  default     = true
}

variable "managed_rule_action" {
  description = "Effective action for the AWS managed core rule set (Count during staged rollout, Block later)"
  type        = string
  default     = "Count"

  validation {
    condition     = contains(["Block", "Count"], var.managed_rule_action)
    error_message = "managed_rule_action must be Block or Count"
  }
}

variable "log_retention_days" {
  description = "CloudWatch log group retention in days"
  type        = number
  default     = 7
}

locals {
  name = "${var.name_prefix}-waf-${var.environment}"
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_wafv2_web_acl" "main" {
  count = var.create ? 1 : 0

  name  = local.name
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Per-IP rate limiting (#165). Block by default; flip to Count to observe.
  rule {
    name     = "rate-limit"
    priority = 1

    action {
      dynamic "block" {
        for_each = var.rate_rule_action == "Block" ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.rate_rule_action == "Count" ? [1] : []
        content {}
      }
    }

    statement {
      rate_based_statement {
        limit                 = var.rate_limit
        aggregate_key_type    = "IP"
        evaluation_window_sec = var.rate_evaluation_window
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # AWS managed core rule set, staged in Count before switching to Block.
  dynamic "rule" {
    for_each = var.enable_core_managed_rules ? [1] : []

    content {
      name     = "aws-core-managed-rules"
      priority = 2

      override_action {
        dynamic "none" {
          for_each = var.managed_rule_action == "Block" ? [1] : []
          content {}
        }
        dynamic "count" {
          for_each = var.managed_rule_action == "Count" ? [1] : []
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          name        = "AWSManagedRulesCommonRuleSet"
          vendor_name = "AWS"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.name}-aws-core-managed-rules"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

# Sampled WAF logging per the edge-security design: enough to tune the rate
# limit and observe rule matches. Included WAF log volume is free-tier sized.
resource "aws_cloudwatch_log_group" "waf" {
  count = var.create ? 1 : 0

  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
}

# CloudWatch requires a log-resource policy granting the WAF log delivery
# principal before the logging configuration can attach.
data "aws_iam_policy_document" "waf_log_delivery" {
  count = var.create ? 1 : 0

  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${aws_cloudwatch_log_group.waf[0].arn}:*"]

    condition {
      test     = "ArnLike"
      values   = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"]
      variable = "aws:SourceArn"
    }

    condition {
      test     = "StringEquals"
      values   = [data.aws_caller_identity.current.account_id]
      variable = "aws:SourceAccount"
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf_log_delivery" {
  count = var.create ? 1 : 0

  policy_name     = "${local.name}-log-delivery"
  policy_document = data.aws_iam_policy_document.waf_log_delivery[0].json
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  count = var.create ? 1 : 0

  resource_arn            = aws_wafv2_web_acl.main[0].arn
  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]

  depends_on = [aws_cloudwatch_log_resource_policy.waf_log_delivery]
}

output "web_acl_id" {
  description = "ID of the CloudFront-scope web ACL (null when create = false)"
  value       = var.create ? aws_wafv2_web_acl.main[0].id : null
}

output "web_acl_arn" {
  description = "ARN of the CloudFront-scope web ACL (null when create = false)"
  value       = var.create ? aws_wafv2_web_acl.main[0].arn : null
}
