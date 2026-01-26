# Budget Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "budget_name" {
  description = "Name of the budget"
  type        = string
}

variable "limit_amount" {
  description = "Monthly spending limit in USD"
  type        = string
  default     = "10.0"
}

variable "account_id" {
  description = "AWS account ID to monitor"
  type        = string
}

variable "alert_emails" {
  description = "List of email addresses for budget alerts"
  type        = list(string)
}

variable "primary_alert_email" {
  description = "Primary email for anomaly detection alerts"
  type        = string
}

variable "existing_monitor_arn" {
  description = "ARN of existing anomaly monitor to use"
  type        = string
}
