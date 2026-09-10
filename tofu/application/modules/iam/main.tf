# IAM Roles Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in IAM resource names (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for IAM roles and policies"
  type        = string
}

variable "dynamodb_table_arns" {
  description = "Map of DynamoDB table ARNs used by the application"
  type        = map(string)
}

variable "exports_bucket_arn" {
  description = "ARN of the S3 bucket used for report exports"
  type        = string
}

# Restrict AppSync's Lambda invoke permissions to only the functions it needs
variable "lambda_function_arns" {
  type        = map(string)
  description = "Map of Lambda function ARNs that AppSync is permitted to invoke"
}

variable "cloudfront_distribution_arn" {
  description = "ARN of the CloudFront site distribution to scope invalidations to. When null, CloudFront invalidation permissions are omitted."
  type        = string
  default     = null
}

variable "prevent_destroy" {
  description = "Set to false for ephemeral environments that must be destroyed after use."
  type        = bool
  default     = true
}

locals {
  role_suffix         = "-${var.region_abbrev}-${var.environment}"
  dynamodb_table_arns = values(var.dynamodb_table_arns)
  dynamodb_index_arns = [for arn in values(var.dynamodb_table_arns) : "${arn}/index/*"]
  # Include both the base function ARN and the qualifier variant (versions/aliases)
  lambda_invoke_arns = flatten([for arn in values(var.lambda_function_arns) : [arn, "${arn}:*"]])
}

# =============================================================================
# Lambda Execution Role
# =============================================================================

# TODO(#75): This is a shared execution role used by every Lambda. It currently
# grants broad DynamoDB/S3 access to all functions. Hardening step: split into
# per-function roles scoped to the tables/buckets each handler actually needs.
#
# #121: Cognito admin/destructive actions (AdminDeleteUser,
# AdminResetUserPassword, AdminLinkProviderForUser, ListUsers) are isolated on
# the separate aws_iam_role.lambda_admin_execution role, assigned only to the
# admin-operations, delete-account, and pre-signup functions. The shared role
# below no longer grants any Cognito admin permissions, so a buggy or
# compromised non-admin handler cannot delete users or reset passwords.

resource "aws_iam_role" "lambda_execution" {
  name = "${var.name_prefix}-lambda-exec${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda DynamoDB Access
data "aws_iam_policy_document" "lambda_dynamodb" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = concat(local.dynamodb_table_arns, local.dynamodb_index_arns)
  }
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name   = "dynamodb-access"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_dynamodb.json
}

