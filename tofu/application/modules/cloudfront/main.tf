# CloudFront Distribution Module

variable "site_domain" {
  description = "Fully qualified site domain (e.g., dev.kernelworx.app or kernelworx.app)"
  type        = string
}

variable "site_certificate_arn" {
  description = "ACM certificate ARN for the CloudFront site domain"
  type        = string
}

variable "static_bucket_id" {
  description = "ID of the S3 bucket serving static assets"
  type        = string
}

variable "static_bucket_arn" {
  description = "ARN of the S3 bucket serving static assets"
  type        = string
}

variable "static_bucket_regional_domain" {
  description = "Regional domain name of the S3 bucket for CloudFront origin"
  type        = string
}

variable "exports_bucket_name" {
  description = "Name of the S3 exports bucket serving payment QR presigned URLs (CSP img-src allowlist)"
  type        = string
}

variable "aws_region" {
  description = "AWS region of the exports bucket (CSP img-src allowlist)"
  type        = string
}

variable "certificate_validation" {
  description = "Certificate validation resource to ensure certificate is valid before use"
  type        = any
  default     = null
}

variable "web_acl_id" {
  description = "Full ARN of the CLOUDFRONT-scope AWS WAF web ACL to attach to the distribution (null = no WAF). The bare ACL ID is rejected by CloudFront in this account ('Web ACL is not accessible by the requester'), so the ARN is passed."
  type        = string
  default     = null
}

variable "api_origin_domain" {
  description = "AppSync default endpoint hostname for the /graphql behavior (null = no API behavior)"
  type        = string
  default     = null
}

variable "auth_origin_domain" {
  description = "Cognito custom domain hostname proxied for /l*, /oauth2/*, /.well-known/* (null = no auth behaviors)"
  type        = string
  default     = null
}

locals {
  site_domain = var.site_domain

  api_origin_id  = "AppSync-${var.api_origin_domain}"
  auth_origin_id = "Cognito-${var.auth_origin_domain}"

  # Auth paths proxied to the Cognito custom domain (Amplify builds OAuth URLs
  # at root paths, so these must live at the root and not under a prefix).
  # #665: /login and /logout collapsed into the /l* wildcard and the
  # /favicon.ico behavior removed (favicons ship in frontend/public and are
  # served by the default S3 behavior), bringing the distribution to the
  # CloudFront Free plan's 5-behavior cap. Sharp edge: never add an SPA
  # route starting with /l - it would be silently proxied to Cognito and 404.
  auth_path_patterns = ["/l*", "/oauth2/*", "/.well-known/*"]

  # AWS-managed cache/origin-request/response-headers policies (#665,
  # CloudFront pricing plans Free tier): legacy forwarded_values and
  # behavior-level TTLs are unsupported on every tier, and custom response
  # headers policies are a Business-tier feature, so the managed policies
  # replace all of them. These IDs are the stable AWS-published IDs.
  managed_cache_disabled_policy_id         = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
  managed_cache_optimized_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  managed_all_viewer_except_host_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
  managed_security_headers_policy_id       = "67f7725c-6f97-4210-82d7-5512b31e9d03" # SecurityHeadersPolicy
}

# CloudFront Function: Cognito answers with absolute redirects on its own
# domain; rewrite them to the site origin so browsers stay on the
# distribution. Associated with the auth ordered cache behaviors only.
resource "aws_cloudfront_function" "auth_location_rewrite" {
  count   = var.auth_origin_domain != null ? 1 : 0
  name    = "${replace(local.site_domain, ".", "-")}-auth-location-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite Cognito absolute Location redirects from ${var.auth_origin_domain} to ${local.site_domain}"
  publish = true

  code = <<-EOF
  function handler(event) {
    var response = event.response;
    var location = response.headers.location;
    var prefix = "https://${var.auth_origin_domain}";
    if (location && location.value.indexOf(prefix) === 0) {
      var rest = location.value.slice(prefix.length);
      if (rest.indexOf("/") !== 0) {
        rest = "/" + rest;
      }
      location.value = "https://${local.site_domain}" + rest;
    }
    return response;
  }
  EOF
}

# Origin Access Control (#335: OAI is deprecated; OAC supports SSE-KMS,
# dynamic requests, and modern sigv4 request signing).
resource "aws_cloudfront_origin_access_control" "main" {
  name                              = "OAC for ${local.site_domain}"
  description                       = "OAC for ${local.site_domain}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"

  lifecycle {
    prevent_destroy = true
  }
}

