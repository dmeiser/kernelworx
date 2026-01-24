# AppSync Query Resolvers

# === ACCOUNT & PROFILE QUERIES ===

# getMyAccount (VTL)
resource "aws_appsync_resolver" "get_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getMyAccount"
  data_source = aws_appsync_datasource.accounts.name

  request_template  = file("${local.mapping_templates_dir}/get_my_account_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_my_account_response.vtl")
}

# getProfile Pipeline
resource "aws_appsync_resolver" "get_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "getProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.fetch_profile.function_id,
      aws_appsync_function.check_profile_read_auth.function_id,
    ]
  }

  request_template  = file("${local.mapping_templates_dir}/get_profile_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_profile_response.vtl")
}

# listMyProfiles (JS)
resource "aws_appsync_resolver" "list_my_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listMyProfiles"
  data_source = aws_appsync_datasource.profiles.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_profiles_fn.js")
}

# listMyShares (Lambda)
resource "aws_appsync_resolver" "list_my_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listMyShares"
  data_source = aws_appsync_datasource.list_my_shares.name
}

# listCatalogsInUse (Lambda)
resource "aws_appsync_resolver" "list_catalogs_in_use" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listCatalogsInUse"
  data_source = aws_appsync_datasource.list_catalogs_in_use.name
}

# === CAMPAIGN QUERIES ===

# getCampaign Pipeline
resource "aws_appsync_resolver" "get_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "getCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.query_campaign.function_id,
      aws_appsync_function.verify_profile_read_access.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.return_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_campaign_resolver.js")
}

# listCampaignsByProfile Pipeline
resource "aws_appsync_resolver" "list_campaigns_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listCampaignsByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_read_access.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.query_campaigns.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_campaigns_by_profile_resolver.js")
}

# === ORDER QUERIES ===

# getOrder Pipeline
resource "aws_appsync_resolver" "get_order" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "getOrder"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.query_order.function_id,
      aws_appsync_function.verify_profile_read_access.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.return_order.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_order_resolver.js")
}

# listOrdersByCampaign Pipeline
resource "aws_appsync_resolver" "list_orders_by_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listOrdersByCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_campaign_for_orders.function_id,
      aws_appsync_function.verify_profile_read_access.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.query_orders_by_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_orders_by_campaign_resolver.js")
}

# listOrdersByProfile Pipeline
resource "aws_appsync_resolver" "list_orders_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listOrdersByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_read_access.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.query_orders_by_profile.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_orders_by_profile_resolver.js")
}

# === SHARE & INVITE QUERIES ===

# listSharesByProfile Pipeline
resource "aws_appsync_resolver" "list_shares_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listSharesByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_write_or_owner.function_id,
      aws_appsync_function.check_write_permission.function_id,
      aws_appsync_function.query_shares.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_shares_by_profile_resolver.js")
}

# listInvitesByProfile Pipeline
resource "aws_appsync_resolver" "list_invites_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listInvitesByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_write_or_owner.function_id,
      aws_appsync_function.check_write_permission.function_id,
      aws_appsync_function.query_invites.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_invites_by_profile_pipeline_resolver.js")
}

# === CATALOG QUERIES ===

# getCatalog (VTL)
resource "aws_appsync_resolver" "get_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getCatalog"
  data_source = aws_appsync_datasource.catalogs.name

  request_template  = file("${local.mapping_templates_dir}/get_catalog_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_catalog_response.vtl")
}

# listManagedCatalogs (JS)
resource "aws_appsync_resolver" "list_managed_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listManagedCatalogs"
  data_source = aws_appsync_datasource.catalogs.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_public_catalogs_resolver.js")
}

# listMyCatalogs (JS)
resource "aws_appsync_resolver" "list_my_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listMyCatalogs"
  data_source = aws_appsync_datasource.catalogs.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_catalogs_resolver.js")
}

# === SHARED CAMPAIGN QUERIES ===

# getSharedCampaign (VTL)
resource "aws_appsync_resolver" "get_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getSharedCampaign"
  data_source = aws_appsync_datasource.shared_campaigns.name

  request_template  = file("${local.mapping_templates_dir}/get_shared_campaign_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_shared_campaign_response.vtl")
}

# listMySharedCampaigns (JS)
resource "aws_appsync_resolver" "list_my_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listMySharedCampaigns"
  data_source = aws_appsync_datasource.shared_campaigns.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_shared_campaigns_resolver.js")
}

# findSharedCampaigns (JS)
resource "aws_appsync_resolver" "find_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "findSharedCampaigns"
  data_source = aws_appsync_datasource.shared_campaigns.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/find_shared_campaigns_resolver.js")
}

# === REPORTING QUERIES ===

# getUnitReport (Lambda)
resource "aws_appsync_resolver" "get_unit_report" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getUnitReport"
  data_source = aws_appsync_datasource.unit_reporting.name
}

# listUnitCatalogs (Lambda)
resource "aws_appsync_resolver" "list_unit_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listUnitCatalogs"
  data_source = aws_appsync_datasource.list_unit_catalogs.name
}

# listUnitCampaignCatalogs (Lambda)
resource "aws_appsync_resolver" "list_unit_campaign_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listUnitCampaignCatalogs"
  data_source = aws_appsync_datasource.list_unit_campaign_catalogs.name
}

# === PAYMENT METHODS QUERIES ===

# myPaymentMethods Pipeline
resource "aws_appsync_resolver" "my_payment_methods" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "myPaymentMethods"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_payment_methods.function_id,
      aws_appsync_function.inject_global_payment_methods.function_id,
      aws_appsync_function.set_owner_account_id_in_stash.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/my_payment_methods_pipeline_resolver.js")
}

# paymentMethodsForProfile Pipeline
resource "aws_appsync_resolver" "payment_methods_for_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "paymentMethodsForProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.fetch_profile.function_id,
      aws_appsync_function.check_payment_methods_access.function_id,
      aws_appsync_function.get_owner_payment_methods.function_id,
      aws_appsync_function.filter_payment_methods_by_access.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/payment_methods_for_profile_pipeline_resolver.js")
}

# === ADMIN QUERIES ===

# adminListUsers (Lambda)
resource "aws_appsync_resolver" "admin_list_users" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminListUsers"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminSearchUser (Lambda)
resource "aws_appsync_resolver" "admin_search_user" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminSearchUser"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminGetUserProfiles (Lambda)
resource "aws_appsync_resolver" "admin_get_user_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserProfiles"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminGetUserCatalogs (Lambda)
resource "aws_appsync_resolver" "admin_get_user_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserCatalogs"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminGetUserCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_get_user_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminGetUserSharedCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_get_user_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserSharedCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminGetProfileShares (Lambda)
resource "aws_appsync_resolver" "admin_get_profile_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetProfileShares"
  data_source = aws_appsync_datasource.admin_operations.name
}
