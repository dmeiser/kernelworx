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
  description = "Maximum requests per IP per evaluation window before blocking. The CI smoke suite peaks near 2500 req/5min from one shared egress IP and GitHub CI ranges skip the rate rule via the address group, so 2000 stays tight for everyone else."
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

variable "github_token" {
  description = "Optional GitHub token for authenticating calls to api.github.com/meta to avoid IP rate limits"
  type        = string
  default     = ""
  sensitive   = true
}

data "http" "github_meta" {
  count = var.create ? 1 : 0

  url = "https://api.github.com/meta"

  request_headers = merge(
    {
      Accept = "application/json"
    },
    var.github_token != "" ? {
      Authorization = "Bearer ${var.github_token}"
    } : {}
  )
}

locals {
  name                 = "${var.name_prefix}-waf-${var.environment}"
  github_meta_response = jsondecode(var.create ? data.http.github_meta[0].response_body : "{}")
  # The feed mixes IPv4 and IPv6 CIDRs, but the declared IP set holds IPV4 only
  # (the provider passes the list through unfiltered, and a mixed list makes
  # CreateIPSet fail). GitHub-hosted runners have no IPv6 egress, so nothing
  # needed by the CI smoke suite is lost.
  github_actions_cidrs = var.create ? [for c in try(local.github_meta_response["actions"], []) : c if !strcontains(c, ":")] : []
}

# GitHub Actions IP set (#269) built at deploy time from api.github.com/meta.
# Scoped into the rate rule below so CI smoke test runs (peaking near 2500
# req/5min from one shared IP) skip only the per-IP rate limit, without
# loosening protection for everyone else.
resource "aws_wafv2_ip_set" "github_actions" {
  count = var.create ? 1 : 0

  name               = "${local.name}-github-actions"
  description        = "GitHub Actions IP ranges from api.github.com/meta"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = local.github_actions_cidrs

  lifecycle {
    precondition {
      condition     = contains(keys(local.github_meta_response), "actions")
      error_message = "GitHub meta endpoint response is missing the required 'actions' key"
    }
    precondition {
      condition     = length(local.github_actions_cidrs) <= 10000
      error_message = "GitHub Actions IP list exceeds WAF IP set limit of 10000 entries"
    }
  }
}

resource "aws_wafv2_web_acl" "main" {
  count = var.create ? 1 : 0

  name  = local.name
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Per-IP rate limiting (#165), scoped down so GitHub Actions CI ranges skip
  # only the rate limit while remaining subject to every other rule.
  rule {
    name     = "rate-limit"
    priority = 2

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

        scope_down_statement {
          not_statement {
            statement {
              ip_set_reference_statement {
                arn = aws_wafv2_ip_set.github_actions[0].arn
              }
            }
          }
        }
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
      priority = 3

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

# #665: WAF access logging is not available on the CloudFront pricing plans
# Free tier (it is included at Pro+). The web ACL, GitHub Actions IP set,
# per-IP rate rule, and managed core rules stay; CloudWatch WAF metrics on
# the visibility configs are the remaining observation signal until a move
# to Pro reinstates logging.

output "web_acl_id" {
  description = "ID of the CloudFront-scope web ACL (null when create = false)"
  value       = var.create ? aws_wafv2_web_acl.main[0].id : null
}

output "web_acl_arn" {
  description = "ARN of the CloudFront-scope web ACL (null when create = false)"
  value       = var.create ? aws_wafv2_web_acl.main[0].arn : null
}
