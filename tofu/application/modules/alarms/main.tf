# Operational alarms for the public-orders API surface (KW-PUBLIC-ORDERS spec §9,
# slice 10). This module is the repo's first aws_cloudwatch_metric_alarm: before
# it the only alerting anywhere was the bootstrap cost budgets
# (tofu/bootstrap/budgets/, which notify by direct email subscriber).
#
# Notification shape: a CloudWatch alarm can only act on an SNS topic, so this
# module owns one ops topic per environment and wires every alarm to it. The
# topic's email subscription is created unconfirmed and must be confirmed once
# by clicking the link in the first delivery (out of band, like the SES identity
# verification). Until confirmed, the alarms still fire — they just have no
# delivery target.
#
# Ephemeral environments do not instantiate this module at all (the #665 WAF /
# SES pattern): zero alarm objects, zero cost. `create = false` is kept as the
# explicit opt-out so a future environment can no-op without deleting the
# module call.
#
# Metric names and dimensions below were verified against the live dev account's
# CloudWatch metric list (`aws cloudwatch list-metrics`), not from memory:
#   AWS/AppSync  4XXError            dimensions: GraphQLAPIId
#   AWS/SES      Reputation.BounceRate   / Reputation.ComplaintRate  (no dimensions)
#
# There is deliberately NO CloudTrail and NO X-Ray here — both are excluded from
# this design (xray_enabled = false on the API, and the KICS exclusion for X-Ray
# in tofu/.kics.yml).

locals {
  name = "${var.name_prefix}-alarms-${var.environment}"

  # The reminder fires 30 days before the key's own `expires` value, derived
  # from it rather than written as a second literal: renewal edits one date
  # (api.tf's `expires`) and the reminder follows automatically. Unpadded
  # day/month because that is the form the AWS cron examples use (formatdate's
  # layout string cannot carry the literal "cron" text, so the fields are
  # interpolated).
  api_key_expiry_reminder_day      = var.api_key_expiry == "" ? "" : trimprefix(formatdate("DD", timeadd(var.api_key_expiry, "-720h")), "0")
  api_key_expiry_reminder_month    = var.api_key_expiry == "" ? "" : trimprefix(formatdate("MM", timeadd(var.api_key_expiry, "-720h")), "0")
  api_key_expiry_reminder_schedule = "cron(0 14 ${local.api_key_expiry_reminder_day} ${local.api_key_expiry_reminder_month} ? *)"
}

