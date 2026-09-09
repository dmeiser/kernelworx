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
  description = "Cognito custom domain hostname proxied for /login, /logout, /oauth2/*, /.well-known/*, /favicon.ico (null = no auth behaviors)"
  type        = string
  default     = null
}

locals {
  site_domain = var.site_domain

  api_origin_id  = "AppSync-${var.api_origin_domain}"
  auth_origin_id = "Cognito-${var.auth_origin_domain}"

  # Auth paths proxied to the Cognito custom domain (Amplify builds OAuth URLs
  # at root paths, so these must live at the root and not under a prefix).
  auth_path_patterns = ["/login", "/logout", "/oauth2/*", "/.well-known/*", "/favicon.ico"]
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

# --- ONE-TIME MIGRATION SCAFFOLD (follow-up: remove after the legacy OAI is
# destroyed in all environments) ---
#
# #335/#359 removed aws_cloudfront_origin_access_identity.main from the config,
# which leaves a dangling destroy in state. Nothing references the OAI anymore,
# so OpenTofu schedules its destroy first/parallel to the OAC cutover, and
# CloudFront rejects the delete (CloudFrontOriginAccessIdentityInUse) because
# the InUse check runs against the live config — UpdateDistribution returns at
# acceptance, several minutes before signing actually switches. The same race
# hits aws_s3_bucket_policy.static: flipping the principal from the OAI
# canonical user to the Service+SourceArn grant before the cutover has
# DEPLOYED would leave the live distribution (still signing as the OAI) without
# S3 access. The gate below orders both behind the distribution reaching the
# Deployed state.
resource "terraform_data" "legacy_oai_destroy_gate" {
  depends_on = [aws_cloudfront_distribution.site]

  provisioner "local-exec" {
    # Poll until the distribution cutover has fully deployed (up to 30 min).
    # awscli is available in the deploy job (deploy-shared.yml uses it for the
    # post-deploy invalidation).
    command     = <<-EOT
      set -e
      DIST_ID="${aws_cloudfront_distribution.site.id}"
      for i in $(seq 1 60); do
        STATUS=$(aws cloudfront get-distribution --id "$DIST_ID" --query 'Distribution.Status' --output text 2>/dev/null || true)
        if [ "$STATUS" = "Deployed" ]; then
          echo "Distribution $DIST_ID reached Deployed; the legacy OAI destroy and bucket-policy cutover are safe to proceed."
          exit 0
        fi
        echo "Distribution $DIST_ID status is '$${STATUS:-unknown}'; waiting for Deployed before legacy OAI destroy (attempt $i/60)..."
        sleep 30
      done
      echo "ERROR: distribution $DIST_ID did not reach Deployed within 30 minutes; refusing to proceed with the legacy OAI destroy while the OAC cutover may still be in flight." >&2
      exit 1
    EOT
    interpreter = ["/bin/bash", "-c"]
  }
}

# Re-added with count = 0 ONLY to order the dangling state destroy of the
# legacy OAI after the gate above (the exact address must match state).
# ONE-TIME MIGRATION SCAFFOLD: remove this block in a follow-up once the OAI
# is destroyed in every environment.
resource "aws_cloudfront_origin_access_identity" "main" {
  count = 0

  comment = "legacy OAI for ${local.site_domain} — destroy-only scaffold, do not recreate"

  depends_on = [terraform_data.legacy_oai_destroy_gate]
}

# S3 Bucket Policy for CloudFront. Grants access to the CloudFront service
# principal, scoped to this distribution via the SourceArn condition (the
# OAC signing model replaces the OAI canonical-user grant).
resource "aws_s3_bucket_policy" "static" {
  bucket = var.static_bucket_id

  # ONE-TIME MIGRATION SCAFFOLD: the principal flip (OAI canonical user ->
  # Service+SourceArn) must wait until the OAC cutover is Deployed; while the
  # live distribution still signs as the OAI, only the old grant would work.
  # Remove this depends_on with the scaffold follow-up.
  depends_on = [terraform_data.legacy_oai_destroy_gate]

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
  price_class         = "PriceClass_100"
  web_acl_id          = var.web_acl_id

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

      forwarded_values {
        query_string = true
        headers      = ["Authorization", "Content-Type", "Accept"]

        cookies {
          forward = "none"
        }
      }

      min_ttl     = 0
      default_ttl = 0
      max_ttl     = 0
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

      forwarded_values {
        query_string = true

        cookies {
          forward = "all"
        }
      }

      min_ttl     = 0
      default_ttl = 0
      max_ttl     = 0

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

    # #166: security headers (CSP incl. frame-ancestors) on all site responses.
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

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
