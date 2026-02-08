# AppSync Functions for Catalog Operations

resource "aws_appsync_function" "create_catalog" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "CreateCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/create_catalog_fn.js")
}

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

resource "aws_appsync_function" "update_catalog_fn" {
  api_id      = aws_appsync_graphql_api.main.id
  data_source = aws_appsync_datasource.catalogs.name
  name        = "UpdateCatalogFn${local.env_suffix}"

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }

  code = file("${local.js_resolvers_dir}/update_catalog_fn.js")
}
