# AppSync Module Variables

variable "environment" {
  type = string
}

variable "region_abbrev" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "domain" {
  type = string
}

variable "api_certificate_arn" {
  type = string
}

variable "appsync_service_role_arn" {
  type = string
}

variable "dynamodb_table_arns" {
  type        = map(string)
  description = "Map of DynamoDB table names to ARNs"
}

variable "dynamodb_table_names" {
  type        = map(string)
  description = "Map of logical names to DynamoDB table names"
}

variable "lambda_function_arns" {
  type        = map(string)
  description = "Map of Lambda function names to ARNs"
}

variable "lambda_function_names" {
  type        = map(string)
  description = "Map of logical names to Lambda function names"
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
