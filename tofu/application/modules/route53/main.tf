# Route53 DNS Records Module
# Manages application-specific DNS records (API, login, etc.)

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "domain" {
  type        = string
  description = "Base domain for DNS records"
}

variable "cloudfront_domain_name" {
  description = "CloudFront distribution domain name for static site"
  type        = string
}

variable "appsync_api_url" {
  description = "AppSync API URL (HTTPS endpoint)"
  type        = string
}

variable "cognito_domain" {
  description = "Cognito custom domain"
  type        = string
}

variable "api_certificate_arn" {
  description = "ARN of the ACM certificate for the API domain"
  type        = string
}

variable "login_certificate_arn" {
  description = "ARN of the ACM certificate for the login domain"
  type        = string
}

variable "cognito_cloudfront_domain" {
  description = "CloudFront domain backing the Cognito custom domain"
  type        = string
}

variable "api_validation_records" {
  description = "Validation records for API certificate"
  type = list(object({
    name   = string
    record = string
    type   = string
  }))
}

variable "login_validation_records" {
  description = "Validation records for login certificate"
  type = list(object({
    name   = string
    record = string
    type   = string
  }))
}

variable "site_validation_records" {
  description = "Validation records for site certificate"
  type = list(object({
    name   = string
    record = string
    type   = string
  }))
}

# Locals for domain construction
locals {
  is_prod   = var.environment == "prod"
  zone_name = local.is_prod ? "${var.domain}." : "${var.environment}.${var.domain}."

  # Record names relative to the hosted zone
  site_record_name  = ""      # zone apex for both prod and dev
  api_record_name   = "api"
  login_record_name = "login"
}

# Data source to lookup the hosted zone
data "aws_route53_zone" "main" {
  name         = local.zone_name
  private_zone = false
}

# Zone apex / site (A alias to CloudFront)
resource "aws_route53_record" "site" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.site_record_name
  type    = "A"

  allow_overwrite = true

  alias {
    name                   = var.cloudfront_domain_name
    zone_id                = "Z2FDTNDATAQYW2" # CloudFront hosted zone ID
    evaluate_target_health = false
  }
}

# API subdomain (CNAME to AppSync)
# Extract domain from AppSync URL (https://xyz.appsync-api.region.amazonaws.com/graphql)
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.api_record_name
  type    = "CNAME"
  ttl     = 300
  allow_overwrite = true

  records = [
    replace(replace(var.appsync_api_url, "https://", ""), "/graphql", "")
  ]
}

# Login subdomain (Cognito custom domain)
# This will be an A record with alias to CloudFront if using custom domain
resource "aws_route53_record" "login" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.login_record_name
  type    = "A"
  allow_overwrite = true

  alias {
    name                   = var.cognito_cloudfront_domain
    zone_id                = "Z2FDTNDATAQYW2" # CloudFront hosted zone ID (global)
    evaluate_target_health = false
  }
}

# ACM Certificate validation records
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for rec in concat(
      var.api_validation_records,
      var.login_validation_records,
      var.site_validation_records
    ) :
    # Strip trailing dot to create stable keys
    trimspace(trimsuffix(rec.name, ".")) => rec
  }

  allow_overwrite = true

  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.record]
}

# Outputs
output "zone_id" {
  description = "Route53 hosted zone ID"
  value       = data.aws_route53_zone.main.zone_id
}

output "zone_name_servers" {
  description = "Nameservers for the zone"
  value       = data.aws_route53_zone.main.name_servers
}

output "api_fqdn" {
  description = "Fully qualified domain name for API"
  value       = aws_route53_record.api.fqdn
}

output "login_fqdn" {
  description = "Fully qualified domain name for login"
  value       = aws_route53_record.login.fqdn
}

output "site_fqdn" {
  description = "Fully qualified domain name for site apex"
  value       = aws_route53_record.site.fqdn
}
output "cert_validation_records" {
  description = "Certificate validation Route53 records"
  value       = [for rec in aws_route53_record.cert_validation : rec]
}
