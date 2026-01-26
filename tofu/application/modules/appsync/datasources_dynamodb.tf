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
