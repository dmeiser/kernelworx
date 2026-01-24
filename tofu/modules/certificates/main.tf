# ACM Certificates Module

variable "environment" {
  type = string
}

variable "domain" {
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
  value = aws_acm_certificate.site.arn
}

output "api_certificate_arn" {
  value = aws_acm_certificate.api.arn
}

output "login_certificate_arn" {
  value = aws_acm_certificate.login.arn
}
