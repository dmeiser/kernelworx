# Cognito Module
# Matches actual AWS configuration

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in resource names (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for Cognito resources"
  type        = string
}

variable "login_domain" {
  description = "Fully qualified login domain (e.g., login.dev.kernelworx.app or login.kernelworx.app). When null, a globally-unique prefix domain is created instead."
  type        = string
  default     = null
}

variable "google_client_id" {
  description = "Google OAuth client ID for social login"
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth client secret for social login"
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "login_certificate_arn" {
  description = "ARN of ACM certificate for the Cognito login domain. Required when login_domain is set."
  type        = string
  default     = null
}

variable "login_certificate_validation" {
  description = "Certificate validation resource for the Cognito login domain"
  type        = any
  default     = null
}

variable "sms_role_arn" {
  description = "IAM role ARN used by Cognito for SMS/MFA delivery"
  type        = string
}

variable "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role to attach the scoped Cognito admin policy to"
  type        = string
}

variable "enable_google_idp" {
  type        = bool
  default     = false
  description = "Enable Google Identity Provider"
}

variable "pre_signup_lambda_arn" {
  description = "ARN of the Pre Sign-Up Lambda trigger. If null, no pre-signup trigger is configured."
  type        = string
  default     = null
}

variable "post_auth_lambda_arn" {
  description = "ARN of the Post Authentication Lambda trigger. If null, no post-auth trigger is configured."
  type        = string
  default     = null
}

variable "post_confirmation_lambda_arn" {
  description = "ARN of the Post Confirmation Lambda trigger. If null, no post-confirmation trigger is configured."
  type        = string
  default     = null
}

variable "enable_lambda_triggers" {
  description = "Whether Cognito Lambda triggers are configured. Use a static bool (known at plan time) rather than deriving from ARN nullability to avoid unknown count/for_each values during greenfield applies."
  type        = bool
  default     = false

  validation {
    condition = !var.enable_lambda_triggers || (
      var.pre_signup_lambda_arn != null &&
      var.post_auth_lambda_arn != null &&
      var.post_confirmation_lambda_arn != null
    )
    error_message = "When enable_lambda_triggers is true, pre_signup_lambda_arn, post_auth_lambda_arn, and post_confirmation_lambda_arn must all be non-null."
  }
}

variable "enable_webauthn" {
  description = "Enable WebAuthn (passkey) sign-in. When true, web_authn_relying_party_id must also be provided."
  type        = bool
  default     = false
}

variable "web_authn_relying_party_id" {
  description = "WebAuthn relying party ID (typically the apex domain, e.g. 'kernelworx.app'). Required when enable_webauthn = true."
  type        = string
  default     = null
}

variable "callback_urls" {
  description = "OAuth callback URLs for the Cognito User Pool client"
  type        = list(string)
}

variable "logout_urls" {
  description = "OAuth logout URLs for the Cognito User Pool client"
  type        = list(string)
}

variable "prevent_destroy" {
  description = "Set to false for ephemeral environments that must be destroyed after use."
  type        = bool
  default     = true
}

locals {
  user_pool_name    = "${var.name_prefix}-users-${var.region_abbrev}-${var.environment}"
  use_custom_domain = var.login_domain != null
  # Prefix domains must be globally unique across all AWS accounts.
  prefix_domain = "${var.name_prefix}-${var.region_abbrev}-${var.environment}"
  tags = {
    Environment = var.environment
    ManagedBy   = "opentofu"
    Project     = var.name_prefix
  }
}

