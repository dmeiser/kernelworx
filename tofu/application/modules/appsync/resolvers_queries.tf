# AppSync Query Resolvers

# === ACCOUNT & PROFILE QUERIES ===

# getMyAccount Pipeline (JS)
resource "aws_appsync_resolver" "get_my_account" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "getMyAccount"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_my_account_exact.function_id,
      aws_appsync_function.ensure_my_account_exists.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_my_account_pipeline_resolver.js")
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
      # Step 2 of the two-phase owner check (#545): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.fetch_profile_step2.function_id,
      aws_appsync_function.check_profile_read_auth.function_id,
    ]
  }

  request_template  = file("${local.mapping_templates_dir}/get_profile_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_profile_response.vtl")
}

# listMyProfiles Pipeline (JS)
# Batch-attaches latestCampaign to profiles carrying the denormalized
# latestCampaignId field in a single BatchGetItem per page (#331);
# unmigrated profiles fall through to the field resolver's per-item Query.
resource "aws_appsync_resolver" "list_my_profiles" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listMyProfiles"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.list_my_profiles.function_id,
      aws_appsync_function.batch_latest_campaigns.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_profiles_pipeline_resolver.js")
}

# listMyShares Pipeline (JS) - migrated from the list-my-shares Lambda (#334)
resource "aws_appsync_resolver" "list_my_shares" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listMyShares"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.query_my_shares.function_id,
      aws_appsync_function.batch_get_shared_profiles.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_shares_pipeline_resolver.js")
}

# listCatalogsInUse (Lambda)
resource "aws_appsync_resolver" "list_catalogs_in_use" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listCatalogsInUse"
  data_source = aws_appsync_datasource.list_catalogs_in_use.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
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
      # Step 2 of the two-phase owner check (#508): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_read_access_step2.function_id,
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
# Last step batch-resolves every campaign's catalog in one BatchGetItem
# instead of one GetItem per campaign via the field resolver (#332).
resource "aws_appsync_resolver" "list_campaigns_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listCampaignsByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_read_access.function_id,
      # Step 2 of the two-phase owner check (#508).
      aws_appsync_function.verify_profile_read_access_step2.function_id,
      aws_appsync_function.check_share_read_permissions.function_id,
      aws_appsync_function.query_campaigns.function_id,
      aws_appsync_function.batch_get_catalogs.function_id,
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
      # Step 2 of the two-phase owner check (#508).
      aws_appsync_function.verify_profile_read_access_step2.function_id,
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
      # Step 2 of the two-phase owner check (#508).
      aws_appsync_function.verify_profile_read_access_step2.function_id,
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

# === SHARE & INVITE QUERIES ===

# listSharesByProfile Pipeline
resource "aws_appsync_resolver" "list_shares_by_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listSharesByProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      # #547: two-phase owner check (#438) - the strongly consistent base-table
      # GetItem decides ownership; the GSI runs only for non-owners. This was
      # previously the pre-#438 verify_profile_write_or_owner single-step GSI
      # read, which authorized off the eventually-consistent GSI.
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.verify_profile_write_access_step2.function_id,
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
      # #547: two-phase owner check (#438), same as listSharesByProfile - ownership
      # is decided by the strongly consistent base-table GetItem, never the GSI.
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.verify_profile_write_access_step2.function_id,
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

# === PUBLIC ORDER SETTINGS QUERIES ===

# getProfilePublicOrderSettings Pipeline (#679 settings slice). Owner-only:
# the pair decides ownership, verify_public_settings_owner refuses everyone else
# with FORBIDDEN (its own message, because the pair's Query silent-deny branch
# leaves a null stash for a stranger and for a nonexistent profile alike), and
# one CampaignsDS GetItem supplies the counter, name and staleness flag.
resource "aws_appsync_resolver" "get_profile_public_order_settings" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "getProfilePublicOrderSettings"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      # Two-phase owner check (#438): the strongly consistent base-table GetItem
      # decides ownership, the GSI runs only for non-owners.
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.verify_public_settings_owner.function_id,
      aws_appsync_function.lookup_public_settings_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_profile_public_order_settings_pipeline_resolver.js")
}

