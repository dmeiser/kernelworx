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

  # The public order surface (KW-PUBLIC-ORDERS) adds API_KEY as an ADDITIONAL mode:
  # Cognito stays the PRIMARY/default mode, and the schema's @aws_api_key directives
  # are what confine an API-key caller to the public fields and types. The block
  # accepts only authentication_type (plus openid_connect_config / user_pool_config /
  # lambda_authorizer_config) - the key's description and expires live on the
  # separate aws_appsync_api_key resource below; there is no api_key_config block in
  # the provider schema. Verified against `tofu providers schema -json`.
  additional_authentication_provider {
    authentication_type = "API_KEY"
  }

  # AppSync service roles for DynamoDB/Lambda data sources are configured
  # separately as IAM assume-role policies; they are not additional auth providers.

  xray_enabled = false

  # Query depth / resolver count limits (issue #328). Measured basis:
  # - Deepest legitimate frontend query is GetUnitReport:
  #   getUnitReport -> sellers -> orders -> lineItems -> scalar = depth 5
  #   (root field counts as level 1). The schema's theoretical maximum is 6.
  #   query_depth_limit = 10 gives ~2x headroom over both.
  # - Worst-case legitimate resolver fan-out is ListMyProfiles (frontend sends
  #   no limit): 1 query resolver + 5 per-item field resolvers per returned
  #   SellerProfile (profileId, ownerAccountId, isOwner, permissions,
  #   latestCampaign). At 100 profiles in one response that is 501 resolver
  #   invocations; resolver_count_limit = 1000 gives ~2x headroom there while
  #   capping alias fan-out attacks well below the AppSync default of 10000.
  query_depth_limit    = 10
  resolver_count_limit = 1000

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

# API key for the public order surface. It is a transport credential, not a
# secret: it ships in the public browser bundle (VITE_APPSYNC_API_KEY) and grants
# access only to the @aws_api_key fields and types; every public call still needs
# a valid per-profile share token. AppSync allows one key per API-key mode, so
# rotation replaces this resource.
#
# `expires` is load-bearing: the provider DEFAULTS TO 7 DAYS, which would
# silently kill the public page a week after deploy. AWS caps a key at 365 days
# and requires the timestamp rounded DOWN to the nearest hour. Renewal is a
# manual runbook: the key VALUE is not retrievable through the AWS CLI after
# creation (only this resource's output carries it), so any change that REPLACES
# this resource loses the value permanently and the frontend bundle must be
# rebuilt in the same apply - a replaced key with a stale bundle means every
# public call fails Unauthorized until the next deploy. The ExpiredAPIKeys alarm
# is PLANNED in the public-orders spec's section 9 with the feature's ops slice
# and is NOT deployed yet - no CloudWatch alarm watches for day-zero key expiry
# today, so this date gate below is the only expiry check in the meantime.
resource "aws_appsync_api_key" "public" {
  api_id      = aws_appsync_graphql_api.main.id
  description = "Public order placement API key (public browser bundle; scoped by @aws_api_key)"
  expires     = "2027-10-03T00:00:00Z"
}

# AppSync-managed CloudWatch log group with explicit retention.
resource "aws_cloudwatch_log_group" "appsync" {
  name = "/aws/appsync/apis/${aws_appsync_graphql_api.main.id}"
  # kics-scan ignore-line -- retention IS set dynamically below; KICS only matches static values
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
