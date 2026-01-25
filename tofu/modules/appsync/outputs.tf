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
  value       = aws_appsync_domain_name.api.domain_name
  description = "AppSync custom domain name"
}

output "api_arn" {
  value       = aws_appsync_graphql_api.main.arn
  description = "AppSync GraphQL API ARN"
}
