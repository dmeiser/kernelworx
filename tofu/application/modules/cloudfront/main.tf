# CloudFront Distribution Module

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "site_domain" {
  description = "Fully qualified site domain (e.g., dev.kernelworx.app or kernelworx.app)"
  type = string
}

variable "site_certificate_arn" {
  description = "ACM certificate ARN for the CloudFront site domain"
  type = string
}

variable "static_bucket_id" {
  description = "ID of the S3 bucket serving static assets"
  type = string
}

variable "static_bucket_arn" {
  description = "ARN of the S3 bucket serving static assets"
  type = string
}

variable "static_bucket_regional_domain" {
  description = "Regional domain name of the S3 bucket for CloudFront origin"
  type        = string
}

variable "api_gateway_regional_domain" {
  description = "Regional domain name of the API Gateway custom domain (for routing page requests to Lambda)"
  type        = string
  default     = ""
}

variable "api_gateway_domain" {
  description = "The API Gateway custom domain name (e.g., api.dev.kernelworx.app) for CloudFront to route page requests"
  type        = string
  default     = ""
}

variable "certificate_validation" {
  description = "Certificate validation resource to ensure certificate is valid before use"
  type        = any
  default     = null
}

locals {
  site_domain = var.site_domain
  api_origin_id = "ApiGateway-${var.environment}"
  use_api_origin = var.api_gateway_domain != "" || var.api_gateway_regional_domain != ""
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
  default_root_object = ""
  aliases             = [local.site_domain]
  price_class         = "PriceClass_100"

  origin {
    domain_name = var.static_bucket_regional_domain
    origin_id   = "S3-${var.static_bucket_id}"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.main.cloudfront_access_identity_path
    }
  }

  dynamic "origin" {
    for_each = local.use_api_origin ? [1] : []
    content {
      domain_name = var.api_gateway_domain != "" ? var.api_gateway_domain : var.api_gateway_regional_domain
      origin_id   = local.api_origin_id

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # Static assets from S3
  ordered_cache_behavior {
    path_pattern     = "/static/*"
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-${var.static_bucket_id}"
    viewer_protocol_policy = "redirect-to-https"
    compress = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 604800
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.use_api_origin ? local.api_origin_id : "S3-${var.static_bucket_id}"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers = ["Authorization", "Content-Type", "Accept", "HX-Request", "HX-Target", "HX-Trigger", "HX-Redirect"]
      cookies {
        forward = "all"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
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
    precondition {
      condition     = var.certificate_validation != null ? true : true
      error_message = "Certificate validation must complete before creating CloudFront distribution"
    }
  }
}

# Outputs
output "distribution_id" {
  description = "ID of the CloudFront distribution"
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_arn" {
  description = "ARN of the CloudFront distribution"
  value       = aws_cloudfront_distribution.site.arn
}

output "distribution_domain" {
  description = "Domain name of the CloudFront distribution"
  value       = aws_cloudfront_distribution.site.domain_name
}

output "distribution_hosted_zone_id" {
  description = "Route 53 zone ID for the CloudFront distribution"
  value       = aws_cloudfront_distribution.site.hosted_zone_id
}
