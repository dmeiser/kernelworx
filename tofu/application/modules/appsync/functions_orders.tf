# AppSync Functions for Order Operations

resource "aws_appsync_function" "lookup_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "LookupOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_order_fn.js")
}

resource "aws_appsync_function" "get_catalog_for_update_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "GetCatalogForUpdateOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_catalog_for_update_order_fn.js")
}

resource "aws_appsync_function" "fetch_catalog_for_update" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "FetchCatalogForUpdateFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/fetch_catalog_for_update_fn.js")
}

resource "aws_appsync_function" "update_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "UpdateOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_order_fn.js")
}

resource "aws_appsync_function" "lookup_order_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "LookupOrderForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_order_for_delete_fn.js")
}

resource "aws_appsync_function" "delete_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "DeleteOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_order_fn.js")
}

resource "aws_appsync_function" "verify_order_delete_propagation" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "VerifyOrderDeletePropagationFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/verify_order_delete_propagation_fn.js")
}

resource "aws_appsync_function" "get_campaign_for_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "GetCampaignForOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_campaign_for_order_fn.js")
}

resource "aws_appsync_function" "get_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "GetCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_catalog_fn.js")
}

resource "aws_appsync_function" "create_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "CreateOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_order_fn.js")
}

resource "aws_appsync_function" "query_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "QueryOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_order_fn.js")
}

resource "aws_appsync_function" "return_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.none.name
  name        = "ReturnOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/return_order_fn.js")
}

resource "aws_appsync_function" "lookup_campaign_for_orders" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.campaigns.name
  name        = "LookupCampaignForOrdersFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/lookup_campaign_for_orders_fn.js")
}

resource "aws_appsync_function" "query_orders_by_campaign" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "QueryOrdersByCampaignFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/query_orders_by_campaign_fn.js")
}

# publicCreateOrder pipeline step 5 (#679): the no-oracle payment-method clone.
# CLONE of validate_payment_method_fn.js: both rejections (off the allowlist,
# no longer on the account) share one message and never echo the submitted
# name, so the mutation cannot enumerate the owner's stored method names.
resource "aws_appsync_function" "validate_payment_method_public" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.accounts.name
  name        = "ValidatePaymentMethodPublicFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/validate_payment_method_public_fn.js")
}

# publicCreateOrder pipeline step 7 (#679): the order write. A CLONE of
# create_order_fn.js that reads the stash (not ctx.args.input) and adds
# orderSource, status, and the minted receiptToken.
resource "aws_appsync_function" "create_public_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "CreatePublicOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  # templatefile() (not file()): the write is a TransactWriteItems spanning
  # two tables, and each transact item's `table` field must be the REAL AWS
  # table name - AppSync takes it literally rather than defaulting to the
  # datasource's table. The hardcoded logical names 'Orders'/'Campaigns'
  # produced AccessDenied on table/Orders in the deployed runtime. The
  # escaping rules are the module-wide ones (#570): every surviving
  # dollar-brace sequence is interpolated, so a literal must be written $${...}.
  code = templatefile("${local.js_resolvers_dir}/create_public_order_fn.js", {
    orders_table_name    = var.dynamodb_table_names.orders
    campaigns_table_name = var.dynamodb_table_names.campaigns
  })
}

# publicCreateOrder pipeline step 8 (KW-PUBLIC-ORDERS-SES-1): the best-effort
# order-confirmation email invoke on the public-orders Lambda. Runs AFTER the
# order write; both the handler and this function's response() swallow every
# failure so an email problem can never fail a committed order. The payload
# carries the explicit "send_order_emails" operation discriminator (there is
# no info.fieldName in an Invoke payload).
resource "aws_appsync_function" "send_public_order_emails" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.public_orders.name
  name        = "SendPublicOrderEmailsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/send_public_order_emails_fn.js")
}
