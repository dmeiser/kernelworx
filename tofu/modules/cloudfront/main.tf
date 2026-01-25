# CloudFront Distribution Module

variable "environment" {
  type = string
}

variable "domain" {
  type = string
}

variable "site_certificate_arn" {
  type = string
}

variable "static_bucket_id" {
  type = string
}

variable "static_bucket_arn" {
  type = string
}

variable "static_bucket_regional_domain" {
  type = string
}

locals {
  site_domain = "${var.environment}.${var.domain}"
}

# Origin Access Identity
resource "aws_cloudfront_origin_access_identity" "main" {
  comment = "OAI for ${local.site_domain}"

  lifecycle {
    prevent_destroy = true
  }
}

# S3 Bucket Policy for CloudFront
resource "aws_s3_bucket_policy" "static" {
  bucket = var.static_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontAccess"
        Effect    = "Allow"
        Principal = {
          AWS = aws_cloudfront_origin_access_identity.main.iam_arn
        }
        Action   = "s3:GetObject"
        Resource = "${var.static_bucket_arn}/*"
      }
    ]
  })
}

# CloudFront Distribution
# NOTE: CloudFront logging is disabled to minimize AWS costs.
# kics-scan ignore-line
resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [local.site_domain]
  price_class         = "PriceClass_100"

  origin {
    domain_name = var.static_bucket_regional_domain
    origin_id   = "S3-${var.static_bucket_id}"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.main.cloudfront_access_identity_path
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-${var.static_bucket_id}"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 86400
  }

  # SPA routing - return index.html for 404s
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.site_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Outputs
output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "distribution_domain" {
  value = aws_cloudfront_distribution.site.domain_name
}

output "distribution_hosted_zone_id" {
  value = aws_cloudfront_distribution.site.hosted_zone_id
}
