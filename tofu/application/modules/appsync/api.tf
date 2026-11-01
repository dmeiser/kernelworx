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

  # Additional authentication mode for the public-orders surface (#679 rev 7).
  # The provider takes ONLY authentication_type here: an API key carries no
  # inline configuration block, and the key itself is the separate
  # aws_appsync_api_key resource below. The Cognito user-pool config above stays
  # the PRIMARY mode, so every existing field keeps its current auth; a field is
  # reachable with the key only when it carries @aws_api_key. At transport level
  # the key alone suffices to reach those fields; the per-campaign share token
  # is not a bearer header but a plain GraphQL argument each resolver checks
  # itself, answering NOT_FOUND when absent.
  additional_authentication_provider {
    authentication_type = "API_KEY"
  }

  # Schema loaded from file
  schema = file("${path.module}/../../schema/schema.graphql")

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# The public-orders API key (#679 rev 7). It is baked into the frontend bundle
# (VITE_APPSYNC_API_KEY), so it is expected to be public: it grants access only
# to the @aws_api_key root fields, and every one of those still requires a valid
# per-campaign share token, which is a plain GraphQL argument checked inside
# the resolver (NOT_FOUND when absent).
#
# `expires` is an explicit RFC3339 value at hour granularity. Omitting it is a
# trap: the provider defaults to 7 days, which would silently kill the public
# order page a week after every deploy. The value is a literal rather than
# timeadd(timestamp(), ...) on purpose - a computed expiry changes on every
# plan and would replace the key (and break every open tab holding the old
# bundle) on each deploy. The service caps a key at 365 days from creation, so
# this date must stay within a year of the deploy that creates the key.
#
# ROTATION MODEL (SEC-3): an expires-only edit does NOT rotate the key. The
# provider updates `expires` in place via UpdateApiKey and the key material
# never changes, so a leaked key edited this way stays valid - the old runbook
# premise ("any new value mints a new key") was false. AppSync's API-key mode
# genuinely supports multiple keys per API, so rotation is explicit and
# two-phase, modeled by `var.public_orders_key_slots`:
#
#   "a"  steady state: only slot A exists; the module output reads A.
#   "ab" rotation phase 1 (ADD NEW + DEPLOY): slot B is created; the module
#        output (and therefore every bundle the deploy builds) now reads B,
#        while slot A stays valid so open tabs are not broken.
#   "b"  rotation phase 3 (REMOVE OLD, after the B bundle is verified live):
#        slot A is destroyed and the leaked key is actually revoked.
#
# The full sequence with verification steps is docs/PUBLIC_API_KEY_RUNBOOK.md.
resource "aws_appsync_api_key" "public_orders" {
  count = contains(["a", "ab"], var.public_orders_key_slots) ? 1 : 0

  api_id      = aws_appsync_graphql_api.main.id
  description = "Public orders slot A (campaign-scoped share tokens)"
  expires     = "2027-10-01T00:00:00Z"
}

# Rotation slot B: exists only while `var.public_orders_key_slots` is "ab" or
# "b". Fresh key material on every creation; while it exists the module output
# prefers it. The "slot A"/"slot B" tags in the descriptions are what the
# ephemeral recovery import matches on (AppSync keys have no name).
resource "aws_appsync_api_key" "public_orders_rotation" {
  count = contains(["ab", "b"], var.public_orders_key_slots) ? 1 : 0

  api_id      = aws_appsync_graphql_api.main.id
  description = "Public orders rotation slot B (campaign-scoped share tokens)"
  expires     = "2027-10-01T00:00:00Z"
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
