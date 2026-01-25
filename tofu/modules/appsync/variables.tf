# AppSync Module Variables

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "region_abbrev" {
  description = "Short region code used in API naming (e.g., ue1)"
  type = string
}

variable "name_prefix" {
  description = "Global name prefix for AppSync resources"
  type = string
}

variable "domain" {
  description = "Base domain used to build the AppSync API hostname"
  type = string
}

variable "api_certificate_arn" {
  description = "ACM certificate ARN for the AppSync custom domain"
  type = string
}

variable "appsync_service_role_arn" {
  description = "IAM role ARN used by AppSync to access data sources"
  type = string
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

locals {
  api_name   = "${var.name_prefix}-api-${var.region_abbrev}-${var.environment}"
  api_domain = "api.${var.environment}.${var.domain}"
  env_suffix = "_${var.environment}"
  
  # JS resolver code path
  js_resolvers_dir     = "${path.module}/../../appsync/js-resolvers"
  mapping_templates_dir = "${path.module}/../../appsync/mapping-templates"
}
