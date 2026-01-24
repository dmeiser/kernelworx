# S3 Buckets Module

variable "environment" {
  type = string
}

variable "region_abbrev" {
  type = string
}

variable "name_prefix" {
  type = string
}

locals {
  bucket_suffix = "-${var.region_abbrev}-${var.environment}"
}

# Static Assets Bucket
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
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = ["*"]
    max_age_seconds = 3600
  }
}

# Outputs
output "static_bucket_id" {
  value = aws_s3_bucket.static.id
}

output "static_bucket_arn" {
  value = aws_s3_bucket.static.arn
}

output "static_bucket_regional_domain" {
  value = aws_s3_bucket.static.bucket_regional_domain_name
}

output "exports_bucket_name" {
  value = aws_s3_bucket.exports.bucket
}

output "exports_bucket_arn" {
  value = aws_s3_bucket.exports.arn
}
