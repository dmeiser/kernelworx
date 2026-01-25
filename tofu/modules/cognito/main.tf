# Cognito Module
# Matches actual AWS configuration

variable "environment" {
  type = string
}

variable "region_abbrev" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "domain" {
  type = string
}

variable "google_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "login_certificate_arn" {
  type = string
}

variable "sms_role_arn" {
  type = string
}

variable "enable_google_idp" {
  type        = bool
  default     = false
  description = "Enable Google Identity Provider"
}

locals {
  user_pool_name = "${var.name_prefix}-users-${var.region_abbrev}-${var.environment}"
  login_domain   = "login.${var.environment}.${var.domain}"
  tags = {
    Environment = var.environment
    ManagedBy   = "opentofu"
    Project     = var.name_prefix
  }
}

# User Pool
resource "aws_cognito_user_pool" "main" {
  name = local.user_pool_name

  # Username configuration
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Password policy
  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # MFA configuration
  mfa_configuration = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  # SMS configuration for MFA
  sms_configuration {
    external_id    = "kernelworx-sms-role"
    sns_caller_arn = var.sms_role_arn
    sns_region     = "us-east-1"
  }

  # Account recovery
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Email configuration
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Schema attributes
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  # User attribute update settings
  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

# Google Identity Provider (optional - not currently configured)
resource "aws_cognito_identity_provider" "google" {
  count = var.enable_google_idp ? 1 : 0

  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id                     = var.google_client_id
    client_secret                 = var.google_client_secret
    authorize_scopes              = "email openid profile"
    attributes_url                = "https://people.googleapis.com/v1/people/me?personFields="
    attributes_url_add_attributes = "true"
    authorize_url                 = "https://accounts.google.com/o/oauth2/v2/auth"
    oidc_issuer                   = "https://accounts.google.com"
    token_request_method          = "POST"
    token_url                     = "https://www.googleapis.com/oauth2/v4/token"
  }

  attribute_mapping = {
    email    = "email"
    username = "sub"
    name     = "name"
  }
}

# User Pool Client - matches actual AWS config
resource "aws_cognito_user_pool_client" "web" {
  name         = "KernelWorx-Web"
  user_pool_id = aws_cognito_user_pool.main.id

  # Note: generate_secret must not be specified for imported clients 
  # as it forces replacement

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_AUTH"
  ]

  # Currently only COGNITO (Google IdP not yet configured)
  supported_identity_providers = ["COGNITO"]

  callback_urls = [
    "http://localhost:5173",
    "https://dev.kernelworx.app",
    "https://dev.kernelworx.app/callback",
    "https://local.dev.appworx.app:5173"
  ]

  logout_urls = [
    "http://localhost:5173",
    "https://dev.kernelworx.app",
    "https://local.dev.appworx.app:5173"
  ]

  allowed_oauth_flows                  = ["code", "implicit"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["email", "openid", "profile"]

  prevent_user_existence_errors = "ENABLED"

  # Don't specify token validity - use defaults from imported state

  lifecycle {
    prevent_destroy = true
    # Ignore certain attributes that may differ from actual AWS state
    ignore_changes = [
      access_token_validity,
      id_token_validity,
      refresh_token_validity,
      token_validity_units,
    ]
  }
}

# User Pool Domain
resource "aws_cognito_user_pool_domain" "custom" {
  domain          = local.login_domain
  user_pool_id    = aws_cognito_user_pool.main.id
  certificate_arn = var.login_certificate_arn

  lifecycle {
    prevent_destroy = true
  }
}

# Outputs
output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  value = aws_cognito_user_pool.main.endpoint
}

output "client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "domain" {
  value = aws_cognito_user_pool_domain.custom.domain
}
