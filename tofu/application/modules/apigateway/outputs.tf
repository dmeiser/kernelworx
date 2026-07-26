# REST API Gateway Module Outputs

output "api_id" {
  value       = aws_api_gateway_rest_api.main.id
  description = "REST API Gateway ID"
}

output "api_execution_arn" {
  value       = aws_api_gateway_rest_api.main.execution_arn
  description = "REST API Gateway Execution ARN"
}

output "api_url" {
  value       = "https://${var.api_domain}"
  description = "REST API Gateway URL"
}

output "api_domain" {
  value       = aws_api_gateway_domain_name.api.domain_name
  description = "API Gateway custom domain name"
}

output "api_regional_domain_name" {
  value       = aws_api_gateway_domain_name.api.regional_domain_name
  description = "The regional domain name of the API Gateway custom domain (Route53 alias target)"
}
