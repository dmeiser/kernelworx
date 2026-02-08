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
