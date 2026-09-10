# AppSync Field Resolvers

# === CAMPAIGN FIELD RESOLVERS ===

# Campaign.catalog (JS pipeline, #332)
# check_source_catalog surfaces a catalog already batch-resolved by a parent
# list query (listCampaignsByProfile); get_campaign_catalog performs the
# single GetItem for singular fetches, exactly as the removed VTL resolver.
resource "aws_appsync_resolver" "campaign_catalog" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Campaign"
  field  = "catalog"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.check_source_catalog.function_id,
      aws_appsync_function.get_campaign_catalog.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/campaign_catalog_pipeline_resolver.js")
}

# Campaign.totalOrders (VTL)
resource "aws_appsync_resolver" "campaign_total_orders" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Campaign"
  field       = "totalOrders"
  data_source = aws_appsync_datasource.orders.name

  request_template  = file("${local.mapping_templates_dir}/campaign_total_orders_request.vtl")
  response_template = file("${local.mapping_templates_dir}/campaign_total_orders_response.vtl")
}

# Campaign.totalRevenue (VTL)
resource "aws_appsync_resolver" "campaign_total_revenue" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Campaign"
  field       = "totalRevenue"
  data_source = aws_appsync_datasource.orders.name

  request_template  = file("${local.mapping_templates_dir}/campaign_total_revenue_request.vtl")
  response_template = file("${local.mapping_templates_dir}/campaign_total_revenue_response.vtl")
}

# === SELLER PROFILE FIELD RESOLVERS ===

# SellerProfile.ownerAccountId (JS)
resource "aws_appsync_resolver" "seller_profile_owner_account_id" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SellerProfile"
  field       = "ownerAccountId"
  data_source = aws_appsync_datasource.none.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_owner_account_id_resolver.js")
}

# SellerProfile.profileId (JS)
resource "aws_appsync_resolver" "seller_profile_id" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SellerProfile"
  field       = "profileId"
  data_source = aws_appsync_datasource.none.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_id_resolver.js")
}

# SellerProfile.isOwner (JS)
resource "aws_appsync_resolver" "seller_profile_is_owner" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SellerProfile"
  field       = "isOwner"
  data_source = aws_appsync_datasource.none.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_is_owner_resolver.js")
}

# SellerProfile.permissions (JS)
resource "aws_appsync_resolver" "seller_profile_permissions" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SellerProfile"
  field       = "permissions"
  data_source = aws_appsync_datasource.shares.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_permissions_resolver.js")
}

# SellerProfile.latestCampaign (JS)
resource "aws_appsync_resolver" "seller_profile_latest_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SellerProfile"
  field       = "latestCampaign"
  data_source = aws_appsync_datasource.campaigns.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_latest_campaign_resolver.js")
}

# SharedProfile.latestCampaign (JS)
resource "aws_appsync_resolver" "shared_profile_latest_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "SharedProfile"
  field       = "latestCampaign"
  data_source = aws_appsync_datasource.campaigns.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/seller_profile_latest_campaign_resolver.js")
}

# === SHARED CAMPAIGN FIELD RESOLVERS ===

# SharedCampaign.catalog (JS pipeline, #332)
# check_source_catalog surfaces a catalog already batch-resolved by a parent
# list query (listMySharedCampaigns / findSharedCampaigns);
# get_shared_campaign_catalog performs the single GetItem for singular
# fetches, exactly as the removed VTL resolver.
resource "aws_appsync_resolver" "shared_campaign_catalog" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "SharedCampaign"
  field  = "catalog"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.check_source_catalog.function_id,
      aws_appsync_function.get_shared_campaign_catalog.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/shared_campaign_catalog_pipeline_resolver.js")
}

# === SHARE FIELD RESOLVERS ===

# Share.targetAccount (JS)
resource "aws_appsync_resolver" "share_target_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Share"
  field       = "targetAccount"
  data_source = aws_appsync_datasource.accounts.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/share_target_account_resolver.js")
}

# === ACCOUNT FIELD RESOLVERS ===

# Account.accountId (JS)
resource "aws_appsync_resolver" "account_id" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Account"
  field       = "accountId"
  data_source = aws_appsync_datasource.none.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/account_id_resolver.js")
}

