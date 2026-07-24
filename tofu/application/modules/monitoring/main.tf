# Monitoring Module
# Minimum viable CloudWatch alarms + SNS notifications for the KernelWorx application.

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in resource naming (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for monitoring resources"
  type        = string
}

variable "alarm_email" {
  description = "Email address to receive CloudWatch alarm notifications"
  type        = string
  sensitive   = true
}

variable "lambda_function_names" {
  description = "Map of Lambda function logical names to function names to alarm on"
  type        = map(string)
}

variable "appsync_api_id" {
  description = "AppSync GraphQL API ID"
  type        = string
}

variable "dynamodb_table_names" {
  description = "Map of DynamoDB table logical names to table names to alarm on"
  type        = map(string)
}

locals {
  suffix = "-${var.region_abbrev}-${var.environment}"
}

# =============================================================================
# Notification channel
# =============================================================================

resource "aws_sns_topic" "alarms" {
  name         = "${var.name_prefix}-alarms${local.suffix}"
  display_name = "KernelWorx ${var.environment} alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# =============================================================================
# Lambda alarms
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = var.lambda_function_names

  alarm_name          = "${var.name_prefix}-lambda-errors-${each.key}${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Errors detected on Lambda function ${each.value}"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each = var.lambda_function_names

  alarm_name          = "${var.name_prefix}-lambda-throttles-${each.key}${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Throttles detected on Lambda function ${each.value}"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# =============================================================================
# AppSync alarms
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "appsync_5xx" {
  alarm_name          = "${var.name_prefix}-appsync-5xx${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "5XXError"
  namespace           = "AWS/AppSync"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "5xx errors detected on AppSync GraphQL API ${var.appsync_api_id}"

  dimensions = {
    GraphQLAPIId = var.appsync_api_id
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# =============================================================================
# DynamoDB alarms
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "dynamodb_system_errors" {
  for_each = var.dynamodb_table_names

  alarm_name          = "${var.name_prefix}-dynamodb-system-errors-${each.key}${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "SystemErrors"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "System errors detected on DynamoDB table ${each.value}"

  dimensions = {
    TableName = each.value
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# =============================================================================
# Outputs
# =============================================================================

output "sns_topic_arn" {
  description = "ARN of the SNS topic used for alarm notifications"
  value       = aws_sns_topic.alarms.arn
}
