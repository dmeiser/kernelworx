# Kernelworx Production - AWS Budgets & Cost Monitoring

terraform {
  required_version = ">= 1.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local backend for budgets project (separate from main infrastructure)
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region  = "us-east-1"
  profile = "kernelworx-prod"

  default_tags {
    tags = {
      Project     = "kernelworx"
      Environment = "prod"
      ManagedBy   = "opentofu"
      Component   = "budgets"
    }
  }
}

# Get current AWS account ID
data "aws_caller_identity" "current" {}

locals {
  # Prod account anomaly monitor ARN (to be discovered)
  existing_monitor_arn = "arn:aws:ce::${data.aws_caller_identity.current.account_id}:anomalymonitor/DEFAULT"
}

module "budget" {
  source = "../../modules/budget"

  name_prefix           = "kernelworx-prod"
  budget_name           = "KernelworxProduction-Monthly"
  limit_amount          = "10.0"
  account_id            = data.aws_caller_identity.current.account_id
  alert_emails          = ["dave@repeatersolutions.com"]
  primary_alert_email   = "dave@repeatersolutions.com"
  existing_monitor_arn  = local.existing_monitor_arn
}
