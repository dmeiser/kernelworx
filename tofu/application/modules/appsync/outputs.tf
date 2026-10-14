# AppSync Module Outputs

output "api_id" {
  value       = aws_appsync_graphql_api.main.id
  description = "AppSync GraphQL API ID"
}

output "api_url" {
  value       = aws_appsync_graphql_api.main.uris["GRAPHQL"]
  description = "AppSync GraphQL API URL"
}

output "api_domain" {
  value       = var.api_domain != null ? aws_appsync_domain_name.api[0].domain_name : null
  description = "AppSync custom domain name (null when using the AWS-managed URL)"
}

output "api_arn" {
  value       = aws_appsync_graphql_api.main.arn
  description = "AppSync GraphQL API ARN"
}

# The public-orders API key (#679 rev 7). Deliberately NOT sensitive: it is
# baked into the public frontend bundle (VITE_APPSYNC_API_KEY) by design, and it
# grants access only to the @aws_api_key root fields, each of which still
# requires a valid per-campaign bearer token. It must be readable from
# `tofu output -json` so scripts/generate_integration_env.py can write the
# TEST_APPSYNC_API_KEY / VITE_APPSYNC_API_KEY managed keys.
#
# The provider marks `key` sensitive, and OpenTofu rejects any root-module
# output that exports a sensitive value without `sensitive = true`. Since this
# key is public by design, nonsensitive() strips the mark here, at the one
# module boundary every environment's `appsync_api_key` output reads through,
# so all of them stay unmasked for `tofu output -raw` / `-json` consumers.
output "api_key" {
  value       = nonsensitive(aws_appsync_api_key.public_orders.key)
  description = "AppSync API key for the public-orders (@aws_api_key) fields"
}

output "api_key_id" {
  value       = aws_appsync_api_key.public_orders.id
  description = "AppSync public-orders API key ID (for import and recovery tooling)"
}
