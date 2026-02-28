# S3 Buckets Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "region_abbrev" {
  description = "Short region code used in bucket names (e.g., ue1)"
  type = string
}

variable "name_prefix" {
  description = "Global name prefix for S3 buckets"
  type = string
}

variable "site_domain" {
  description = "Fully qualified site domain for CORS allowed origins (e.g., dev.kernelworx.app or kernelworx.app)"
  type = string
}

locals {
  bucket_suffix = "-${var.region_abbrev}-${var.environment}"
}

# Static Assets Bucket
# NOTE: S3 access logging is disabled to minimize AWS costs for this volunteer project.
# Logging would incur additional S3 storage costs for log files.
# kics-scan ignore-line
resource "aws_s3_bucket" "static" {
  bucket = "${var.name_prefix}-static${local.bucket_suffix}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "static" {
  bucket = aws_s3_bucket.static.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static" {
  bucket = aws_s3_bucket.static.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "static" {
  bucket = aws_s3_bucket.static.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Exports Bucket
# NOTE: S3 access logging is disabled to minimize AWS costs for this volunteer project.
# Logging would incur additional S3 storage costs for log files.
# kics-scan ignore-line
resource "aws_s3_bucket" "exports" {
  bucket = "${var.name_prefix}-exports${local.bucket_suffix}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket = aws_s3_bucket.exports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    id     = "expire-old-reports"
    status = "Enabled"

    expiration {
      days = 7
    }

    filter {
      prefix = "reports/"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  cors_rule {
    # Restrict headers to those needed for S3 uploads
    allowed_headers = [
      "Content-Type",
      "Content-MD5",
      "x-amz-date",
      "Authorization"
    ]
    allowed_methods = ["GET", "PUT", "POST"]
    # Restrict CORS to our application domain only (not wildcard)
    allowed_origins = [
      "https://${var.site_domain}",
      "https://www.${var.site_domain}"
    ]
    max_age_seconds = 3600
  }
}

# Outputs
output "static_bucket_id" {
  description = "ID of the static assets S3 bucket"
  value       = aws_s3_bucket.static.id
}

output "static_bucket_arn" {
  description = "ARN of the static assets S3 bucket"
  value       = aws_s3_bucket.static.arn
}

output "static_bucket_regional_domain" {
  description = "Regional domain name of the static assets S3 bucket"
  value       = aws_s3_bucket.static.bucket_regional_domain_name
}

output "exports_bucket_name" {
  description = "Name of the exports S3 bucket"
  value       = aws_s3_bucket.exports.bucket
}

output "exports_bucket_arn" {
  description = "ARN of the exports S3 bucket"
  value       = aws_s3_bucket.exports.arn
}