# S3 Bucket Policy for CloudFront. Grants access to the CloudFront service
# principal, scoped to this distribution via the SourceArn condition (the
# OAC signing model replaces the OAI canonical-user grant).
resource "aws_s3_bucket_policy" "static" {
  bucket = var.static_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontAccess"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${var.static_bucket_arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
          }
        }
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
  # price_class is deliberately unset: the CloudFront flat-rate Free plan
  # (#665) rejects any distribution that carries one - UpdateDistribution
  # fails with "Distributions with the Free pricing plan can't have the
  # following features: Price class". Omitted is the only accepted value;
  # edge coverage is whatever the plan provides, not a configured tier.
  web_acl_id = var.web_acl_id

  origin {
    domain_name = var.static_bucket_regional_domain
    origin_id   = "S3-${var.static_bucket_id}"

    origin_access_control_id = aws_cloudfront_origin_access_control.main.id

    s3_origin_config {
      origin_access_identity = ""
    }
  }

  # AppSync default endpoint hostname (the served TLS cert matches it; the
  # custom-domain name does not work as an origin name).
  dynamic "origin" {
    for_each = var.api_origin_domain != null ? [1] : []

    content {
      domain_name = var.api_origin_domain
      origin_id   = local.api_origin_id

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # Cognito custom domain, reached with SNI/Host of the custom domain.
  dynamic "origin" {
    for_each = var.auth_origin_domain != null ? [1] : []

    content {
      domain_name = var.auth_origin_domain
      origin_id   = local.auth_origin_id

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # GraphQL API path: same-origin through the distribution, no caching.
  dynamic "ordered_cache_behavior" {
    for_each = var.api_origin_domain != null ? [1] : []

    content {
      path_pattern           = "/graphql"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      target_origin_id       = local.api_origin_id
      viewer_protocol_policy = "redirect-to-https"

      # Managed-CachingDisabled (TTLs 0) + Managed-AllViewerExceptHostHeader
      # (forwards Authorization/Content-Type/Accept and all cookies): same
      # same-origin GraphQL semantics as the old forwarded_values block.
      cache_policy_id          = local.managed_cache_disabled_policy_id
      origin_request_policy_id = local.managed_all_viewer_except_host_policy_id
    }
  }

  # Cognito auth paths (managed login + OAuth endpoints), ahead of the
  # default behavior. Caching disabled; cookies must flow to Cognito.
  dynamic "ordered_cache_behavior" {
    for_each = var.auth_origin_domain != null ? local.auth_path_patterns : []

    content {
      path_pattern           = ordered_cache_behavior.value
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      target_origin_id       = local.auth_origin_id
      viewer_protocol_policy = "redirect-to-https"

      # Caching disabled; cookies must flow to Cognito (same managed pair as
      # /graphql). #550 headers now come from the AWS-managed
      # SecurityHeadersPolicy (#665): nosniff, Referrer-Policy, HSTS
      # max-age=31536000, and XFO SAMEORIGIN. Cognito's own values win when
      # it already sends one of these (managed policy, Override origin? = No).
      cache_policy_id            = local.managed_cache_disabled_policy_id
      origin_request_policy_id   = local.managed_all_viewer_except_host_policy_id
      response_headers_policy_id = local.managed_security_headers_policy_id

      function_association {
        event_type   = "viewer-response"
        function_arn = aws_cloudfront_function.auth_location_rewrite[0].arn
      }
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-${var.static_bucket_id}"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    # #665: Managed-CachingOptimized only (no origin request policy). Its
    # effective default TTL is the policy's 86400s when objects carry no
    # Cache-Control (vs the old 3600s); deploy invalidations already
    # force-fresh index.html, so behavior is unchanged in practice.
    cache_policy_id = local.managed_cache_optimized_policy_id

    # #166/#665: the AWS-managed SecurityHeadersPolicy replaces the custom
    # policy (a Business-tier feature): nosniff, Referrer-Policy, HSTS
    # max-age=31536000, XFO SAMEORIGIN. The application CSP survives only
    # as the <meta> tag in frontend/index.html - a documented #665 trade-off.
    response_headers_policy_id = local.managed_security_headers_policy_id
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
    precondition {
      # When a validation resource is supplied, ensure it has completed before
      # creating the distribution. Dev builds omit validation entirely.
      condition     = var.certificate_validation == null ? true : try(length(var.certificate_validation.validation_record_fqdns) > 0, false)
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
