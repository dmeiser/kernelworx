# AppSync Functions for Campaign Operations

resource "aws_appsync_function" "lookup_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "LookupCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_campaign_fn.js")
}

resource "aws_appsync_function" "update_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "UpdateCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_campaign_fn.js")
}

resource "aws_appsync_function" "verify_update_catalog_access" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "VerifyUpdateCatalogAccessFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_update_catalog_access_fn.js")
}

resource "aws_appsync_function" "lookup_campaign_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "LookupCampaignForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_campaign_for_delete_fn.js")
}

resource "aws_appsync_function" "query_campaign_orders_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "QueryCampaignOrdersForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_campaign_orders_for_delete_fn.js")
}

resource "aws_appsync_function" "delete_campaign_orders" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "DeleteCampaignOrdersFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  # templatefile() reads the esbuild bundle in appsync/dist/, which strips
  # ordinary comments, so a dollar-brace sequence that survives bundling is
  # interpolated as a Terraform expression: in a string literal it aborts every
  # plan/apply with "Invalid expression". `${table_name}` is the only intended
  # placeholder; escape a literal as `$${...}` or switch this to file()
  # (#284 defers that switch). Enforced by
  # tests/unit/check_templatefile_escaping.test.ts (#570).
  code = templatefile("${local.js_resolvers_dir}/delete_campaign_orders_fn.js", {
    table_name = var.dynamodb_table_names.orders
  })
}

resource "aws_appsync_function" "delete_campaign_orders_lambda" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.delete_campaign_orders.name
  name        = "DeleteCampaignOrdersLambdaFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_campaign_orders_lambda_fn.js")
}

resource "aws_appsync_function" "delete_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "DeleteCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_campaign_fn.js")
}

resource "aws_appsync_function" "verify_campaign_delete_propagation" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "VerifyCampaignDeletePropagationFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_campaign_delete_propagation_fn.js")
}

resource "aws_appsync_function" "query_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "QueryCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_campaign_fn.js")
}

resource "aws_appsync_function" "return_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.none.name
  name        = "ReturnCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/return_campaign_fn.js")
}

resource "aws_appsync_function" "query_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "QueryCampaignsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_campaigns_fn.js")
}

# Shared Campaign Functions
resource "aws_appsync_function" "count_user_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "CountUserSharedCampaignsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/count_user_shared_campaigns_fn.js")
}

resource "aws_appsync_function" "get_catalog_for_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "GetCatalogForSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_catalog_for_shared_campaign_fn.js")
}

resource "aws_appsync_function" "get_account_for_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "GetAccountForSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_account_for_shared_campaign_fn.js")
}

resource "aws_appsync_function" "create_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "CreateSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_shared_campaign_fn.js")
}

resource "aws_appsync_function" "get_shared_campaign_for_update" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "GetSharedCampaignForUpdateFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_shared_campaign_for_update_fn.js")
}

resource "aws_appsync_function" "update_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "UpdateSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_shared_campaign_fn.js")
}

resource "aws_appsync_function" "delete_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "DeleteSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_shared_campaign_fn.js")
}

resource "aws_appsync_function" "get_shared_campaign_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "GetSharedCampaignForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_shared_campaign_for_delete_fn.js")
}

resource "aws_appsync_function" "lookup_shared_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "LookupSharedCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_shared_campaign_fn.js")
}

resource "aws_appsync_function" "verify_shared_campaign_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "VerifySharedCampaignCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_shared_campaign_catalog_fn.js")
}

resource "aws_appsync_function" "create_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "CreateCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_campaign_fn.js")
}

resource "aws_appsync_function" "create_campaign_share" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CreateCampaignShareFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_campaign_share_fn.js")
}


# Denormalized profile.latestCampaignId maintenance (#331).
# The create pipeline SETs the field to the new campaign (a new campaign is
# always the latest active one); the update/delete pipelines recompute the
# canonical latest ACTIVE campaign whenever isActive changes or a campaign
# is removed, so the denormalized pointer cannot drift from the semantics the
# SellerProfile.latestCampaign resolver implements.
resource "aws_appsync_function" "set_profile_latest_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "SetProfileLatestCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/set_profile_latest_campaign_fn.js")
}

