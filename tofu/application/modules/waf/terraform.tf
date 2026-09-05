terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.56"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
  }
}
