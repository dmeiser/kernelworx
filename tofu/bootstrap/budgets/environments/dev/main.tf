# Kernelworx Development - AWS Budgets & Cost Monitoring

terraform {
  required_version = ">= 1.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket        = "kernelworx-dev-750620721302-tofu-state-ue1"
    key           = "bootstrap/dev/terraform.tfstate"
    region        = "us-east-1"
    encrypt       = true
    use_lockfile  = true
  }
}

provider "aws" {
  region  = "us-east-1"
  profile = "default"

  default_tags {
    tags = {
      Project     = "kernelworx"
      Environment = "dev"
      ManagedBy   = "opentofu"
      Component   = "budgets"
    }
  }
}

# Get current AWS account ID
data "aws_caller_identity" "current" {}

module "budget" {
  source = "../../modules/budget"

  name_prefix           = "kernelworx-dev"
  budget_name           = "KernelworxDev-Monthly"
  limit_amount          = "10.0"
  account_id            = data.aws_caller_identity.current.account_id
  alert_emails          = ["dave@repeatersolutions.com"]
  primary_alert_email   = "dave@repeatersolutions.com"
  
  # Create new anomaly monitor in dev
  create_anomaly_monitor = true
}
