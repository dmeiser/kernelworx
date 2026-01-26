# AppSync Functions for Profile Operations

# Profile Query Functions
resource "aws_appsync_function" "fetch_profile" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "FetchProfileFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/fetch_profile_fn.js")
}

resource "aws_appsync_function" "check_profile_read_auth" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckProfileReadAuthFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_profile_read_auth_fn.js")
}

resource "aws_appsync_function" "verify_profile_write_or_owner" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileWriteAccessOrOwnerFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_write_access_or_owner_fn.js")
}

resource "aws_appsync_function" "check_write_permission" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckWritePermissionFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_write_permission_fn.js")
}

resource "aws_appsync_function" "query_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "QuerySharesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_shares_fn.js")
}

resource "aws_appsync_function" "query_invites" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "QueryInvitesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_invites_fn.js")
}

# Profile Delete Functions
resource "aws_appsync_function" "lookup_profile_for_update" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "LookupProfileForUpdateFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_profile_for_update_fn.js")
}

resource "aws_appsync_function" "update_profile" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "UpdateProfileFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_profile_fn.js")
}

resource "aws_appsync_function" "verify_profile_owner_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileOwnerForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_owner_for_delete_fn.js")
}

resource "aws_appsync_function" "query_profile_shares_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "QueryProfileSharesForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_profile_shares_for_delete_fn.js")
}

resource "aws_appsync_function" "query_profile_invites_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "QueryProfileInvitesForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_profile_invites_for_delete_fn.js")
}

resource "aws_appsync_function" "delete_profile_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "DeleteProfileSharesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_shares_fn.js")
}

resource "aws_appsync_function" "delete_profile_invites" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "DeleteProfileInvitesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_invites_fn.js")
}

resource "aws_appsync_function" "query_profile_campaigns_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "QueryProfileCampaignsForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_profile_campaigns_for_delete_fn.js")
}

resource "aws_appsync_function" "delete_profile_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "DeleteProfileCampaignsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_campaigns_fn.js")
}

resource "aws_appsync_function" "delete_profile_ownership" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "DeleteProfileOwnershipFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_ownership_fn.js")
}

resource "aws_appsync_function" "delete_profile_metadata" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "DeleteProfileMetadataFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_metadata_fn.js")
}

resource "aws_appsync_function" "check_catalog_usage" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "CheckCatalogUsageFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_catalog_usage_fn.js")
}

resource "aws_appsync_function" "delete_profile_orders_cascade_appsync" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.delete_profile_orders_cascade.name
  name        = "DeleteProfileOrdersCascadeFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_orders_cascade_fn.js")
}
