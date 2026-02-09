# ACM Certificates Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "domain" {
  description = "Base domain name used for site/api/login certificates"
  type = string
}

locals {
  site_domain  = "${var.environment}.${var.domain}"
  api_domain   = "api.${var.environment}.${var.domain}"
  login_domain = "login.${var.environment}.${var.domain}"
}

# Note: These certificates were created manually/by CDK and validated
# They are imported here for management, not created fresh

resource "aws_acm_certificate" "site" {
  domain_name       = local.site_domain
  validation_method = "DNS"

  lifecycle {
    prevent_destroy = true
    create_before_destroy = true
  }

  tags = {
    Name = "site-${var.environment}"
  }
}

resource "aws_acm_certificate" "api" {
  domain_name       = local.api_domain
  validation_method = "DNS"

  lifecycle {
    prevent_destroy = true
    create_before_destroy = true
  }

  tags = {
    Name = "api-${var.environment}"
  }
}

resource "aws_acm_certificate" "login" {
  domain_name       = local.login_domain
  validation_method = "DNS"

  lifecycle {
    prevent_destroy = true
    create_before_destroy = true
  }

  tags = {
    Name = "login-${var.environment}"
  }
}

# Outputs
output "site_certificate_arn" {
  description = "ARN of the ACM certificate for the site domain"
  value       = aws_acm_certificate.site.arn
}

output "api_certificate_arn" {
  description = "ARN of the ACM certificate for the API domain"
  value       = aws_acm_certificate.api.arn
}

output "login_certificate_arn" {
  description = "ARN of the ACM certificate for the login domain"
  value       = aws_acm_certificate.login.arn
}

output "api_validation_records" {
  description = "Validation records for API certificate"
  value = [for dvo in aws_acm_certificate.api.domain_validation_options : {
    name   = dvo.resource_record_name
    record = dvo.resource_record_value
    type   = dvo.resource_record_type
  }]
}

output "login_validation_records" {
  description = "Validation records for login certificate"
  value = [for dvo in aws_acm_certificate.login.domain_validation_options : {
    name   = dvo.resource_record_name
    record = dvo.resource_record_value
    type   = dvo.resource_record_type
  }]
}
output "site_validation_records" {
  description = "Validation records for site certificate"
  value = [for dvo in aws_acm_certificate.site.domain_validation_options : {
    name   = dvo.resource_record_name
    record = dvo.resource_record_value
    type   = dvo.resource_record_type
  }]
}