# AppSync Functions for Catalog Operations

resource "aws_appsync_function" "get_catalog_for_delete" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "GetCatalogForDeleteFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_catalog_for_delete_fn.js")
}

resource "aws_appsync_function" "check_shared_campaign_usage" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "CheckSharedCampaignUsageFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_shared_campaign_usage_fn.js")
}

resource "aws_appsync_function" "delete_catalog_fn" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "DeleteCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/delete_catalog_fn.js")
}

# === #332: batch catalog resolution for Campaign/SharedCampaign list queries ===

# One BatchGetItem per list query for every catalogId in the campaign array
# (replaces the N+1 GetItem field resolver). Two variants with different
# deleted-catalog contracts: Campaign.catalog returned the raw item,
# SharedCampaign.catalog mapped soft-deleted catalogs to null.
resource "aws_appsync_function" "batch_get_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "BatchGetCatalogsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  # WARNING: templatefile() interpolates every `${...}` in the source; see the
  # header comment in batch_get_catalogs_fn.js. Do not add JS template
  # literals to that file.
  code = templatefile("${local.js_resolvers_dir}/batch_get_catalogs_fn.js", {
    table_name = var.dynamodb_table_names.catalogs
  })
}

resource "aws_appsync_function" "batch_get_shared_campaign_catalogs" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "BatchGetSharedCampaignCatalogsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = templatefile("${local.js_resolvers_dir}/batch_get_shared_campaign_catalogs_fn.js", {
    table_name = var.dynamodb_table_names.catalogs
  })
}

# First step of the Campaign.catalog / SharedCampaign.catalog pipeline field
# resolvers: surface a batch-resolved catalog from a parent list query.
resource "aws_appsync_function" "check_source_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.none.name
  name        = "CheckSourceCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/check_source_catalog_fn.js")
}

# GetItem fallback for singular Campaign.catalog fetches (unchanged contract
# from the removed VTL field resolver: raw item, soft-deleted included).
resource "aws_appsync_function" "get_campaign_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "GetCampaignCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_campaign_catalog_fn.js")
}

# GetItem fallback for singular SharedCampaign.catalog fetches (unchanged
# contract from the removed VTL field resolver: soft-deleted/missing -> null).
resource "aws_appsync_function" "get_shared_campaign_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "GetSharedCampaignCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/get_shared_campaign_catalog_fn.js")
}

# Query step of the listMySharedCampaigns pipeline (#332): the former unit
# resolver logic, unchanged, now running as a pipeline function.
resource "aws_appsync_function" "query_my_shared_campaigns" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "QueryMySharedCampaignsFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/list_my_shared_campaigns_resolver.js")
}

# Query step of the findSharedCampaigns pipeline (#332): the former unit
# resolver logic, unchanged, now running as a pipeline function.
resource "aws_appsync_function" "find_shared_campaigns_by_unit" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.shared_campaigns.name
  name        = "FindSharedCampaignsByUnitFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/find_shared_campaigns_resolver.js")
}
