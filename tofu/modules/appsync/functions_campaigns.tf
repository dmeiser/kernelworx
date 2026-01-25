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

  code = file("${local.js_resolvers_dir}/delete_campaign_orders_fn.js")
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
