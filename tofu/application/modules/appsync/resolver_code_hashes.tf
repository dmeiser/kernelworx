# Code-hash triggers for createOrder pipeline resolver.
# When the underlying JS changes, this terraform_data resource changes,
# forcing replacement of the target resolver so the new code is guaranteed
# to be deployed (workaround for AppSync in-place update taint).

resource "terraform_data" "create_order_resolver_code" {
  input = filesha256("${local.js_resolvers_dir}/create_order_pipeline_resolver.js")
}
