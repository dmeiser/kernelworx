# OpenTofu Dev Environment Configuration

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
    bucket       = "kernelworx-tofu-state-ue1"
    key          = "kernelworx/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
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
  default     = "dev"
  description = "Environment name"
}

variable "region_abbrev" {
  type        = string
  default     = "ue1"
  description = "Abbreviated region for resource naming"
}

variable "domain" {
  type        = string
  default     = "kernelworx.app"
  description = "Base domain name"
}

variable "google_client_id" {
  type        = string
  sensitive   = true
  description = "Google OAuth client ID"
}

variable "google_client_secret" {
  type        = string
  sensitive   = true
  description = "Google OAuth client secret"
}

# Local computed values
locals {
  name_prefix     = "kernelworx"
  site_domain     = "${var.environment}.${var.domain}"
}

# Module instantiations
module "dynamodb" {
  source = "../../modules/dynamodb"

  environment   = var.environment
  region_abbrev = var.region_abbrev
  name_prefix   = local.name_prefix
}

module "s3" {
  source = "../../modules/s3"

  environment   = var.environment
  region_abbrev = var.region_abbrev
  name_prefix   = local.name_prefix
  domain        = var.domain
}

module "iam" {
  source = "../../modules/iam"

  environment   = var.environment
  region_abbrev = var.region_abbrev
  name_prefix   = local.name_prefix

  dynamodb_table_arns = module.dynamodb.table_arns
  exports_bucket_arn  = module.s3.exports_bucket_arn
  lambda_function_arns = module.lambda.function_arns
}

module "certificates" {
  source = "../../modules/certificates"

  environment = var.environment
  domain      = var.domain
}

module "cognito" {
  source = "../../modules/cognito"

  environment          = var.environment
  region_abbrev        = var.region_abbrev
  name_prefix          = local.name_prefix
  domain               = var.domain
  google_client_id     = var.google_client_id
  google_client_secret = var.google_client_secret
  login_certificate_arn = module.certificates.login_certificate_arn
  sms_role_arn         = module.iam.cognito_sms_role_arn
  enable_google_idp    = false  # Not currently configured in AWS
}

module "lambda" {
  source = "../../modules/lambda"

  environment         = var.environment
  region_abbrev       = var.region_abbrev
  name_prefix         = local.name_prefix
  lambda_role_arn     = module.iam.lambda_execution_role_arn
  exports_bucket_name = module.s3.exports_bucket_name
  
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

module "appsync" {
  source = "../../modules/appsync"

  environment              = var.environment
  region_abbrev            = var.region_abbrev
  name_prefix              = local.name_prefix
  domain                   = var.domain
  api_certificate_arn      = module.certificates.api_certificate_arn
  appsync_service_role_arn = module.iam.appsync_service_role_arn
  user_pool_id             = module.cognito.user_pool_id
  aws_region               = var.aws_region
  
  dynamodb_table_names = module.dynamodb.table_names
  lambda_function_arns = module.lambda.function_arns
}

module "cloudfront" {
  source = "../../modules/cloudfront"

  environment          = var.environment
  domain               = var.domain
  site_certificate_arn = module.certificates.site_certificate_arn
  static_bucket_id     = module.s3.static_bucket_id
  static_bucket_arn    = module.s3.static_bucket_arn
  static_bucket_regional_domain = module.s3.static_bucket_regional_domain
}

module "route53" {
  source = "../../modules/route53"

  environment            = var.environment
  domain                 = var.domain
  appsync_api_url        = module.appsync.api_url
  cognito_domain         = module.cognito.domain
  cognito_cloudfront_domain = module.cognito.cloudfront_domain
  cloudfront_domain_name = module.cloudfront.distribution_domain
  api_certificate_arn    = module.certificates.api_certificate_arn
  login_certificate_arn  = module.certificates.login_certificate_arn
  api_validation_records   = module.certificates.api_validation_records
  login_validation_records = module.certificates.login_validation_records
}

# Outputs
output "cognito_user_pool_id" {
  description = "ID of the Cognito User Pool for authentication"
  value       = module.cognito.user_pool_id
}

output "cognito_client_id" {
  description = "Client ID for the Cognito User Pool web application"
  value       = module.cognito.client_id
}

output "appsync_api_url" {
  description = "GraphQL API URL for the AppSync API"
  value       = module.appsync.api_url
}

output "cloudfront_distribution_id" {
  description = "ID of the CloudFront distribution serving the site"
  value       = module.cloudfront.distribution_id
}

output "site_url" {
  description = "Public URL of the application site"
  value       = "https://${local.site_domain}"
}
