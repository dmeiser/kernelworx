# AppSync Module Variables

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in API naming (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for AppSync resources"
  type        = string
}

variable "api_domain" {
  description = "Fully qualified API domain (e.g., api.dev.kernelworx.app or api.kernelworx.app). When null, no custom domain is created and the AWS-managed AppSync URL is used."
  type        = string
  default     = null
}

variable "api_certificate_arn" {
  description = "ACM certificate ARN for the AppSync custom domain. Required when api_domain is set."
  type        = string
  default     = null
}

variable "certificate_validation" {
  description = "Certificate validation resource to ensure certificate is valid before use"
  type        = any
  default     = null
}

variable "appsync_service_role_arn" {
  description = "IAM role ARN used by AppSync to access data sources"
  type        = string
}

variable "dynamodb_table_names" {
  type        = map(string)
  description = "Map of logical names to DynamoDB table names"
}

variable "lambda_function_arns" {
  type        = map(string)
  description = "Map of Lambda function names to ARNs"
}

variable "user_pool_id" {
  type        = string
  description = "Cognito User Pool ID for AppSync authentication"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "prevent_destroy" {
  description = "Set to false for ephemeral environments that must be destroyed after use."
  type        = bool
  default     = true
}

locals {
  api_name   = "${var.name_prefix}-api-${var.region_abbrev}-${var.environment}"
  api_domain = var.api_domain
  # AppSync function names cannot contain hyphens, so sanitize the environment
  # identifier while keeping it readable.
  env_suffix = "_${replace(var.environment, "-", "_")}"

  # JS resolver code path
  js_resolvers_dir      = "${path.module}/../../appsync/js-resolvers"
  mapping_templates_dir = "${path.module}/../../appsync/mapping-templates"
}
