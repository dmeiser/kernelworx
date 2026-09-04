# OpenTofu Ephemeral Environment Configuration
# Disposable per-PR / per-run stack for integration and E2E tests.
# Skips custom domains, ACM certificates, CloudFront, and Route53.

terraform {
  required_version = ">= 1.7.0"

  # State encryption configuration
  encryption {
    key_provider "pbkdf2" "main" {
      passphrase = var.encryption_passphrase
    }

    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.main
    }

    state {
      method   = method.aes_gcm.main
      enforced = true
    }

    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }

  backend "s3" {
    bucket       = "kernelworx-tofu-state-us-east-1-dev"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
    # key is supplied via tofu init -backend-config="key=application/ephemeral/<run-id>/terraform.tfstate"
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.56"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "kernelworx"
      Project     = "kernelworx"
      Environment = var.environment
      ManagedBy   = "opentofu"
    }
  }
}

# Variables
variable "encryption_passphrase" {
  type        = string
  sensitive   = true
  description = "Passphrase for state encryption (from ENCRYPTION_PASSPHRASE env var)"
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region"
}

variable "environment" {
  type        = string
  description = "Run identifier used to namespace all resources (e.g. pr-123)"
}

variable "region_abbrev" {
  type        = string
  default     = "ue1"
  description = "Abbreviated region for resource naming"
}

# Local computed values
locals {
  name_prefix = "kernelworx"

  cognito_callback_urls = [
    "http://localhost:4173",
    "http://localhost:4173/callback",
    "http://localhost:5173",
    "http://localhost:5173/callback",
  ]

  cognito_logout_urls = [
    "http://localhost:4173",
    "http://localhost:5173",
  ]
}

# Module instantiations
module "dynamodb" {
  source = "../../modules/dynamodb"

  environment                = var.environment
  region_abbrev              = var.region_abbrev
  name_prefix                = local.name_prefix
  prevent_destroy            = false
  enable_deletion_protection = false
}

module "s3" {
  source = "../../modules/s3"

  environment        = var.environment
  region_abbrev      = var.region_abbrev
  name_prefix        = local.name_prefix
  site_domain        = "localhost"
  extra_cors_origins = ["http://localhost:4173", "http://localhost:5173"]
  prevent_destroy    = false
  force_destroy      = true
}

module "iam" {
  source = "../../modules/iam"

  environment   = var.environment
  region_abbrev = var.region_abbrev
  name_prefix   = local.name_prefix

  dynamodb_table_arns         = module.dynamodb.table_arns
  exports_bucket_arn          = module.s3.exports_bucket_arn
  lambda_function_arns        = module.lambda.function_arns
  cloudfront_distribution_arn = null
  prevent_destroy             = false
}

module "lambda" {
  source = "../../modules/lambda"

  environment     = var.environment
  region_abbrev   = var.region_abbrev
  name_prefix     = local.name_prefix
  lambda_role_arn = module.iam.lambda_execution_role_arn
  # #121: admin-operations, delete-account, and pre-signup use the isolated
  # admin role that carries the Cognito admin policy.
  lambda_admin_role_arn = module.iam.lambda_admin_execution_role_arn
  exports_bucket_name   = module.s3.exports_bucket_name

  table_names = {
    accounts         = module.dynamodb.accounts_table_name
    catalogs         = module.dynamodb.catalogs_table_name
    profiles         = module.dynamodb.profiles_table_name
    campaigns        = module.dynamodb.campaigns_table_name
    orders           = module.dynamodb.orders_table_name
    shares           = module.dynamodb.shares_table_name
    invites          = module.dynamodb.invites_table_name
    shared_campaigns = module.dynamodb.shared_campaigns_table_name
  }

  user_pool_id = module.cognito.user_pool_id
}

module "cognito" {
  source = "../../modules/cognito"

  environment           = var.environment
  region_abbrev         = var.region_abbrev
  name_prefix           = local.name_prefix
  aws_region            = var.aws_region
  login_domain          = null
  login_certificate_arn = null
  sms_role_arn          = module.iam.cognito_sms_role_arn
  enable_google_idp     = false
  callback_urls         = local.cognito_callback_urls
  logout_urls           = local.cognito_logout_urls
  prevent_destroy       = false

  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  # #121: attach the Cognito admin policy to the isolated admin role, not the
  # shared execution role used by every Lambda.
  lambda_admin_execution_role_arn = module.iam.lambda_admin_execution_role_arn

  # Cognito trigger Lambdas
  enable_lambda_triggers       = true
  pre_signup_lambda_arn        = module.lambda.trigger_function_arns["pre-signup"]
  post_auth_lambda_arn         = module.lambda.trigger_function_arns["post-auth"]
  post_confirmation_lambda_arn = module.lambda.trigger_function_arns["post-auth"]

  # WebAuthn / passkey sign-in against localhost
  enable_webauthn            = true
  web_authn_relying_party_id = "localhost"
}

module "appsync" {
  source = "../../modules/appsync"

  environment              = var.environment
  region_abbrev            = var.region_abbrev
  name_prefix              = local.name_prefix
  api_domain               = null
  api_certificate_arn      = null
  appsync_service_role_arn = module.iam.appsync_service_role_arn
  user_pool_id             = module.cognito.user_pool_id
  aws_region               = var.aws_region
  prevent_destroy          = false

  dynamodb_table_names = module.dynamodb.table_names
  lambda_function_arns = module.lambda.function_arns
}

# Ephemeral has no CloudFront distribution, so the edge WAF feature is nulled:
# zero WAF objects, zero cost, zero behavior change.
module "waf" {
  source = "../../modules/waf"

  name_prefix = local.name_prefix
  environment = var.environment
  create      = false
}

# Outputs consumed by test scripts
output "appsync_api_url" {
  description = "GraphQL API URL for the AppSync API"
  value       = module.appsync.api_url
}

output "cognito_user_pool_id" {
  description = "ID of the ephemeral Cognito User Pool"
  value       = module.cognito.user_pool_id
}

output "cognito_client_id" {
  description = "Client ID for the ephemeral Cognito User Pool web application"
  value       = module.cognito.client_id
}

output "cognito_domain" {
  description = "Full Cognito prefix domain hostname (e.g. kernelworx-ue1-pr-123.auth.us-east-1.amazoncognito.com)"
  value       = "${module.cognito.domain}.auth.${var.aws_region}.amazoncognito.com"
}
