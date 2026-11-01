# AppSync Functions for Sharing Operations

resource "aws_appsync_function" "verify_profile_owner_for_invite" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileOwnerForInviteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_owner_for_invite_fn.js")
}

# #453: confirms at redemption time that the profile is still owned by the
# invite's creation-time ownerAccountId (transfer moves the item to the new
# owner's partition, so a base-table GetItem under the old owner fails).
resource "aws_appsync_function" "verify_invite_owner_current" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyInviteOwnerCurrentFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_invite_owner_current_fn.js")
}

resource "aws_appsync_function" "create_invite" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "CreateInviteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_invite_fn.js")
}

resource "aws_appsync_function" "verify_profile_owner_for_revoke" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileOwnerForRevokeFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_owner_for_revoke_fn.js")
}

resource "aws_appsync_function" "delete_share" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "DeleteShareFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_share_fn.js")
}

resource "aws_appsync_function" "delete_profile_invite" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "DeleteProfileInviteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_profile_invite_fn.js")
}

resource "aws_appsync_function" "delete_invite_item" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "DeleteInviteItemFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_invite_item_fn.js")
}

resource "aws_appsync_function" "verify_profile_write_access" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileWriteAccessFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_write_access_fn.js")
}

resource "aws_appsync_function" "verify_profile_write_access_step2" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileWriteAccessStep2Fn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_write_access_fn.js")
}

resource "aws_appsync_function" "check_share_permissions" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckSharePermissionsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_share_permissions_fn.js")
}

resource "aws_appsync_function" "verify_profile_read_access" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileReadAccessFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_read_access_fn.js")
}

# Second invocation in the two-phase read owner check (#508), mirroring
# verify_profile_write_access_step2. AppSync rejects duplicate function IDs in
# a pipeline, so the second slot needs its own resource; it points at the same
# JS file, which branches on ctx.stash.isOwner set by the first call (Step 2
# runs the GSI locator only for non-owners).
resource "aws_appsync_function" "verify_profile_read_access_step2" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileReadAccessStep2Fn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_read_access_fn.js")
}

resource "aws_appsync_function" "check_share_read_permissions" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckShareReadPermissionsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_share_read_permissions_fn.js")
}

resource "aws_appsync_function" "verify_profile_owner_for_share" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "VerifyProfileOwnerForShareFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_profile_owner_for_share_fn.js")
}

resource "aws_appsync_function" "lookup_account_by_email" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "LookupAccountByEmailFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_account_by_email_fn.js")
}

resource "aws_appsync_function" "check_existing_share" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckExistingShareFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_existing_share_fn.js")
}

resource "aws_appsync_function" "create_share" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CreateShareFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_share_fn.js")
}

resource "aws_appsync_function" "lookup_invite" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "LookupInviteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_invite_fn.js")
}

resource "aws_appsync_function" "mark_invite_used" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.invites.name
  name        = "MarkInviteUsedFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/mark_invite_used_fn.js")
}

# listMyShares pipeline (Query) - migrated from the list-my-shares Lambda (#334)
resource "aws_appsync_function" "query_my_shares" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "QueryMySharesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_my_shares_fn.js")
}

resource "aws_appsync_function" "batch_get_shared_profiles" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.profiles.name
  name        = "BatchGetSharedProfilesFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  # templatefile() reads the esbuild bundle in appsync/dist/, which strips
  # ordinary comments, so a dollar-brace sequence that survives bundling is
  # interpolated as a Terraform expression: in a string literal it aborts every
  # plan/apply with "Invalid expression". `${table_name}` is the only intended
  # placeholder; escape a literal as `$${...}` or switch this to file() (#284
  # defers that switch). Enforced by
  # tests/unit/check_templatefile_escaping.test.ts (#570).
  code = templatefile("${local.js_resolvers_dir}/batch_get_shared_profiles_fn.js", {
    table_name = var.dynamodb_table_names.profiles
  })
}