# Lambda S3 Access
# NOTE: S3 GetObject permission is required for Lambda functions to download reports
# from the exports bucket. This is expected behavior, not data exfiltration.
# kics-scan disable-line
data "aws_iam_policy_document" "lambda_s3" {
  statement {
    effect = "Allow"
    # kics-scan ignore-line
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [
      var.exports_bucket_arn,
      "${var.exports_bucket_arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "lambda_s3" {
  name   = "s3-access"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_s3.json
}

# Lambda CloudFront Access
# Scope invalidations to the site distribution used by the application.
# Omitted when no CloudFront distribution is configured (e.g. ephemeral environments).
data "aws_iam_policy_document" "lambda_cloudfront" {
  count = var.cloudfront_distribution_arn != null ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [var.cloudfront_distribution_arn]
  }
}

resource "aws_iam_role_policy" "lambda_cloudfront" {
  count = var.cloudfront_distribution_arn != null ? 1 : 0

  name   = "cloudfront-invalidation"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_cloudfront[0].json
}

# =============================================================================
# Lambda Admin Execution Role
# =============================================================================
#
# Separate role for the small set of Lambda handlers that perform Cognito admin
# actions (admin-operations, delete-account, pre-signup). It carries the same
# DynamoDB/S3/CloudFront access as the shared role, plus the Cognito admin
# policy attached in the cognito module (see lambda_admin_execution_role_arn).
# Isolating these destructive actions means the other ~16 functions cannot
# delete Cognito users or reset passwords even if their handler is buggy or
# compromised. See issue #121.

resource "aws_iam_role" "lambda_admin_execution" {
  name = "${var.name_prefix}-lambda-admin-exec${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

resource "aws_iam_role_policy_attachment" "lambda_admin_basic" {
  role       = aws_iam_role.lambda_admin_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_admin_dynamodb" {
  name   = "dynamodb-access"
  role   = aws_iam_role.lambda_admin_execution.id
  policy = data.aws_iam_policy_document.lambda_dynamodb.json
}

resource "aws_iam_role_policy" "lambda_admin_s3" {
  name   = "s3-access"
  role   = aws_iam_role.lambda_admin_execution.id
  policy = data.aws_iam_policy_document.lambda_s3.json
}

resource "aws_iam_role_policy" "lambda_admin_cloudfront" {
  count = var.cloudfront_distribution_arn != null ? 1 : 0

  name   = "cloudfront-invalidation"
  role   = aws_iam_role.lambda_admin_execution.id
  policy = data.aws_iam_policy_document.lambda_cloudfront[0].json
}

# =============================================================================
# Lambda Campaign Domain Execution Role (#351, chunk 1 of the #326 IAM role split)
# =============================================================================
#
# First scoped per-domain execution role, establishing the pattern the remaining
# #326 chunks reuse. Assigned to the campaign-domain handlers via the lambda
# module's domain-role map (lambda_domain_role_arns):
#   - delete-campaign-orders (handlers/campaign_operations.py)
#   - unit-reporting (handlers/campaign_reporting.py)
#
# DynamoDB scope was verified against the handler source (including the shared
# auth helpers in src/utils/auth.py):
#   - campaigns: Query on campaignId-index / unitCampaignKey-index, GetItem
#   - orders:    Query, GetItem, and BatchWriteItem deletes (order cleanup)
#   - profiles:  Query / BatchGetItem via auth helpers (owner/share checks)
#   - shares:    GetItem / BatchGetItem via auth helpers
#
# Read-only actions where the handlers only read; the single write action is
# BatchWriteItem scoped to the orders table (the boto3 resource-style
# batch_writer issues BatchWriteItem, which cannot be restricted to
# delete-only at the IAM action level). No S3, CloudFront, or Cognito
# permissions: neither handler touches those services. The monolithic shared
# role is intentionally NOT narrowed here — that is the final chunk (#355).

locals {
  campaign_table_keys = ["campaigns", "orders", "profiles", "shares"]
  campaign_table_arns = [for k in local.campaign_table_keys : var.dynamodb_table_arns[k]]
  campaign_index_arns = [for arn in local.campaign_table_arns : "${arn}/index/*"]
}

resource "aws_iam_role" "lambda_campaign_execution" {
  name = "${var.name_prefix}-lambda-campaign-exec${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

resource "aws_iam_role_policy_attachment" "lambda_campaign_basic" {
  role       = aws_iam_role.lambda_campaign_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_campaign_dynamodb" {
  # Read-only on every table the campaign handlers touch (including the auth
  # helpers' BatchGetItem), plus their GSIs.
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
    ]
    resources = concat(local.campaign_table_arns, local.campaign_index_arns)
  }

  # Order cleanup (delete-campaign-orders) uses the resource-style
  # batch_writer, which issues BatchWriteItem deletes. Scoped to the orders
  # table only.
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:BatchWriteItem"]
    resources = [var.dynamodb_table_arns["orders"]]
  }
}

resource "aws_iam_role_policy" "lambda_campaign_dynamodb" {
  name   = "dynamodb-access"
  role   = aws_iam_role.lambda_campaign_execution.id
  policy = data.aws_iam_policy_document.lambda_campaign_dynamodb.json
}

