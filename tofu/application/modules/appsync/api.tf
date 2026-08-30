# AppSync GraphQL API and Domain

# AppSync GraphQL API
resource "aws_appsync_graphql_api" "main" {
  name                = local.api_name
  authentication_type = "AMAZON_COGNITO_USER_POOLS"

  user_pool_config {
    aws_region     = var.aws_region
    default_action = "ALLOW"
    user_pool_id   = var.user_pool_id
  }

  # Authorization posture: AppSync admits any authenticated Cognito user by default.
  # Owner/share/admin authorization lives entirely in resolvers, not in schema-level
  # directives. See AGENTS.md ## AppSync resolver-only authorization posture (#71).

  # Only Amazon Cognito User Pools authentication is used by the frontend.
  # AppSync service roles for DynamoDB/Lambda data sources are configured
  # separately as IAM assume-role policies; they are not additional auth providers.

  xray_enabled = false

  log_config {
    cloudwatch_logs_role_arn = aws_iam_role.appsync_logging.arn
    field_log_level          = "ERROR"
    exclude_verbose_content  = true
  }

  # Schema loaded from file
  schema = file("${path.module}/../../schema/schema.graphql")

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# AppSync-managed CloudWatch log group with explicit retention.
resource "aws_cloudwatch_log_group" "appsync" {
  name              = "/aws/appsync/apis/${aws_appsync_graphql_api.main.id}"
  retention_in_days = var.environment == "prod" ? 30 : 7

}

# IAM role that permits AppSync to publish logs for this API.
data "aws_iam_policy_document" "appsync_logging_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["appsync.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "appsync_logging" {
  name               = "${local.api_name}-logs"
  assume_role_policy = data.aws_iam_policy_document.appsync_logging_assume_role.json
}

data "aws_iam_policy_document" "appsync_logging" {
  # CreateLogGroup does not support resource-level permissions.
  statement {
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
    ]

    resources = ["*"]
  }

  # Scope stream and event actions to the managed log group and its streams.
  statement {
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      aws_cloudwatch_log_group.appsync.arn,
      "${aws_cloudwatch_log_group.appsync.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "appsync_logging" {
  name   = "appsync-logging"
  role   = aws_iam_role.appsync_logging.id
  policy = data.aws_iam_policy_document.appsync_logging.json
}

# AppSync Custom Domain (optional - omitted for ephemeral environments)
resource "aws_appsync_domain_name" "api" {
  count = var.api_domain != null ? 1 : 0

  domain_name     = var.api_domain
  certificate_arn = var.api_certificate_arn

  lifecycle {
    precondition {
      condition     = var.api_certificate_arn != null
      error_message = "api_certificate_arn is required when api_domain is set"
    }
    precondition {
      # When a validation resource is supplied, ensure it has completed before
      # creating the custom domain. Dev builds omit validation entirely.
      condition     = var.certificate_validation == null ? true : try(length(var.certificate_validation.validation_record_fqdns) > 0, false)
      error_message = "Certificate validation must complete before creating AppSync domain"
    }
  }
}

resource "aws_appsync_domain_name_api_association" "api" {
  count = var.api_domain != null ? 1 : 0

  api_id      = aws_appsync_graphql_api.main.id
  domain_name = aws_appsync_domain_name.api[0].domain_name
}
