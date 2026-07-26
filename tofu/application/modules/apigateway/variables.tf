# REST API Gateway Module Variables

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in API naming (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for API Gateway resources"
  type        = string
}

variable "api_domain" {
  description = "Fully qualified API domain (e.g., api.dev.kernelworx.app)"
  type        = string
}

variable "api_certificate_arn" {
  description = "ACM certificate ARN for the API Gateway custom domain"
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
  description = "Cognito User Pool ID for API Gateway Cognito Authorizer"
}

variable "user_pool_arn" {
  type        = string
  description = "Cognito User Pool ARN for the native API Gateway Cognito JWT authorizer"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
}


