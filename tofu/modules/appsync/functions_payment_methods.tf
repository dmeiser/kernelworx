# AppSync Functions for Payment Methods Operations

resource "aws_appsync_function" "get_payment_methods" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "GetPaymentMethodsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_payment_methods_fn.js")
}

resource "aws_appsync_function" "inject_global_payment_methods" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.payment_methods_none.name
  name        = "InjectGlobalPaymentMethodsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/inject_global_payment_methods_fn.js")
}

resource "aws_appsync_function" "set_owner_account_id_in_stash" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.payment_methods_none.name
  name        = "SetOwnerAccountIdInStashFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/set_owner_account_id_in_stash_fn.js")
}

resource "aws_appsync_function" "check_payment_methods_access" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shares.name
  name        = "CheckPaymentMethodsAccessFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_payment_methods_access_fn.js")
}

resource "aws_appsync_function" "get_owner_payment_methods" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "GetOwnerPaymentMethodsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_owner_payment_methods_fn.js")
}

resource "aws_appsync_function" "filter_payment_methods_by_access" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.filter_payment_methods_none.name
  name        = "FilterPaymentMethodsByAccessFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/filter_payment_methods_by_access_fn.js")
}

resource "aws_appsync_function" "validate_payment_method_appsync" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.validate_payment_method.name
  name        = "ValidatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

resource "aws_appsync_function" "validate_create_payment_method" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "ValidateCreatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_create_payment_method_fn.js")
}

resource "aws_appsync_function" "create_payment_method" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "CreatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_payment_method_fn.js")
}

resource "aws_appsync_function" "validate_update_payment_method" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "ValidateUpdatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_update_payment_method_fn.js")
}

resource "aws_appsync_function" "update_payment_method" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "UpdatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_payment_method_fn.js")
}

resource "aws_appsync_function" "get_payment_method_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "GetPaymentMethodForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_payment_method_for_delete_fn.js")
}

resource "aws_appsync_function" "delete_payment_method_from_prefs" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "DeletePaymentMethodFromPrefsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_payment_method_from_prefs_fn.js")
}
