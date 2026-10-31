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

# redeemProfileInvite Pipeline
resource "aws_appsync_resolver" "redeem_profile_invite" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "redeemProfileInvite"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.lookup_invite.function_id,
      # #453: reject redemption when the profile was transferred away from the
      # invite's creation-time owner before the share is stamped.
      aws_appsync_function.verify_invite_owner_current.function_id,
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
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.verify_update_catalog_access.function_id,
      aws_appsync_function.update_campaign.function_id,
      # isActive can change which campaign is the latest active one;
      # recompute the profile's denormalized latestCampaignId (#331).
      aws_appsync_function.refresh_latest_campaign_lookup.function_id,
      aws_appsync_function.refresh_latest_campaign_write.function_id,
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
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.delete_campaign_orders_lambda.function_id,
      aws_appsync_function.delete_campaign.function_id,
      # Removing a campaign can change which campaign is the latest active
      # one; recompute BEFORE the propagation check so the profile's
      # denormalized latestCampaignId is refreshed even if verification
      # fails (#331).
      aws_appsync_function.refresh_latest_campaign_lookup.function_id,
      aws_appsync_function.refresh_latest_campaign_write.function_id,
      aws_appsync_function.verify_campaign_delete_propagation.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_campaign_pipeline_resolver_v2.js")
}

# createCampaign Pipeline
resource "aws_appsync_resolver" "create_campaign" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createCampaign"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.verify_profile_write_access.function_id,
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.lookup_shared_campaign.function_id,
      aws_appsync_function.verify_shared_campaign_catalog.function_id,
      aws_appsync_function.create_campaign.function_id,
      # Stamp the owning profile's denormalized latestCampaignId in the same
      # pipeline so it cannot drift (#331).
      aws_appsync_function.set_profile_latest_campaign.function_id,
      aws_appsync_function.create_campaign_share.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_campaign_pipeline_resolver.js")
}

# updateCampaignPublicOrderSettings Pipeline (#679 rev 7, campaign-keyed).
# Owner-only: the pair decides ownership over the campaign's own profileId,
# verify_public_settings_owner refuses a WRITE-share collaborator and a stranger
# with FORBIDDEN, then the campaign and its catalog are confirmed before the
# conditioned write. Rev 7 writes the settings onto the campaign item, so
# deleting the campaign destroys the settings, the share token and the counter
# with it - no auto-disable hook and no dangling-anchor recovery anywhere in the
# deleteCampaign pipeline.
resource "aws_appsync_resolver" "update_campaign_public_order_settings" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "updateCampaignPublicOrderSettings"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      # CampaignsDS GSI locator: campaignId -> profileId, for the pair below.
      aws_appsync_function.locate_campaign_public_settings.function_id,
      # Two-phase owner check (#438): ownership comes from the strongly
      # consistent base-table read, never the eventually-consistent GSI.
      aws_appsync_function.verify_profile_write_access.function_id,
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      # Gate: isOwner === true, else FORBIDDEN (share collaborators included).
      aws_appsync_function.verify_public_settings_owner.function_id,
      # CampaignsDS: the campaign exists under this profile's partition key and,
      # when the save is publishing, is active and carries a catalog.
      aws_appsync_function.validate_campaign_settings_write.function_id,
      # CatalogsDS: a different table, so a second function - the catalog must
      # exist and not be soft-deleted before an offer can publish over it.
      aws_appsync_function.validate_public_settings_catalog.function_id,
      # CampaignsDS: the conditioned UpdateItem writing the publicOrders map.
      aws_appsync_function.write_campaign_public_order_settings.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_campaign_public_order_settings_pipeline_resolver.js")
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
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.validate_payment_method_appsync.function_id,
      aws_appsync_function.get_catalog_for_update_order.function_id,
      aws_appsync_function.fetch_catalog_for_update.function_id,
      aws_appsync_function.update_order.function_id,
      # #746: keep the denormalized campaign totals in sync when the edit
      # changed lineItems (a zero/omitted delta makes this a pass-through).
      aws_appsync_function.sync_campaign_totals.function_id,
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
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.delete_order.function_id,
      # #746: decrement the denormalized campaign totals after the delete (a
      # no-op delete stashes no delta and this passes through).
      aws_appsync_function.sync_campaign_totals.function_id,
      aws_appsync_function.verify_order_delete_propagation.function_id,
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
      # Step 2 of the two-phase owner check (#438): runs only for non-owners to
      # query the GSI for the profile so the share check can run.
      aws_appsync_function.verify_profile_write_access_step2.function_id,
      aws_appsync_function.check_share_permissions.function_id,
      aws_appsync_function.validate_payment_method_appsync.function_id,
      aws_appsync_function.get_campaign_for_order.function_id,
      aws_appsync_function.get_catalog.function_id,
      aws_appsync_function.create_order.function_id,
      # #746: increment the denormalized campaign totals after the write.
      aws_appsync_function.sync_campaign_totals.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_order_pipeline_resolver.js")

  lifecycle {
    replace_triggered_by = [terraform_data.create_order_resolver_code]
  }
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
      aws_appsync_function.check_shared_campaign_usage.function_id,
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

# createSellerProfile (JS)
resource "aws_appsync_resolver" "create_seller_profile" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createSellerProfile"
  data_source = aws_appsync_datasource.profiles.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_seller_profile_resolver.js")
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
      aws_appsync_function.delete_profile_cascade.function_id,
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

# updateMyAccount (JS)
resource "aws_appsync_resolver" "update_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "updateMyAccount"
  data_source = aws_appsync_datasource.accounts.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_my_account_resolver.js")
}


