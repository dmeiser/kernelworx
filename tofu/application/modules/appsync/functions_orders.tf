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

# === #679 public-order write path (anonymous, API-key auth mode) ===

# Step 5 of publicCreateOrder: a CLONE of validate_payment_method_fn.js, not a
# reuse. The authenticated original embeds the submitted method name in its
# rejection, which would let an anonymous caller iterate publicCreateOrder to
# enumerate the owner's stored method names; the clone answers both negative
# branches with one indistinguishable message and never names the method.
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

# Step 7 of publicCreateOrder: the order PutItem. Shares the pricing core
# (lib/line_items.js) with create_order_fn.js but reads the stash rather than
# ctx.args.input, and adds the public-order attributes (orderSource, status,
# receiptToken, split customer names, customerEmail).
resource "aws_appsync_function" "create_public_order" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.orders.name
  name        = "CreatePublicOrderFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_public_order_fn.js")
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
