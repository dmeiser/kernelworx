# Alarms module variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod)"
  type        = string
}

variable "create" {
  description = "Whether to create any alarm resources (false = opt out; ephemeral environments do not instantiate this module at all)"
  type        = bool
  default     = true
}

variable "appsync_api_id" {
  description = "AppSync GraphQL API ID whose 4XXError metric the public-surface alarm watches"
  type        = string
}

variable "alert_email" {
  description = "Ops address that receives alarm notifications (the same address the bootstrap cost budgets notify). The SNS email subscription must be confirmed once, out of band, before any notification is delivered."
  type        = string
}

variable "appsync_4xx_threshold" {
  description = "Alarm when the sum of AppSync 4XXError over appsync_4xx_period_seconds reaches this count. Above organic bad-token noise, below flood volume, and low enough that day-zero API-key expiry (every public call answering Unauthorized) trips it."
  type        = number
  default     = 100
}

variable "appsync_4xx_period_seconds" {
  description = "Aggregation window for the AppSync 4XXError alarm"
  type        = number
  default     = 300
}

variable "public_abuse_period_seconds" {
  description = "Aggregation window shared by the public-abuse metric-filter alarms (token mismatch and cap rejection)"
  type        = number
  default     = 300
}

variable "public_token_mismatch_threshold" {
  description = "Alarm when publicCreateOrder share-token mismatches reach this count in public_abuse_period_seconds. A legitimate buyer never mismatches (the token travels in their own URL), so sustained mismatches are a probe flood. Chosen below flood volume but above a single careless retry burst."
  type        = number
  default     = 20
}

variable "public_cap_rejection_threshold" {
  description = "Alarm when publicCreateOrder cap/throttle rejections reach this count in public_abuse_period_seconds. Set above what an organic sell-out burst (the campaign's last few orders racing the cap) can produce, below a deliberate order flood."
  type        = number
  default     = 10
}

variable "ses_reputation_enabled" {
  description = "Whether to create the SES reputation alarms. Prod only: SES reputation and suppression are account-level, and the account whose sending reputation matters for real buyers is the prod account."
  type        = bool
  default     = false
}

variable "ses_bounce_rate_threshold" {
  description = "Alarm when the average SES hard-bounce rate (percent) over one hour reaches this. 5% is the account-level threshold above which SES begins to restrict sending."
  type        = number
  default     = 5.0
}

variable "ses_complaint_rate_threshold" {
  description = "Alarm when the average SES complaint rate (percent) over one hour reaches this. 0.1% is the account-level threshold above which SES begins to restrict sending."
  type        = number
  default     = 0.1
}

variable "api_key_expiry_reminder_enabled" {
  description = "Whether to create the scheduled public-orders API-key expiry reminder. Prod only (the spec's ExpiredAPIKeys alarm): the `expires` literal is one module-level value shared by every environment, so one named reminder covers the whole fleet."
  type        = bool
  default     = false
}

variable "api_key_expiry" {
  description = "The aws_appsync_api_key.public_orders `expires` value (module.appsync.api_key_expires). The reminder date is derived from it, so renewing the key moves the reminder automatically — there is no second date to keep in sync."
  type        = string
  default     = ""
}
