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

# Batch-generate presigned QR code URLs for all payment methods in one Lambda
# invocation (replaces the per-method PaymentMethod.qrCodeUrl field resolver).
# Must run last in the myPaymentMethods and paymentMethodsForProfile pipelines.
resource "aws_appsync_function" "batch_qr_urls" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.generate_qr_presigned_url.name
  name        = "BatchQrUrlsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/batch_qr_urls_fn.js")
}

# Invoke the confirm-qr-upload Lambda as the first step of the
# confirmPaymentMethodQRCodeUpload pipeline. The batch_qr_urls function signs
# the returned key as the pipeline's last step (#330).
resource "aws_appsync_function" "confirm_qr_upload" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.confirm_qr_upload.name
  name        = "ConfirmQRUploadFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/confirm_qr_upload_fn.js")
}

resource "aws_appsync_function" "validate_payment_method_appsync" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "ValidatePaymentMethodFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_payment_method_fn.js")
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

resource "aws_appsync_function" "delete_payment_method_qr_code" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.delete_qr_code.name
  name        = "DeletePaymentMethodQRCodeFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_payment_method_qr_code_fn.js")
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