# =============================================================================
# Lambda Profile & Sharing Domain Execution Role (#352, chunk 2 of the #326 IAM role split)
# =============================================================================
#
# Second scoped per-domain execution role, reusing the wiring pattern #351
# established (the lambda module's lambda_domain_role_arns map). Assigned to
# the profile/sharing-domain handlers:
#   - list-my-shares       (handlers/profile_sharing.py)
#   - transfer-ownership   (handlers/transfer_profile_ownership.py)
#   - delete-profile-cascade (handlers/delete_profile_cascade.py)
#
# DynamoDB scope was verified against the handler source:
#   - list-my-shares:  Query on shares targetAccountId-index, BatchGetItem on
#     profiles. Read-only.
#   - transfer-ownership: Query on profiles profileId-index; TransactWriteItems
#     (Delete+Put) on profiles; GetItem/Query/UpdateItem/DeleteItem on shares.
#     is_admin() reads only the JWT claims, not DynamoDB.
#   - delete-profile-cascade: GetItem (ConsistentRead) on profiles plus
#     DeleteItem; Query + batch_writer deletes on shares, invites
#     (profileId-index), campaigns, and orders; strongly consistent GetItem
#     verification reads on campaigns/orders (shared helpers imported from
#     campaign_operations). It does NOT touch catalogs.
#
# S3 scope: delete-profile-cascade purges report exports under
# reports/<profileId>/ in the exports bucket (ListBucketVersions +
# DeleteObject/DeleteObjectVersion on that prefix only). The other two
# handlers do not touch S3. No CloudFront or Cognito permissions.
# The monolithic shared role is intentionally NOT narrowed here — that is the
# final chunk (#355).

locals {
  profile_sharing_table_keys = ["profiles", "shares", "invites", "campaigns", "orders"]
  profile_sharing_table_arns = [for k in local.profile_sharing_table_keys : var.dynamodb_table_arns[k]]
  profile_sharing_index_arns = [for arn in local.profile_sharing_table_arns : "${arn}/index/*"]

  # Tables the cascade handler's batch_writer deletes from (BatchWriteItem).
  profile_sharing_batch_write_table_arns = [
    for k in ["shares", "invites", "campaigns", "orders"] : var.dynamodb_table_arns[k]
  ]
}

resource "aws_iam_role" "lambda_profile_sharing_execution" {
  name = "${var.name_prefix}-lambda-profile-sharing-exec${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

resource "aws_iam_role_policy_attachment" "lambda_profile_sharing_basic" {
  role       = aws_iam_role.lambda_profile_sharing_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_profile_sharing_dynamodb" {
  # Read actions on every table these handlers touch, plus their GSIs.
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
    ]
    resources = concat(local.profile_sharing_table_arns, local.profile_sharing_index_arns)
  }

  # transfer-ownership rewrites the profile base-table record in a
  # transaction (the ownerAccountId hash key cannot be updated in place);
  # delete-profile-cascade deletes the profile record outright.
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:TransactWriteItems",
    ]
    resources = [var.dynamodb_table_arns["profiles"]]
  }

  # transfer-ownership updates third-party shares' ownerAccountId and deletes
  # the new owner's share after a transfer.
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
    ]
    resources = [var.dynamodb_table_arns["shares"]]
  }

  # Cascade deletes via the resource-style batch_writer, which issues
  # BatchWriteItem deletes. Scoped to exactly the tables it deletes from
  # (cannot be restricted to delete-only at the IAM action level).
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:BatchWriteItem"]
    resources = local.profile_sharing_batch_write_table_arns
  }
}

resource "aws_iam_role_policy" "lambda_profile_sharing_dynamodb" {
  name   = "dynamodb-access"
  role   = aws_iam_role.lambda_profile_sharing_execution.id
  policy = data.aws_iam_policy_document.lambda_profile_sharing_dynamodb.json
}

data "aws_iam_policy_document" "lambda_profile_sharing_s3" {
  # delete-profile-cascade purges report exports under reports/<profileId>/
  # (all versions and delete markers). Scoped to that prefix only.
  statement {
    effect    = "Allow"
    actions   = ["s3:ListBucketVersions"]
    resources = [var.exports_bucket_arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = ["${var.exports_bucket_arn}/reports/*"]
  }
}

resource "aws_iam_role_policy" "lambda_profile_sharing_s3" {
  name   = "s3-reports-cleanup"
  role   = aws_iam_role.lambda_profile_sharing_execution.id
  policy = data.aws_iam_policy_document.lambda_profile_sharing_s3.json
}

# =============================================================================
# AppSync Service Role
# =============================================================================

resource "aws_iam_role" "appsync_service" {
  name = "${var.name_prefix}-appsync${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.appsync_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

data "aws_iam_policy_document" "appsync_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["appsync.amazonaws.com"]
    }
  }
}