# ---------------------------------------------------------------------------
# Notification target
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ops_alerts" {
  # The only publisher is the account's own EventBridge rules (the API-key
  # expiry reminder). Alarms reach the topic through alarm_actions, which the
  # CloudWatch service principal is granted through the service itself.
  statement {
    sid       = "AllowEventBridgePublish"
    effect    = "Allow"
    actions   = ["SNS:Publish"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }

  statement {
    sid       = "RequireTls"
    effect    = "Deny"
    actions   = ["SNS:Publish", "SNS:Subscribe", "SNS:Receive"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sns_topic" "ops_alerts" {
  count = var.create ? 1 : 0

  # SNS encrypts at rest, but KICS wants a customer-managed key here (HIGH when
  # the attribute is absent, MEDIUM when it is the AWS-managed one). A CMK costs
  # $1/month for a topic whose only payload is an alarm name — the same
  # KMS-avoidance posture already taken for the DynamoDB tables and the
  # CloudWatch log groups (tofu/.kics.yml).
  name = "${local.name}-ops"
  # kics-scan ignore-line -- AWS-managed SNS key, not a CMK: see the cost note above
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Name = "${local.name}-ops"
  }
}

resource "aws_sns_topic_policy" "ops_alerts" {
  count = var.create ? 1 : 0

  arn    = aws_sns_topic.ops_alerts[0].arn
  policy = data.aws_iam_policy_document.ops_alerts.json
}

# Direct email, matching the bootstrap budgets precedent (no cross-account or
# SNS-to-SNS fan-out in this design). One-time confirmation is a runbook step.
resource "aws_sns_topic_subscription" "ops_email" {
  count = var.create ? 1 : 0

  topic_arn = aws_sns_topic.ops_alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------------------
# Public-surface 4xx / throttle alarm (dev + prod)
# ---------------------------------------------------------------------------
#
# AppSync answers a bad/expired API key, a bad share token, and a throttled
# request all as HTTP 4xx, and every one of them lands in the same `4XXError`
# metric. The spike (data/KW-PUBLIC-ORDERS §5.1) measured the API-key throttle
# bucket at ~9,000 r/s sustained with 429 `LimitExceededException` bodies and no
# `Retry-After`, so a sustained 4xx climb is the flood signal, and a step
# function to "all public calls failing" is the day-zero key-expiry signal.
#
# Stated honestly: `4XXError` carries only the GraphQLAPIId dimension — there
# is no auth-mode dimension — so this alarm is API-wide, not key-scoped. Cognito
# client errors count toward it too. The threshold sits above organic bad-token
# noise and far below flood volume; tune it from the metric once real buyer
# traffic exists.

resource "aws_cloudwatch_metric_alarm" "appsync_4xx" {
  count = var.create ? 1 : 0

  alarm_name          = "${local.name}-appsync-4xx"
  alarm_description   = "AppSync 4xx (incl. API-key auth failures and throttled public calls) reached ${var.appsync_4xx_threshold} in ${var.appsync_4xx_period_seconds}s"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = var.appsync_4xx_threshold
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/AppSync"
  metric_name = "4XXError"
  period      = var.appsync_4xx_period_seconds
  statistic   = "Sum"

  dimensions = {
    GraphQLAPIId = var.appsync_api_id
  }

  alarm_actions = [aws_sns_topic.ops_alerts[0].arn]
}

# ---------------------------------------------------------------------------
# SES reputation alarms (prod only)
# ---------------------------------------------------------------------------
#
# Q3 (spec §12): bounce handling is SES's built-in account-level suppression
# plus exactly one alarm surface on the reputation metrics — no custom
# SNS-to-Lambda suppression pipeline in v1. Reputation is account-level, so the
# alarm belongs to the prod account only; dev sends are sandbox-verified
# recipients on a dev-owned subdomain and its reputation is not the buyer-facing
# signal.
#
# Both metrics are published with NO dimensions (verified against the live
# metric list), so the alarms carry no dimensions block and aggregate the whole
# account/region. treat_missing_data = notBreaching matters: an account that has
# sent nothing publishes nothing, and missing data must not read as healthy-by-
# accident in one direction or alarming in the other.

resource "aws_cloudwatch_metric_alarm" "ses_bounce_rate" {
  count = var.create && var.ses_reputation_enabled ? 1 : 0

  alarm_name          = "${local.name}-ses-bounce-rate"
  alarm_description   = "SES account hard-bounce rate reached ${var.ses_bounce_rate_threshold}% (1h average); SES restricts sending above this band"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = var.ses_bounce_rate_threshold
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/SES"
  metric_name = "Reputation.BounceRate"
  period      = 3600
  statistic   = "Average"

  alarm_actions = [aws_sns_topic.ops_alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "ses_complaint_rate" {
  count = var.create && var.ses_reputation_enabled ? 1 : 0

  alarm_name          = "${local.name}-ses-complaint-rate"
  alarm_description   = "SES account complaint rate reached ${var.ses_complaint_rate_threshold}% (1h average); SES restricts sending above this band"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = var.ses_complaint_rate_threshold
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/SES"
  metric_name = "Reputation.ComplaintRate"
  period      = 3600
  statistic   = "Average"

  alarm_actions = [aws_sns_topic.ops_alerts[0].arn]
}

# ---------------------------------------------------------------------------
# Public-orders API-key expiry reminder (prod only) — the spec's "ExpiredAPIKeys
# alarm"
# ---------------------------------------------------------------------------
#
# Verified against the live account and the AppSync monitoring docs: AWS
# publishes NO ExpiredAPIKeys metric (AWS/AppSync vends 4XXError, 5XXError,
# Latency, Requests, TokensConsumed, and the subscription/enhanced metrics —
# none of them key-expiry). So the spec's named alarm cannot be a metric alarm
# on an expiry signal; the day-zero symptom itself is caught by the 4XX alarm
# above (an expired key makes every public call answer Unauthorized, which is a
# 4xx). What a metric cannot give is advance warning, and that is the half the
# spec actually asks for ("day-zero expiry otherwise means every public call
# fails Unauthorized ... with no warning").
#
# So the expiry half ships as a scheduled reminder: an EventBridge rule 30 days
# before the key's own `expires` value (derived from it, never a second literal),
# publishing a static message to the same ops topic. Zero compute, no new
# Lambda, no custom metric. Renewing the key therefore moves the reminder by
# itself — the drift the runbook has to guard is only the bundle/key cutover
# order (docs/PUBLIC_API_KEY_RUNBOOK.md). The repo-side tripwire, tests/unit/
# test_public_api_key_surface.py's expiry date gate, stays as the CI half.

resource "aws_cloudwatch_event_rule" "api_key_expiry_reminder" {
  count = var.create && var.api_key_expiry_reminder_enabled ? 1 : 0

  name                = "${local.name}-public-api-key-expiry"
  description         = "Renewal reminder for the public-orders AppSync API key (expires ${var.api_key_expiry})"
  schedule_expression = local.api_key_expiry_reminder_schedule

  lifecycle {
    precondition {
      condition     = var.api_key_expiry != ""
      error_message = "api_key_expiry_reminder_enabled requires api_key_expiry (pass module.appsync.api_key_expires); a reminder with no date cannot derive its schedule."
    }
  }
}

resource "aws_cloudwatch_event_target" "api_key_expiry_reminder" {
  count = var.create && var.api_key_expiry_reminder_enabled ? 1 : 0

  rule = aws_cloudwatch_event_rule.api_key_expiry_reminder[0].name
  arn  = aws_sns_topic.ops_alerts[0].arn

  input = jsonencode({
    alarm   = "Public-orders AppSync API key expiry"
    message = "The public-orders AppSync API key (aws_appsync_api_key.public_orders) expires on ${var.api_key_expiry}. Renew it and redeploy the frontend before that date: see docs/PUBLIC_API_KEY_RUNBOOK.md. Rotation is a hard cutover — open browser tabs break until the bundle is rebuilt."
    runbook = "docs/PUBLIC_API_KEY_RUNBOOK.md"
  })
}