# deleteMyAccount (Lambda)
resource "aws_appsync_resolver" "delete_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "deleteMyAccount"
  data_source = aws_appsync_datasource.delete_account.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# transferProfileOwnership (Lambda)
resource "aws_appsync_resolver" "transfer_profile_ownership" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "transferProfileOwnership"
  data_source = aws_appsync_datasource.transfer_ownership.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
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
      # Batch-sign the QR URL in one Lambda invocation (last step; #330)
      aws_appsync_function.batch_qr_urls.function_id,
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
      aws_appsync_function.delete_payment_method_qr_code.function_id,
      aws_appsync_function.delete_payment_method_from_prefs.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_payment_method_pipeline_resolver.js")
}

# deletePaymentMethodQRCode (Lambda)
resource "aws_appsync_resolver" "delete_payment_method_qr_code" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "deletePaymentMethodQRCode"
  data_source = aws_appsync_datasource.delete_qr_code.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# requestPaymentMethodQRCodeUpload (Lambda)
resource "aws_appsync_resolver" "request_payment_method_qr_code_upload" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "requestPaymentMethodQRCodeUpload"
  data_source = aws_appsync_datasource.request_qr_upload.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_unit_resolver.js")
}

# confirmPaymentMethodQRCodeUpload Pipeline
resource "aws_appsync_resolver" "confirm_payment_method_qr_code_upload" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "confirmPaymentMethodQRCodeUpload"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      aws_appsync_function.confirm_qr_upload.function_id,
      # Sign the returned S3 key into a presigned URL (last step; #330)
      aws_appsync_function.batch_qr_urls.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/confirm_payment_method_qr_code_upload_pipeline_resolver.js")
}

# === ADMIN MUTATIONS ===

# adminResetUserPassword (Lambda)
resource "aws_appsync_resolver" "admin_reset_user_password" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminResetUserPassword"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminPurgeUserAccount (Lambda)
resource "aws_appsync_resolver" "admin_purge_user_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminPurgeUserAccount"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminDeleteUserOrders (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_orders" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserOrders"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminDeleteUserCampaigns (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserCampaigns"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminDeleteUserShares (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserShares"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminDeleteUserProfiles (Lambda)
resource "aws_appsync_resolver" "admin_delete_user_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteUserProfiles"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# createManagedCatalog (Lambda)
resource "aws_appsync_resolver" "create_managed_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "createManagedCatalog"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminDeleteShare (Lambda)
resource "aws_appsync_resolver" "admin_delete_share" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminDeleteShare"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# adminUpdateCampaignSharedCode (Lambda)
resource "aws_appsync_resolver" "admin_update_campaign_shared_code" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Mutation"
  field       = "adminUpdateCampaignSharedCode"
  data_source = aws_appsync_datasource.admin_operations.name

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

# publicCreateOrder (#679 write slice, campaign-keyed rework): an APPSYNC_JS
# pipeline on the DynamoDB datasources plus one Lambda invoke. Order:
#   1 validate_public_token            (CampaignsDS, campaignId-index locator)
#   2 validate_public_token_step2      (CampaignsDS, strong read + all checks)
#   3 throttle_public_order_create     (PublicOrderThrottlesDS, per-token
#                                       fixed-window abuse guard, SEC-6)
#   4 get_profile_for_public_order     (ProfilesDS, GSI locator only)
#   5 get_profile_for_public_order_step2 (ProfilesDS, strong ownership
#                                       confirmation; fail closed on a stale
#                                       transfer-lag projection, SEC-4)
#   6 get_catalog                     (CatalogsDS, reused as-is)
#   7 validate_payment_method_public  (AccountsDS, no-oracle clone)
#   8 increment_public_order_count    (CampaignsDS, the cap CONDITION)
#   9 create_public_order             (OrdersDS, the PutItem + receipt mint)
#  10 send_public_order_emails        (PublicOrdersDS, best-effort; failures
#                                       are swallowed so email never fails the
#                                     committed order)
resource "aws_appsync_resolver" "public_create_order" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "publicCreateOrder"
  kind   = "PIPELINE"

  pipeline_config {
    functions = [
      # Two function resources over two files because a pipeline may list a
      # function id only once (#438).
      aws_appsync_function.validate_public_token.function_id,
      aws_appsync_function.validate_public_token_step2.function_id,
      # SEC-6: the throttle runs immediately after authorization, before any
      # further reads, so a flooding token does no extra work per request.
      aws_appsync_function.throttle_public_order_create.function_id,
      # SEC-4: the GSI locator and the strong ownership confirmation are two
      # functions; the owner id is not trusted until step 5.
      aws_appsync_function.get_profile_for_public_order.function_id,
      aws_appsync_function.get_profile_for_public_order_step2.function_id,
      # CatalogsDS: reused as-is; reads ctx.stash.catalogId stashed in step 2.
      aws_appsync_function.get_catalog.function_id,
      aws_appsync_function.validate_payment_method_public.function_id,
      # CampaignsDS: the cap gate, BEFORE the write (condition failure aborts
      # the pipeline with PUBLIC_ORDER_LIMIT_EXCEEDED and no row).
      aws_appsync_function.increment_public_order_count.function_id,
      aws_appsync_function.create_public_order.function_id,
      # Best-effort email, AFTER the write: the function and the handler both
      # swallow failures and only update confirmationEmailSent.
      aws_appsync_function.send_public_order_emails.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/public_create_order_pipeline_resolver.js")
}
