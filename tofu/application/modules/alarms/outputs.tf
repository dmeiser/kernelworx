# Alarms module outputs

output "ops_alert_topic_arn" {
  description = "ARN of the ops alert SNS topic every alarm in this environment notifies"
  value       = var.create ? aws_sns_topic.ops_alerts[0].arn : ""
}

output "appsync_4xx_alarm_arn" {
  description = "ARN of the AppSync 4xx/throttle alarm"
  value       = var.create ? aws_cloudwatch_metric_alarm.appsync_4xx[0].arn : ""
}

output "ses_reputation_alarm_arns" {
  description = "ARNs of the SES reputation alarms (empty outside prod)"
  value = var.create && var.ses_reputation_enabled ? [
    aws_cloudwatch_metric_alarm.ses_bounce_rate[0].arn,
    aws_cloudwatch_metric_alarm.ses_complaint_rate[0].arn,
  ] : []
}

output "api_key_expiry_reminder_rule_arn" {
  description = "ARN of the scheduled public-orders API-key expiry reminder rule (empty outside prod)"
  value       = var.create && var.api_key_expiry_reminder_enabled ? aws_cloudwatch_event_rule.api_key_expiry_reminder[0].arn : ""
}
