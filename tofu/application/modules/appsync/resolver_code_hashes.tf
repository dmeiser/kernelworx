# Code-hash triggers for createOrder pipeline resolver and functions.
# When the underlying JS changes, these terraform_data resources change,
# forcing replacement of the target resolver/function so the new code is
# guaranteed to be deployed (workaround for AppSync in-place update taint).

resource "terraform_data" "create_order_resolver_code" {
  input = filesha256("${local.js_resolvers_dir}/create_order_pipeline_resolver.js")
}

resource "terraform_data" "verify_profile_write_access_code" {
  input = filesha256("${local.js_resolvers_dir}/verify_profile_write_access_fn.js")
}

resource "terraform_data" "check_share_permissions_code" {
  input = filesha256("${local.js_resolvers_dir}/check_share_permissions_fn.js")
}

resource "terraform_data" "validate_payment_method_appsync_code" {
  input = filesha256("${local.js_resolvers_dir}/lambda_passthrough_resolver.js")
}

resource "terraform_data" "get_campaign_for_order_code" {
  input = filesha256("${local.js_resolvers_dir}/get_campaign_for_order_fn.js")
}

resource "terraform_data" "get_catalog_code" {
  input = filesha256("${local.js_resolvers_dir}/get_catalog_fn.js")
}

resource "terraform_data" "create_order_function_code" {
  input = filesha256("${local.js_resolvers_dir}/create_order_fn.js")
}
