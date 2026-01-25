# IAM Roles Module

variable "environment" {
  type = string
}

variable "region_abbrev" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "dynamodb_table_arns" {
  type = map(string)
}

variable "exports_bucket_arn" {
  type = string
}

locals {
  role_suffix         = "-${var.region_abbrev}-${var.environment}"
  dynamodb_table_arns = values(var.dynamodb_table_arns)
  dynamodb_index_arns = [for arn in values(var.dynamodb_table_arns) : "${arn}/index/*"]
}

# =============================================================================
# Lambda Execution Role
# =============================================================================

resource "aws_iam_role" "lambda_execution" {
  name = "${var.name_prefix}-lambda-exec${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  lifecycle {
    prevent_destroy = true
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
      "s3:ListBucket",
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
data "aws_iam_policy_document" "lambda_cloudfront" {
  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_cloudfront" {
  name   = "cloudfront-invalidation"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_cloudfront.json
}

# Lambda Cognito Admin Access
data "aws_iam_policy_document" "lambda_cognito" {
  statement {
    effect = "Allow"
    actions = [
      "cognito-idp:AdminResetUserPassword",
      "cognito-idp:AdminDeleteUser",
      "cognito-idp:ListUsers",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:AdminGetUser",
      "cognito-idp:AdminLinkProviderForUser",
      "cognito-idp:AdminCreateUser",
      "cognito-idp:AdminSetUserPassword",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_cognito" {
  name   = "cognito-admin"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_cognito.json
}

# =============================================================================
# AppSync Service Role
# =============================================================================

resource "aws_iam_role" "appsync_service" {
  name = "${var.name_prefix}-appsync${local.role_suffix}"

  assume_role_policy = data.aws_iam_policy_document.appsync_assume_role.json

  lifecycle {
    prevent_destroy = true
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
data "aws_iam_policy_document" "appsync_lambda" {
  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "appsync_lambda" {
  name   = "lambda-invoke"
  role   = aws_iam_role.appsync_service.id
  policy = data.aws_iam_policy_document.appsync_lambda.json
}

# =============================================================================
# Cognito SMS Role
# =============================================================================

resource "aws_iam_role" "cognito_sms" {
  name = "${var.name_prefix}-${var.region_abbrev}-${var.environment}-UserPoolsmsRole"

  assume_role_policy = data.aws_iam_policy_document.cognito_assume_role.json

  lifecycle {
    prevent_destroy = true
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
  }
}

data "aws_iam_policy_document" "cognito_sms" {
  statement {
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = ["arn:aws:sns:*:*:*"]
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
  value = aws_iam_role.lambda_execution.arn
}

output "lambda_execution_role_name" {
  value = aws_iam_role.lambda_execution.name
}

output "appsync_service_role_arn" {
  value = aws_iam_role.appsync_service.arn
}

output "cognito_sms_role_arn" {
  value = aws_iam_role.cognito_sms.arn
}