# publicGetOrderOffer (Lambda unit resolver, #679 offer slice). A direct UNIT
# resolver on the public-orders Lambda: the offer makes six reads plus local QR
# signing, which a Lambda can do and an APPSYNC_JS function cannot. The field
# carries only @aws_api_key, so identity is null here; lambda_unit_resolver.js
# forwards the whole context (the handler dispatches on info.fieldName) and maps
# the handler's __isError payload to the GraphQL error code.
resource "aws_appsync_resolver" "public_order_offer" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "publicGetOrderOffer"
  data_source = aws_appsync_datasource.public_orders.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# publicGetOrderReceipt (Lambda unit resolver, #679 write slice). The second
# field on the same public-orders Lambda: the receipt read is one strongly
# consistent orders GetItem plus the seller-name read, and the handler
# dispatches on info.fieldName exactly as the offer does. The per-order receipt
# token in the argument is the capability - identity is null under API_KEY, and
# unknown order, absent token, mismatched token, and an embedded-campaign
# mismatch all answer the identical NOT_FOUND.
resource "aws_appsync_resolver" "public_order_receipt" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "publicGetOrderReceipt"
  data_source = aws_appsync_datasource.public_orders.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
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

# listMySharedCampaigns Pipeline (#332)
# Batch-resolves every shared campaign's catalog in one BatchGetItem instead
# of one GetItem per campaign via the field resolver.
resource "aws_appsync_resolver" "list_my_shared_campaigns" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "listMySharedCampaigns"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.query_my_shared_campaigns.function_id,
      aws_appsync_function.batch_get_shared_campaign_catalogs.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_shared_campaigns_pipeline_resolver.js")
}

# findSharedCampaigns Pipeline (#332)
# Batch-resolves every shared campaign's catalog in one BatchGetItem instead
# of one GetItem per campaign via the field resolver.
resource "aws_appsync_resolver" "find_shared_campaigns" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Query"
  field  = "findSharedCampaigns"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.find_shared_campaigns_by_unit.function_id,
      aws_appsync_function.batch_get_shared_campaign_catalogs.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/find_shared_campaigns_pipeline_resolver.js")
}

# === REPORTING QUERIES ===

# getUnitReport (Lambda)
resource "aws_appsync_resolver" "get_unit_report" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getUnitReport"
  data_source = aws_appsync_datasource.unit_reporting.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# listUnitCatalogs (Lambda)
resource "aws_appsync_resolver" "list_unit_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listUnitCatalogs"
  data_source = aws_appsync_datasource.list_unit_catalogs.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# listUnitCampaignCatalogs (Lambda)
resource "aws_appsync_resolver" "list_unit_campaign_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listUnitCampaignCatalogs"
  data_source = aws_appsync_datasource.list_unit_campaign_catalogs.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
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
      # Batch-sign all QR URLs in one Lambda invocation (last step; #330)
      aws_appsync_function.batch_qr_urls.function_id,
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
      # Step 2 of the two-phase owner check (#545): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.fetch_profile_step2.function_id,
      aws_appsync_function.check_payment_methods_access.function_id,
      aws_appsync_function.get_owner_payment_methods.function_id,
      aws_appsync_function.filter_payment_methods_by_access.function_id,
      # Batch-sign all QR URLs in one Lambda invocation (last step; #330)
      aws_appsync_function.batch_qr_urls.function_id,
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

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminSearchUser (Lambda)
resource "aws_appsync_resolver" "admin_search_user" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminSearchUser"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminGetUserProfiles (Lambda)
resource "aws_appsync_resolver" "admin_get_user_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserProfiles"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminGetUserCatalogs (Lambda)
resource "aws_appsync_resolver" "admin_get_user_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserCatalogs"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminGetUserCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_get_user_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminGetUserSharedCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_get_user_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetUserSharedCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminGetProfileShares (Lambda)
resource "aws_appsync_resolver" "admin_get_profile_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "adminGetProfileShares"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}
