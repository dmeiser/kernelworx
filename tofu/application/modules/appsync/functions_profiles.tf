# AppSync Functions for Profile and Account Operations

resource "aws_appsync_function" "get_my_account_exact" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "GetMyAccountExactFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_my_account_exact_fn.js")
}

resource "aws_appsync_function" "ensure_my_account_exists" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "EnsureMyAccountExistsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/ensure_my_account_exists_fn.js")
}

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

resource "aws_appsync_function" "delete_profile_cascade" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.delete_profile_cascade.name
  name        = "DeleteProfileCascadeFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_cascade_fn.js")
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


# listMyProfiles pipeline functions (#331): the list query itself, plus a
# BatchGetItem step that attaches latestCampaign to every profile carrying
# the denormalized latestCampaignId field in a single call per page.
resource "aws_appsync_function" "list_my_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "ListMyProfilesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_profiles_fn.js")
}

resource "aws_appsync_function" "batch_latest_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "BatchLatestCampaignsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  # WARNING: templatefile() interpolates every `${...}` sequence in the source as a
  # Terraform variable reference. The bundled source keeps only the intended
  # `${campaigns_table_name}` placeholder; any JS template literal added to the
  # source will either fail the plan or be silently substituted. Do not add
  # `${...}` to the source without also switching this to file() (#284 defers
  # that switch).
  code = templatefile("${local.js_resolvers_dir}/batch_latest_campaigns_fn.js", {
    campaigns_table_name = var.dynamodb_table_names.campaigns
  })
}