# User Pool
resource "aws_cognito_user_pool" "main" {
  name                = local.user_pool_name
  deletion_protection = var.environment == "prod" ? "ACTIVE" : "INACTIVE"

  # Username configuration
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Password policy
  # Matches client-side validation in ForgotPasswordPage.tsx and SignupPage.tsx.
  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
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
    sns_region     = var.aws_region
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

  # WebAuthn / passkey sign-in
  # user_pool_tier must be ESSENTIALS or PLUS to use WebAuthn.
  user_pool_tier = var.enable_webauthn ? "ESSENTIALS" : "LITE"

  dynamic "sign_in_policy" {
    for_each = var.enable_webauthn ? [1] : []
    content {
      allowed_first_auth_factors = ["PASSWORD", "WEB_AUTHN"]
    }
  }

  dynamic "web_authn_configuration" {
    for_each = var.enable_webauthn ? [1] : []
    content {
      relying_party_id  = var.web_authn_relying_party_id
      user_verification = "preferred"
    }
  }

  # Lambda triggers (restored from CDK; omitted during CDK → OpenTofu migration)
  # Use a static block (not dynamic) so the block is always emitted; null values are
  # treated as "no trigger" by the provider without plan-time unknown issues.
  lambda_config {
    pre_sign_up         = var.pre_signup_lambda_arn
    post_authentication = var.post_auth_lambda_arn
    post_confirmation   = var.post_confirmation_lambda_arn
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# Lambda permissions - allow Cognito to invoke trigger functions
# Count is gated on the static enable_lambda_triggers flag only.  ARN nullability
# is intentionally NOT checked here: on greenfield applies the Lambda ARNs come
# from module outputs and are unknown during plan, which would make count unknown.
# The module-level variable validation still requires the ARNs to be non-null when
# triggers are enabled.
resource "aws_lambda_permission" "cognito_pre_signup" {
  count = var.enable_lambda_triggers ? 1 : 0

  statement_id  = "AllowCognitoInvokePreSignup"
  action        = "lambda:InvokeFunction"
  function_name = var.pre_signup_lambda_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

resource "aws_lambda_permission" "cognito_post_auth" {
  count = var.enable_lambda_triggers ? 1 : 0

  statement_id  = "AllowCognitoInvokePostAuth"
  action        = "lambda:InvokeFunction"
  function_name = var.post_auth_lambda_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

resource "aws_lambda_permission" "cognito_post_confirmation" {
  count = var.enable_lambda_triggers ? 1 : 0

  statement_id  = "AllowCognitoInvokePostConfirmation"
  action        = "lambda:InvokeFunction"
  function_name = var.post_confirmation_lambda_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

# Least-privilege Cognito admin policy for Lambda handlers.
# Scopes actions to the created user pool. Only actions actually used by the
# Lambda handlers (list/search users, list groups, delete/reset/link users) are
# granted. AdminCreateUser/AdminSetUserPassword/AdminGetUser are not used.
# kics-scan ignore-line
data "aws_iam_policy_document" "lambda_cognito_admin" {
  statement {
    effect = "Allow"
    actions = [
      "cognito-idp:ListUsers",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:AdminDeleteUser",
      "cognito-idp:AdminResetUserPassword",
      "cognito-idp:AdminLinkProviderForUser",
    ]
    resources = [aws_cognito_user_pool.main.arn]
  }
}

resource "aws_iam_role_policy" "lambda_cognito_admin" {
  name   = "cognito-admin"
  role   = regex("^.*/(.+)$", var.lambda_execution_role_arn)[0]
  policy = data.aws_iam_policy_document.lambda_cognito_admin.json
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
  depends_on   = [aws_cognito_identity_provider.google]

  # Note: generate_secret must not be specified for imported clients 
  # as it forces replacement

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_AUTH"
  ]

  # Include Google IdP when enabled for this environment
  supported_identity_providers = var.enable_google_idp ? ["COGNITO", "Google"] : ["COGNITO"]

  callback_urls = var.callback_urls

  logout_urls = var.logout_urls

  # Frontend uses the authorization-code flow via Amplify. Implicit flow is not
  # required, so it is omitted to reduce token exposure in the browser.
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["email", "openid", "profile"]

  prevent_user_existence_errors = "ENABLED"

  # Don't specify token validity - use defaults from imported state

  lifecycle {
    prevent_destroy = var.prevent_destroy
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
# Custom domain with ACM certificate (dev/prod)
resource "aws_cognito_user_pool_domain" "custom" {
  count = local.use_custom_domain ? 1 : 0

  domain          = var.login_domain
  user_pool_id    = aws_cognito_user_pool.main.id
  certificate_arn = var.login_certificate_arn

  lifecycle {
    prevent_destroy = var.prevent_destroy
    precondition {
      condition     = var.login_certificate_arn != null
      error_message = "login_certificate_arn is required when login_domain is set"
    }
    precondition {
      # Reference the validation resource so the custom domain waits for the login
      # certificate to validate. The ternary allows dev builds that omit it.
      condition     = var.login_certificate_validation != null ? try(length(var.login_certificate_validation.validation_record_fqdns) > 0, false) : true
      error_message = "Login certificate validation must complete before creating the Cognito custom domain"
    }
  }
}

# Prefix domain (ephemeral environments without custom domain / ACM)
resource "aws_cognito_user_pool_domain" "prefix" {
  count = local.use_custom_domain ? 0 : 1

  domain       = local.prefix_domain
  user_pool_id = aws_cognito_user_pool.main.id

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# Outputs
output "user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "ARN of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  description = "Endpoint of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.endpoint
}

output "client_id" {
  description = "ID of the Cognito User Pool client"
  value       = aws_cognito_user_pool_client.web.id
}

output "domain" {
  description = "Cognito User Pool domain (custom domain when configured, otherwise prefix domain)"
  value       = local.use_custom_domain ? aws_cognito_user_pool_domain.custom[0].domain : aws_cognito_user_pool_domain.prefix[0].domain
}

output "cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN backing the Cognito custom domain (null for prefix domains)"
  value       = local.use_custom_domain ? aws_cognito_user_pool_domain.custom[0].cloudfront_distribution_arn : null
}

output "cloudfront_domain" {
  description = "CloudFront domain name backing the Cognito custom domain (null for prefix domains)"
  value       = local.use_custom_domain ? aws_cognito_user_pool_domain.custom[0].cloudfront_distribution : null
}
