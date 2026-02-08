# Development Budget Outputs

output "budget_name" {
  description = "Name of the development budget"
  value       = module.budget.budget_name
}

output "anomaly_monitor_arn" {
  description = "ARN of the anomaly detection monitor"
  value       = module.budget.anomaly_monitor_arn
}

output "anomaly_subscription_arn" {
  description = "ARN of the anomaly alert subscription"
  value       = module.budget.anomaly_subscription_arn
}
