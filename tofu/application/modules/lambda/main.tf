# Lambda Functions Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "region_abbrev" {
  description = "Short region code used in function naming (e.g., ue1)"
  type = string
}

variable "name_prefix" {
  description = "Global name prefix for Lambda resources"
  type = string
}

variable "lambda_role_arn" {
  description = "IAM role ARN assumed by the Lambda functions"
  type = string
}

variable "exports_bucket_name" {
  description = "Name of the S3 bucket used for report exports"
  type = string
}

variable "table_names" {
  description = "Map of DynamoDB table names used by the Lambdas"
  type = map(string)
}

variable "user_pool_id" {
  description = "Cognito User Pool ID passed to relevant Lambdas"
  type = string
}

variable "lambda_src_dir" {
  type        = string
  description = "Path to Lambda source code directory"
  default     = ""
}

variable "lambda_payload_dir" {
  type        = string
  description = "Path to directory for Lambda payload zip files"
  default     = ""
}

locals {
  func_suffix = "-${var.region_abbrev}-${var.environment}"
  
  # Use provided paths or default to relative paths from module
  src_dir     = var.lambda_src_dir != "" ? var.lambda_src_dir : "${path.module}/../../../../src"
  payload_dir = var.lambda_payload_dir != "" ? var.lambda_payload_dir : "${path.module}/../../../.build/lambda"
  
  common_env = {
    EXPORTS_BUCKET              = var.exports_bucket_name
    POWERTOOLS_SERVICE_NAME     = var.name_prefix
    LOG_LEVEL                   = "INFO"
    ACCOUNTS_TABLE_NAME         = var.table_names.accounts
    CATALOGS_TABLE_NAME         = var.table_names.catalogs
    PROFILES_TABLE_NAME         = var.table_names.profiles
    CAMPAIGNS_TABLE_NAME        = var.table_names.campaigns
    ORDERS_TABLE_NAME           = var.table_names.orders
    SHARES_TABLE_NAME           = var.table_names.shares
    INVITES_TABLE_NAME          = var.table_names.invites
    SHARED_CAMPAIGNS_TABLE_NAME = var.table_names.shared_campaigns
  }
  
  # Lambda functions configuration
  functions = {
    "list-my-shares" = {
      handler     = "handlers.profile_sharing.list_my_shares"
      timeout     = 30
      memory_size = 256
    }
    "list-catalogs-in-use" = {
      handler     = "handlers.list_catalogs_in_use.handler"
      timeout     = 30
      memory_size = 256
    }
    "create-profile" = {
      handler     = "handlers.scout_operations.create_seller_profile"
      timeout     = 30
      memory_size = 256
    }
    "request-report" = {
      handler     = "handlers.report_generation.request_campaign_report"
      timeout     = 60
      memory_size = 512
    }
    "unit-reporting" = {
      handler     = "handlers.campaign_reporting.get_unit_report"
      timeout     = 60
      memory_size = 512
    }
    "list-unit-catalogs" = {
      handler     = "handlers.list_unit_catalogs.list_unit_catalogs"
      timeout     = 30
      memory_size = 512
    }
    "list-unit-campaign-catalogs" = {
      handler     = "handlers.list_unit_catalogs.list_unit_campaign_catalogs"
      timeout     = 30
      memory_size = 512
    }
    "campaign-operations" = {
      handler     = "handlers.campaign_operations.create_campaign"
      timeout     = 30
      memory_size = 512
    }
    "delete-profile-orders-cascade" = {
      handler     = "handlers.delete_profile_orders_cascade.lambda_handler"
      timeout     = 60
      memory_size = 512
    }
    "update-account" = {
      handler     = "handlers.account_operations.update_my_account"
      timeout     = 10
      memory_size = 256
    }
    "delete-account" = {
      handler     = "handlers.account_operations.delete_my_account"
      timeout     = 30
      memory_size = 256
    }
    "transfer-ownership" = {
      handler     = "handlers.transfer_profile_ownership.lambda_handler"
      timeout     = 10
      memory_size = 256
    }
    "post-auth" = {
      # DLQ intentionally not configured for Cognito Post Authentication trigger.
      # Cognito invokes this synchronously and handles retries; introducing a DLQ adds
      # unnecessary cost/complexity without operational benefit for this flow.
      handler     = "handlers.post_authentication.lambda_handler"
      timeout     = 10
      memory_size = 256
    }
    "pre-signup" = {
      # DLQ intentionally not configured for Cognito Pre Sign-Up trigger.
      # Cognito manages retries for this trigger; failures are surfaced to the client
      # and are not suitable for asynchronous reprocessing via a DLQ.
      handler     = "handlers.pre_signup.lambda_handler"
      timeout     = 10
      memory_size = 256
    }
    "request-qr-upload" = {
      handler     = "handlers.payment_methods_handlers.request_qr_upload"
      timeout     = 10
      memory_size = 256
    }
    "confirm-qr-upload" = {
      handler     = "handlers.payment_methods_handlers.confirm_qr_upload"
      timeout     = 10
      memory_size = 256
    }
    "generate-qr-code-presigned-url" = {
      handler     = "handlers.generate_qr_code_presigned_url.generate_qr_code_presigned_url"
      timeout     = 3
      memory_size = 128
    }
    "delete-qr-code" = {
      handler     = "handlers.payment_methods_handlers.delete_qr_code"
      timeout     = 10
      memory_size = 256
    }
    "validate-payment-method" = {
      handler     = "handlers.validate_payment_method.lambda_handler"
      timeout     = 10
      memory_size = 256
    }
    "admin-operations" = {
      handler     = "handlers.admin_operations.lambda_handler"
      timeout     = 30
      memory_size = 256
      extra_env = {
        USER_POOL_ID = var.user_pool_id
      }
    }
  }
}