resource "aws_appsync_function" "refresh_latest_campaign_lookup" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "RefreshLatestCampaignLookupFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/refresh_latest_campaign_lookup_fn.js")
}

resource "aws_appsync_function" "refresh_latest_campaign_write" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "RefreshLatestCampaignWriteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/refresh_latest_campaign_write_fn.js")
}

# === #679 rev 7 public-order settings (campaign-keyed, owner-only) ===

# Locator, first in both settings pipelines. The Campaigns base table is keyed
# {profileId, campaignId}, so a campaignId alone cannot address the row: this
# reads the campaignId-index GSI purely to learn the partition key, and hands
# the located item to the write-access pair through ctx.stash.campaign. The GSI
# row is a locator only - ownership is decided by the pair's consistent
# base-table read (#438) and the settings are re-read consistently below.
resource "aws_appsync_function" "locate_campaign_public_settings" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "LocateCampaignPublicSettingsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/locate_campaign_public_settings_fn.js")
}

# Authoritative settings read of getCampaignPublicOrderSettings. Rev 7 stores
# the publicOrders map on the campaign item, so one strongly consistent GetItem
# returns the settings, the lifetime counter, and the campaign's own name and
# active state. Keyed by the located partition key, so a campaignId belonging to
# another profile is a GetItem miss rather than a cross-account read.
resource "aws_appsync_function" "lookup_campaign_public_settings" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "LookupCampaignPublicSettingsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_campaign_public_settings_fn.js")
}

# Campaign gate of updateCampaignPublicOrderSettings: a caller who does not
# own the profile is refused FORBIDDEN by verify_public_settings_owner two
# steps earlier, so the consistent GetItem miss here answers NOT_FOUND only
# for a campaign deleted between the locator read and this read. When the save
# is actually publishing (enabling from an off state), the campaign must be
# active and carry a catalog. Disable, method-list and rotate-token saves stay
# allowed over an inactive campaign so the seller always has a working off
# switch and token revocation path.
resource "aws_appsync_function" "validate_campaign_settings_write" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "ValidateCampaignSettingsWriteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_campaign_settings_write_fn.js")
}

# Conditioned UpdateItem writing the campaign's publicOrders map. The
# attribute_not_exists(publicOrders.#token) guard is what makes a concurrent
# first-enable lose instead of overwriting the share token, and
# attribute_exists(campaignId) (the table's range key) makes a concurrent
# campaign delete win instead of leaving settings on a row that is going away -
# which is also why rev 7 needs no campaign-delete auto-disable hook.
resource "aws_appsync_function" "write_campaign_public_order_settings" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "WriteCampaignPublicOrderSettingsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/write_campaign_public_order_settings_fn.js")
}

# =============================================================================
# publicCreateOrder pipeline functions - campaign locator + cap gate (#679)
# =============================================================================

# Step 1: locate the campaign through the campaignId-index GSI. A GSI locator
# only; the consistent read in step 2 is what authorizes (#545). A pipeline may
# list a function id only once (#438), so each step is its own function resource.
resource "aws_appsync_function" "validate_public_token" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "ValidatePublicTokenFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_public_token_fn.js")
}

# Step 2: the strong campaign read carrying the token, active, cap pre-check,
# allowlist, ack, and input-bound checks; stashes the campaign + catalogId.
resource "aws_appsync_function" "validate_public_token_step2" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "ValidatePublicTokenStep2Fn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_public_token_step2_fn.js")
}

# Step 3: the per-share-token fixed-window throttle (SEC-6). A blind atomic
# UpdateItem on a tiny item in the public-order-throttles table; the condition
# is the rate bound. Rejects with the campaign-cap limit error shape.
resource "aws_appsync_function" "throttle_public_order_create" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.public_order_throttles.name
  name        = "ThrottlePublicOrderCreateFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/throttle_public_order_create_fn.js")
}

# Step 6: the cap CONDITION (atomic ADD on the campaign). Runs before the write.
resource "aws_appsync_function" "increment_public_order_count" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "IncrementPublicOrderCountFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/increment_public_order_count_fn.js")
}
