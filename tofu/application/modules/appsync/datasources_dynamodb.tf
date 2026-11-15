# AppSync DynamoDB Data Sources

# DynamoDB Data Sources - one per table
resource "aws_appsync_datasource" "accounts" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "AccountsDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.accounts
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "catalogs" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "CatalogsDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.catalogs
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "profiles" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ProfilesDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.profiles
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "campaigns" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "CampaignsDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.campaigns
    region     = var.aws_region
  }
}

# Show & Sell §1.4 (data model §5.5-§5.6): Unit Campaign metadata, Scout
# memberships, and the per-campaign join guard. The order pipelines read the guard
# through this source because it is the only strongly consistent answer to "which
# Unit Campaign is this Scout Campaign joined to right now"; the Campaign row's own
# link is a latest-link that removal retains.
resource "aws_appsync_datasource" "unit_campaigns" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "UnitCampaignsDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.unit_campaigns
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "orders" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "OrdersDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.orders
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "shares" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "SharesDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.shares
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "invites" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "InvitesDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.invites
    region     = var.aws_region
  }
}

resource "aws_appsync_datasource" "shared_campaigns" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "SharedCampaignsDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.shared_campaigns
    region     = var.aws_region
  }
}

# Public-order throttle items (SEC-6): one small item per (share token, 60s
# window) with TTL, written only by the publicCreateOrder throttle step.
resource "aws_appsync_datasource" "public_order_throttles" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "PublicOrderThrottlesDS"
  type             = "AMAZON_DYNAMODB"
  service_role_arn = var.appsync_service_role_arn

  dynamodb_config {
    table_name = var.dynamodb_table_names.public_order_throttles
    region     = var.aws_region
  }
}
