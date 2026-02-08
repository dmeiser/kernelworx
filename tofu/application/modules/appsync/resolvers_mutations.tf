# AppSync Mutation Resolvers

# === SHARING & INVITATION MUTATIONS ===

# createProfileInvite Pipeline
resource "aws_appsync_resolver" "create_profile_invite" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createProfileInvite"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_owner_for_invite.function_id,
      aws_appsync_function.create_invite.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_profile_invite_pipeline_resolver.js")
}

# revokeShare Pipeline
resource "aws_appsync_resolver" "revoke_share" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "revokeShare"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_owner_for_revoke.function_id,
      aws_appsync_function.delete_share.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/revoke_share_pipeline_resolver.js")
}

# deleteProfileInvite Pipeline
resource "aws_appsync_resolver" "delete_profile_invite" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteProfileInvite"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.delete_profile_invite.function_id,
      aws_appsync_function.delete_invite_item.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_invite_pipeline_resolver.js")
}

# shareProfileDirect Pipeline
resource "aws_appsync_resolver" "share_profile_direct" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "shareProfileDirect"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_owner_for_share.function_id,
      aws_appsync_function.lookup_account_by_email.function_id,
      aws_appsync_function.check_existing_share.function_id,
      aws_appsync_function.create_share.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/share_profile_direct_pipeline_resolver.js")
}

# redeemProfileInvite Pipeline
resource "aws_appsync_resolver" "redeem_profile_invite" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "redeemProfileInvite"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_invite.function_id,
      aws_appsync_function.check_existing_share.function_id,
      aws_appsync_function.create_share.function_id,
      aws_appsync_function.mark_invite_used.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/redeem_profile_invite_pipeline_resolver.js")
}

# === CAMPAIGN MUTATIONS ===

# updateCampaign Pipeline
resource "aws_appsync_resolver" "update_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updateCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_campaign.function_id,
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.update_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_campaign_pipeline_resolver_v2.js")
}

# deleteCampaign Pipeline
resource "aws_appsync_resolver" "delete_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_campaign_for_delete.function_id,
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.query_campaign_orders_for_delete.function_id,
      aws_appsync_function.delete_campaign_orders.function_id,
      aws_appsync_function.delete_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_campaign_pipeline_resolver_v2.js")
}

# createCampaign (Lambda)
resource "aws_appsync_resolver" "create_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createCampaign"
  data_source = aws_appsync_datasource.campaign_operations.name
}

# === ORDER MUTATIONS ===

# updateOrder Pipeline
resource "aws_appsync_resolver" "update_order" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updateOrder"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_order.function_id,
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.get_catalog_for_update_order.function_id,
      aws_appsync_function.fetch_catalog_for_update.function_id,
      aws_appsync_function.update_order.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_order_pipeline_resolver_v2.js")
}

# deleteOrder Pipeline
resource "aws_appsync_resolver" "delete_order" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteOrder"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_order_for_delete.function_id,
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.delete_order.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_order_pipeline_resolver_v2.js")
}

# createOrder Pipeline
resource "aws_appsync_resolver" "create_order" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createOrder"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.validate_payment_method_appsync.function_id,
      aws_appsync_function.get_campaign_for_order.function_id,
      aws_appsync_function.ensure_catalog_for_order.function_id,
      aws_appsync_function.get_catalog_try_raw.function_id,
      aws_appsync_function.get_catalog_try_prefixed.function_id,
      aws_appsync_function.ensure_catalog_final.function_id,
      aws_appsync_function.get_catalog.function_id,
      aws_appsync_function.create_order.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_order_pipeline_resolver.js")
}

# === CATALOG MUTATIONS ===

# createCatalog (VTL)
resource "aws_appsync_resolver" "create_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createCatalog"
  data_source = aws_appsync_datasource.catalogs.name

  request_template  = file("${local.mapping_templates_dir}/create_catalog_request.vtl")
  response_template = file("${local.mapping_templates_dir}/create_catalog_response.vtl")
}

# updateCatalog (VTL)
resource "aws_appsync_resolver" "update_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "updateCatalog"
  data_source = aws_appsync_datasource.catalogs.name

  request_template  = file("${local.mapping_templates_dir}/update_catalog_request.vtl")
  response_template = file("${local.mapping_templates_dir}/update_catalog_response.vtl")
}

# deleteCatalog Pipeline
resource "aws_appsync_resolver" "delete_catalog" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteCatalog"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_catalog_for_delete.function_id,
      aws_appsync_function.check_catalog_usage.function_id,
      aws_appsync_function.delete_catalog_fn.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_catalog_pipeline_resolver.js")
}

# === SELLER PROFILE MUTATIONS ===

# createSellerProfile (Lambda)
resource "aws_appsync_resolver" "create_seller_profile" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createSellerProfile"
  data_source = aws_appsync_datasource.create_profile.name
}

# updateSellerProfile Pipeline
resource "aws_appsync_resolver" "update_seller_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updateSellerProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_profile_for_update.function_id,
      aws_appsync_function.update_profile.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_seller_profile_resolver.js")
}

