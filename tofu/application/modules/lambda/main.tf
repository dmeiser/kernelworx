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

variable "cognito_client_id" {
  description = "Cognito User Pool client ID passed to auth Lambdas"
  type = string
}

variable "cognito_domain" {
  description = "Cognito User Pool custom domain passed to auth Lambdas"
  type = string
}

variable "site_domain" {
  description = "Public site domain used by Lambdas for callbacks and links"
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
    SITE_DOMAIN                 = var.site_domain
  }

  # Domain Lambdas: one per domain, each routes internally by HTTP method + path
  # via the `handler` entrypoint (API Gateway AWS_PROXY event shape). Mirrors the
  # routing in tests/e2e/test_server.py.
  domain_functions = {
    "auth" = {
      handler     = "handlers.auth_domain.handler"
      timeout     = 30
      memory_size = 256
      extra_env = {
        COGNITO_CLIENT_ID = var.cognito_client_id
        COGNITO_DOMAIN    = var.cognito_domain
      }
    }
    "scouts" = {
      handler     = "handlers.scouts_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "campaigns" = {
      handler     = "handlers.campaigns_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "orders" = {
      handler     = "handlers.orders_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "catalogs" = {
      handler     = "handlers.catalogs_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "payment-methods" = {
      handler     = "handlers.payment_methods_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "sharing" = {
      handler     = "handlers.sharing_domain.handler"
      timeout     = 30
      memory_size = 256
    }
    "admin" = {
      handler     = "handlers.admin_domain.handler"
      timeout     = 30
      memory_size = 256
    }
  }

  # Restored business-logic handlers adapted to the proxy event shape. Each has
  # its own `handler` entrypoint that routes its dedicated API path.
  app_functions = {
    "account-operations" = {
      handler     = "handlers.account_operations.handler"
      timeout     = 30
      memory_size = 256
      extra_env = {
        USER_POOL_ID = var.user_pool_id
      }
    }
    "transfer-ownership" = {
      handler     = "handlers.transfer_profile_ownership.handler"
      timeout     = 10
      memory_size = 256
    }
    "delete-profile-cascade" = {
      handler     = "handlers.delete_profile_cascade.handler"
      timeout     = 60
      memory_size = 512
    }
    "validate-payment-method" = {
      handler     = "handlers.validate_payment_method.handler"
      timeout     = 10
      memory_size = 256
    }
    "list-catalogs-in-use" = {
      handler     = "handlers.list_catalogs_in_use.handler"
      timeout     = 30
      memory_size = 256
    }
    "list-unit-catalogs" = {
      handler     = "handlers.list_unit_catalogs.handler"
      timeout     = 30
      memory_size = 512
    }
    "generate-qr-presigned-url" = {
      handler     = "handlers.generate_qr_code_presigned_url.handler"
      timeout     = 10
      memory_size = 256
    }
  }

  # Cognito trigger functions are kept separate to avoid module-level dependency
  # cycles. These functions have no extra_env and do not reference var.user_pool_id,
  # so their ARNs can be passed to the cognito module without creating a cycle.
  trigger_functions = {
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
  
  # Archive gets regenerated every time (cheap), but layer only updates when the
  # layer zip content changes. Hash must reflect the actual layer archive, not uv.lock.
  filename         = data.archive_file.lambda_layer.output_path
  source_code_hash = filebase64sha256(data.archive_file.lambda_layer.output_path)
}

# Cognito trigger functions (post-auth, pre-signup) - separate resource block so
# their ARNs can be referenced by the cognito module without creating a cycle.
# These functions must NOT reference var.user_pool_id (directly or via extra_env).
# kics-scan ignore-line
resource "aws_lambda_function" "trigger_functions" {
  for_each = local.trigger_functions

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
    variables = local.common_env
  }

  lifecycle {
    prevent_destroy = false
  }
}

# State migration: post-auth and pre-signup were previously part of the
# legacy aws_lambda_function.functions resource (now removed). No moved block
# is needed because the resource address changed entirely during the redesign
# (old functions map was stale and referenced deleted handlers).

# App functions (domain + restored business-logic). These may depend on
# var.user_pool_id via extra_env, so they are separate from the trigger
# functions to keep the cognito module free of dependency cycles.
# kics-scan ignore-line
resource "aws_lambda_function" "domain_functions" {
  for_each = local.domain_functions

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
    prevent_destroy = false
  }
}

# kics-scan ignore-line
resource "aws_lambda_function" "app_functions" {
  for_each = local.app_functions

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
    prevent_destroy = false
  }
}

# kics-scan ignore-line
resource "aws_lambda_function" "authorizer" {
  function_name = "${var.name_prefix}-authorizer${local.func_suffix}"
  role          = var.lambda_role_arn
  handler       = "handlers.authorizer.handler"
  runtime       = "python3.14"
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 256

  filename         = data.archive_file.lambda_payload.output_path
  source_code_hash = data.archive_file.lambda_payload.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = local.common_env
  }

  lifecycle {
    prevent_destroy = false
  }
}

# Outputs
output "function_arns" {
  description = "Map of all app Lambda function logical names (domain + restored) to their ARNs, keyed by logical name for the apigateway module"
  value = merge(
    { for k, v in aws_lambda_function.domain_functions : k => v.arn },
    { for k, v in aws_lambda_function.app_functions : k => v.arn },
  )
}

output "function_names" {
  description = "Map of all app Lambda function logical names (domain + restored) to their function names"
  value = merge(
    { for k, v in aws_lambda_function.domain_functions : k => v.function_name },
    { for k, v in aws_lambda_function.app_functions : k => v.function_name },
  )
}

output "trigger_function_arns" {
  description = "Map of Cognito trigger Lambda function names to their ARNs (no user_pool_id dependency)"
  value       = { for k, v in aws_lambda_function.trigger_functions : k => v.arn }
}

output "authorizer_arn" {
  description = "ARN of the API Gateway custom authorizer Lambda"
  value       = aws_lambda_function.authorizer.arn
}

output "layer_arn" {
  description = "ARN of the shared Lambda layer"
  value       = aws_lambda_layer_version.shared.arn
}