# AppSync DynamoDB Access
data "aws_iam_policy_document" "appsync_dynamodb" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = concat(local.dynamodb_table_arns, local.dynamodb_index_arns)
  }
}

resource "aws_iam_role_policy" "appsync_dynamodb" {
  name   = "dynamodb-access"
  role   = aws_iam_role.appsync_service.id
  policy = data.aws_iam_policy_document.appsync_dynamodb.json
}

# AppSync Lambda Invoke
# Guarded by count: when no Lambda ARNs are provided, the policy is omitted
# entirely rather than falling back to a wildcard on every Lambda in the account.
data "aws_iam_policy_document" "appsync_lambda" {
  count = length(local.lambda_invoke_arns) > 0 ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    # Principle of least privilege: limit AppSync to specific Lambda functions it calls.
    # KICS recommendation: also allow qualified ARNs (":*") for versions/aliases.
    resources = local.lambda_invoke_arns
  }
}

resource "aws_iam_role_policy" "appsync_lambda" {
  count = length(local.lambda_invoke_arns) > 0 ? 1 : 0

  name   = "lambda-invoke"
  role   = aws_iam_role.appsync_service.id
  policy = data.aws_iam_policy_document.appsync_lambda[0].json
}

# =============================================================================
# Cognito SMS Role
# =============================================================================

resource "aws_iam_role" "cognito_sms" {
  name = "${var.name_prefix}-${var.region_abbrev}-${var.environment}-UserPoolsmsRole"

  assume_role_policy = data.aws_iam_policy_document.cognito_assume_role.json

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

data "aws_iam_policy_document" "cognito_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cognito-idp.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = ["kernelworx-sms-role"]
    }
  }
}

data "aws_iam_policy_document" "cognito_sms" {
  # NOTE: Cognito uses this role to publish SMS messages directly to phone numbers
  # via SNS. There is no application-managed SNS topic, so SNS SMS requires the
  # resource to remain "*". Scoping to a topic ARN is not possible here.
  statement {
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "cognito_sms" {
  name   = "sns-publish"
  role   = aws_iam_role.cognito_sms.id
  policy = data.aws_iam_policy_document.cognito_sms.json
}

# =============================================================================
# Outputs
# =============================================================================

output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution.arn
}

output "lambda_execution_role_name" {
  description = "Name of the Lambda execution role"
  value       = aws_iam_role.lambda_execution.name
}

output "lambda_admin_execution_role_arn" {
  description = "ARN of the Lambda admin execution role (Cognito admin actions; assigned only to admin/destructive handlers)"
  value       = aws_iam_role.lambda_admin_execution.arn
}

output "lambda_admin_execution_role_name" {
  description = "Name of the Lambda admin execution role"
  value       = aws_iam_role.lambda_admin_execution.name
}

output "lambda_campaign_execution_role_arn" {
  description = "ARN of the scoped Lambda execution role for the campaign domain (delete-campaign-orders, unit-reporting). First entry of the #326 per-domain role split; see lambda_domain_role_arns in the lambda module."
  value       = aws_iam_role.lambda_campaign_execution.arn
}

output "lambda_profile_sharing_execution_role_arn" {
  description = "ARN of the scoped Lambda execution role for the profile/sharing domain (list-my-shares, transfer-ownership, delete-profile-cascade). Chunk 2 of the #326 per-domain role split; see lambda_domain_role_arns in the lambda module."
  value       = aws_iam_role.lambda_profile_sharing_execution.arn
}

output "appsync_service_role_arn" {
  description = "ARN of the AppSync service role"
  value       = aws_iam_role.appsync_service.arn
}

output "cognito_sms_role_arn" {
  description = "ARN of the Cognito SMS role"
  value       = aws_iam_role.cognito_sms.arn
  depends_on  = [aws_iam_role_policy.cognito_sms]
}