# Note: Lambda layer and functions would be created here
# For now, we're importing existing functions

# Archive the Lambda source code
data "archive_file" "lambda_payload" {
  type        = "zip"
  source_dir  = local.src_dir
  excludes    = [
    "venv",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache"
  ]
  output_path = "${local.payload_dir}/lambda_payload.zip"
}

# Lambda Layer - Archive dependencies from .venv
data "archive_file" "lambda_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../../../../.build/lambda-layer"
  output_path = "${local.payload_dir}/lambda_layer.zip"
  excludes = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.dist-info",
    "*.egg-info"
  ]
}

resource "aws_lambda_layer_version" "shared" {
  layer_name               = "${var.name_prefix}-deps-${var.region_abbrev}-${var.environment}"
  compatible_runtimes      = ["python3.14"]
  compatible_architectures = ["arm64"]
  description              = "Shared Python dependencies for Lambda functions"
  
  # Archive gets regenerated every time (cheap), but layer only updates when lock file changes
  filename         = data.archive_file.lambda_layer.output_path
  source_code_hash = filebase64sha256("${path.module}/../../../../uv.lock")
}

# Lambda Functions
# kics-scan ignore-line
resource "aws_lambda_function" "functions" {
  for_each = local.functions

  function_name = "${var.name_prefix}-${each.key}${local.func_suffix}"
  role          = var.lambda_role_arn
  handler       = each.value.handler
  runtime       = "python3.14"
  architectures = ["arm64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory_size

  filename         = data.archive_file.lambda_payload.output_path
  source_code_hash = data.archive_file.lambda_payload.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = merge(local.common_env, lookup(each.value, "extra_env", {}))
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Outputs
output "function_arns" {
  description = "Map of Lambda function names to their ARNs"
  value       = { for k, v in aws_lambda_function.functions : k => v.arn }
}

output "function_names" {
  description = "Map of Lambda function logical names to their function names"
  value       = { for k, v in aws_lambda_function.functions : k => v.function_name }
}

output "layer_arn" {
  description = "ARN of the shared Lambda layer"
  value       = aws_lambda_layer_version.shared.arn
}
