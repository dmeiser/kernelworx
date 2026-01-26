# Budget Module Outputs

output "budget_name" {
  description = "Name of the created budget"
  value       = aws_budgets_budget.monthly.name
}

output "anomaly_monitor_arn" {
  description = "ARN of the anomaly detection monitor"
  value       = var.existing_monitor_arn
}

output "anomaly_subscription_arn" {
  description = "ARN of the anomaly alert subscription"
  value       = aws_ce_anomaly_subscription.alerts.arn
}
