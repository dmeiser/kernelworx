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

output "api_key" {
  value       = aws_appsync_api_key.public.key
  sensitive   = true
  description = "API key for the API_KEY auth mode (public order surface). A transport credential threaded into the frontend build as VITE_APPSYNC_API_KEY for the public browser bundle (the public pages consume it); the provider marks the computed key sensitive, so the output inherits that flag."
}
