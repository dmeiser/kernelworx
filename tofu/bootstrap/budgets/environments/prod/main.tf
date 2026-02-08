# Kernelworx Production - AWS Budgets & Cost Monitoring

terraform {
  required_version = ">= 1.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket        = "kernelworx-prod-660261898986-tofu-state-ue1"
    key           = "bootstrap/prod/terraform.tfstate"
    region        = "us-east-1"
    encrypt       = true
    use_lockfile  = true
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

module "budget" {
  source = "../../modules/budget"

  name_prefix           = "kernelworx-prod"
  budget_name           = "KernelworxProduction-Monthly"
  limit_amount          = "10.0"
  account_id            = data.aws_caller_identity.current.account_id
  alert_emails          = ["dave@repeatersolutions.com"]
  primary_alert_email   = "dave@repeatersolutions.com"
  
  # Use existing dimensional monitor (AWS limit: 1 per account)
  create_anomaly_monitor = false
  existing_monitor_arn   = "arn:aws:ce::660261898986:anomalymonitor/3ecf6158-f232-4606-8643-f90428bd290f"
}