# deleteSellerProfile Pipeline
resource "aws_appsync_resolver" "delete_seller_profile" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteSellerProfile"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_owner_for_delete.function_id,
      aws_appsync_function.query_profile_shares_for_delete.function_id,
      aws_appsync_function.query_profile_invites_for_delete.function_id,
      aws_appsync_function.delete_profile_shares.function_id,
      aws_appsync_function.delete_profile_invites.function_id,
      aws_appsync_function.query_profile_campaigns_for_delete.function_id,
      aws_appsync_function.delete_profile_orders_cascade_appsync.function_id,
      aws_appsync_function.delete_profile_campaigns.function_id,
      aws_appsync_function.delete_profile_ownership.function_id,
      aws_appsync_function.delete_profile_metadata.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_seller_profile_resolver.js")
}

# === SHARED CAMPAIGN MUTATIONS ===

# createSharedCampaign Pipeline
resource "aws_appsync_resolver" "create_shared_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createSharedCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.count_user_shared_campaigns.function_id,
      aws_appsync_function.get_catalog_for_shared_campaign.function_id,
      aws_appsync_function.get_account_for_shared_campaign.function_id,
      aws_appsync_function.create_shared_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_shared_campaign_pipeline_resolver.js")
}

# updateSharedCampaign Pipeline
resource "aws_appsync_resolver" "update_shared_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updateSharedCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_shared_campaign_for_update.function_id,
      aws_appsync_function.update_shared_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_shared_campaign_pipeline_resolver.js")
}

# deleteSharedCampaign Pipeline
resource "aws_appsync_resolver" "delete_shared_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deleteSharedCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_shared_campaign_for_delete.function_id,
      aws_appsync_function.delete_shared_campaign.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_shared_campaign_pipeline_resolver.js")
}

# === ACCOUNT & PREFERENCES MUTATIONS ===

# updateMyAccount (Lambda)
resource "aws_appsync_resolver" "update_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "updateMyAccount"
  data_source = aws_appsync_datasource.update_account.name
}

# deleteMyAccount (Lambda)
resource "aws_appsync_resolver" "delete_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "deleteMyAccount"
  data_source = aws_appsync_datasource.delete_account.name
}

# transferProfileOwnership (Lambda)
resource "aws_appsync_resolver" "transfer_profile_ownership" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "transferProfileOwnership"
  data_source = aws_appsync_datasource.transfer_ownership.name
}

# updateMyPreferences (JS)
resource "aws_appsync_resolver" "update_my_preferences" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "updateMyPreferences"
  data_source = aws_appsync_datasource.accounts.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_my_preferences_resolver.js")
}

# requestCampaignReport (Lambda)
resource "aws_appsync_resolver" "request_campaign_report" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "requestCampaignReport"
  data_source = aws_appsync_datasource.request_report.name
}

# === PAYMENT METHODS MUTATIONS ===

# createPaymentMethod Pipeline
resource "aws_appsync_resolver" "create_payment_method" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createPaymentMethod"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.validate_create_payment_method.function_id,
      aws_appsync_function.create_payment_method.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_payment_method_pipeline_resolver.js")
}

# updatePaymentMethod Pipeline
resource "aws_appsync_resolver" "update_payment_method" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updatePaymentMethod"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.validate_update_payment_method.function_id,
      aws_appsync_function.update_payment_method.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_payment_method_pipeline_resolver.js")
}

# deletePaymentMethod Pipeline
resource "aws_appsync_resolver" "delete_payment_method" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "deletePaymentMethod"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.get_payment_method_for_delete.function_id,
      aws_appsync_function.delete_payment_method_from_prefs.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_payment_method_no_qr_pipeline_resolver.js")
}

# deletePaymentMethodQRCode (Lambda)
resource "aws_appsync_resolver" "delete_payment_method_qr_code" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "deletePaymentMethodQRCode"
  data_source = aws_appsync_datasource.delete_qr_code.name
}

# requestPaymentMethodQRCodeUpload (Lambda)
resource "aws_appsync_resolver" "request_payment_method_qr_code_upload" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "requestPaymentMethodQRCodeUpload"
  data_source = aws_appsync_datasource.request_qr_upload.name
}

# confirmPaymentMethodQRCodeUpload (Lambda)
resource "aws_appsync_resolver" "confirm_payment_method_qr_code_upload" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "confirmPaymentMethodQRCodeUpload"
  data_source = aws_appsync_datasource.confirm_qr_upload.name
}

# === ADMIN MUTATIONS ===

# adminResetUserPassword (Lambda)
resource "aws_appsync_resolver" "admin_reset_user_password" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminResetUserPassword"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUser (Lambda)
resource "aws_appsync_resolver" "admin_delete_user" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUser"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUserOrders (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_orders" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserOrders"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUserCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUserShares (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserShares"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUserProfiles (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserProfiles"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteUserCatalogs (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserCatalogs"
  data_source = aws_appsync_datasource.admin_operations.name
}

# createManagedCatalog (Lambda)
resource "aws_appsync_resolver" "create_managed_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createManagedCatalog"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminDeleteShare (Lambda)
resource "aws_appsync_resolver" "admin_delete_share" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteShare"
  data_source = aws_appsync_datasource.admin_operations.name
}

# adminUpdateCampaignSharedCode (Lambda)
resource "aws_appsync_resolver" "admin_update_campaign_shared_code" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminUpdateCampaignSharedCode"
  data_source = aws_appsync_datasource.admin_operations.name
}
