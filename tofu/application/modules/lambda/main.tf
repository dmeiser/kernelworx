# Lambda Functions Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in function naming (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for Lambda resources"
  type        = string
}

variable "lambda_admin_role_arn" {
  description = "IAM role ARN for the small set of handlers that perform Cognito admin/destructive actions (admin-operations, delete-account, pre-signup). When null, those functions must have entries in lambda_domain_role_arns like every other function. See issue #121."
  type        = string
  default     = null
}

# #326 IAM role split (completed by #355): map of Lambda function key (app or
# Cognito trigger) to a scoped per-domain execution role ARN. This is the
# reusable wiring mechanism for the per-domain roles created in the iam
# module — each chunk added its domain role as a new iam-module output plus
# entries here mapping its function keys to that ARN. The monolithic shared
# role was retired in #355, so EVERY non-admin function must have an entry;
# the resolution locals below index this map directly and a missing entry
# fails the plan loudly instead of silently falling back to a broad role.
# The admin role (when set) still takes precedence for admin handlers.
variable "lambda_domain_role_arns" {
  description = "Map of Lambda function key (app or trigger) to a scoped per-domain Lambda execution role ARN (#326 IAM role split). Every non-admin function must have an entry; the admin role still wins for admin handlers."
  type        = map(string)
  default     = {}
}

variable "exports_bucket_name" {
  description = "Name of the S3 bucket used for report exports"
  type        = string
}

variable "table_names" {
  description = "Map of DynamoDB table names used by the Lambdas"
  type        = map(string)
}

variable "user_pool_id" {
  description = "Cognito User Pool ID passed to relevant Lambdas"
  type        = string
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
    "list-catalogs-in-use" = {
      handler     = "handlers.list_catalogs_in_use.handler"
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
    "delete-campaign-orders" = {
      handler     = "handlers.campaign_operations.delete_campaign_orders"
      timeout     = 60
      memory_size = 512
    }
    "delete-profile-cascade" = {
      handler     = "handlers.delete_profile_cascade.lambda_handler"
      timeout     = 60
      memory_size = 512
    }
    "delete-account" = {
      handler     = "handlers.account_operations.delete_my_account"
      timeout     = 30
      memory_size = 256
      extra_env = {
        USER_POOL_ID = var.user_pool_id
      }
    }
    "transfer-ownership" = {
      handler     = "handlers.transfer_profile_ownership.lambda_handler"
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
      timeout     = 10
      memory_size = 128
    }
    "delete-qr-code" = {
      handler     = "handlers.payment_methods_handlers.delete_qr_code"
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

  # Functions that perform Cognito admin/destructive actions and therefore use
  # the isolated admin execution role when lambda_admin_role_arn is set (#121).
  # pre-signup uses AdminLinkProviderForUser; admin-operations uses AdminDeleteUser
  # / AdminResetUserPassword / ListUsers; delete-account uses AdminDeleteUser.
  admin_function_keys = ["admin-operations", "delete-account"]
  admin_trigger_keys  = ["pre-signup"]
}

# Role resolution per function, in precedence order:
#   1. Admin role (#121) when configured and the function is an admin handler
#      or Cognito admin trigger (pre-signup).
#   2. Domain role (#326) via var.lambda_domain_role_arns. Every other
#      function MUST have an entry — the monolithic shared role was retired
#      in #355, so the direct map index fails the plan loudly when an entry
#      is missing rather than silently falling back to a broad role.
locals {
  app_role_arn = {
    for k in keys(local.functions) :
    k => (var.lambda_admin_role_arn != null && contains(local.admin_function_keys, k) ? var.lambda_admin_role_arn : var.lambda_domain_role_arns[k])
  }
  trigger_role_arn = {
    for k in keys(local.trigger_functions) :
    k => (var.lambda_admin_role_arn != null && contains(local.admin_trigger_keys, k) ? var.lambda_admin_role_arn : var.lambda_domain_role_arns[k])
  }
}

# Note: Lambda layer and functions would be created here
# For now, we're importing existing functions

# Archive the Lambda source code
data "archive_file" "lambda_payload" {
  type       = "zip"
  source_dir = local.src_dir
  excludes = [
    "venv",
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
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
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
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
  role          = local.trigger_role_arn[each.key]
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
}

# State migration: post-auth and pre-signup were previously part of
# aws_lambda_function.functions and are now in aws_lambda_function.trigger_functions.
moved {
  from = aws_lambda_function.functions["post-auth"]
  to   = aws_lambda_function.trigger_functions["post-auth"]
}

moved {
  from = aws_lambda_function.functions["pre-signup"]
  to   = aws_lambda_function.trigger_functions["pre-signup"]
}

# App functions (all functions that may depend on var.user_pool_id via extra_env)
# kics-scan ignore-line
resource "aws_lambda_function" "functions" {
  for_each = local.functions

  function_name = "${var.name_prefix}-${each.key}${local.func_suffix}"
  role          = local.app_role_arn[each.key]
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
}

# Managed log groups for Lambda functions so retention is not "never expire".
# These adopt the names Lambda auto-creates on first invocation; existing groups
# must be imported into state before the first apply. for_each uses the local
# function maps so the instance keys are known during planning even when the
# Lambda functions themselves have not been created or imported yet.
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.functions

  name = "/aws/lambda/${var.name_prefix}-${each.key}${local.func_suffix}"
  # kics-scan ignore-line -- retention IS set dynamically below; KICS only matches static values
  retention_in_days = var.environment == "prod" ? 30 : 7
}

resource "aws_cloudwatch_log_group" "trigger_functions" {
  for_each = local.trigger_functions

  name = "/aws/lambda/${var.name_prefix}-${each.key}${local.func_suffix}"
  # kics-scan ignore-line -- retention IS set dynamically below; KICS only matches static values
  retention_in_days = var.environment == "prod" ? 30 : 7
}

# Outputs
output "function_arns" {
  description = "Map of app Lambda function logical names to their ARNs (AppSync-invokable only; excludes Cognito trigger functions to avoid over-broad IAM invoke permissions)"
  value       = { for k, v in aws_lambda_function.functions : k => v.arn }
}

output "function_names" {
  description = "Map of app Lambda function logical names to their function names (AppSync-invokable only; excludes Cognito trigger functions)"
  value       = { for k, v in aws_lambda_function.functions : k => v.function_name }
}

output "trigger_function_arns" {
  description = "Map of Cognito trigger Lambda function names to their ARNs (no user_pool_id dependency)"
  value       = { for k, v in aws_lambda_function.trigger_functions : k => v.arn }
}

output "layer_arn" {
  description = "ARN of the shared Lambda layer"
  value       = aws_lambda_layer_version.shared.arn
}


