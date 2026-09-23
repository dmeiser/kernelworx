# CloudFront Response Headers Policy (#166)
# Attached to the default (/*) behavior. Delivers CSP (including
# frame-ancestors, which the client-side <meta> tag cannot enforce) plus the
# standard security headers on every site response.

variable "hsts_max_age_sec" {
  description = "Strict-Transport-Security max-age in seconds. Dev ramps up from a small value; prod uses one year (#430)."
  type        = number
  default     = 300
}

variable "hsts_include_subdomains" {
  description = "Add includeSubDomains to Strict-Transport-Security. Prod only (#430); browsers clamp on max-age decrease, so only raise this, never lower it."
  type        = bool
  default     = false
}

locals {
  # Mirrors the frontend <meta> CSP (frontend/index.html), plus
  # frame-ancestors 'none' and base-uri 'self'. #440 tightened both policies:
  # - img-src: the old trailing `https:` wildcard admitted arbitrary
  #   third-party images (tracking/exfiltration surface). Enumerated real
  #   image sources instead: 'self' (static assets), data: (MFA TOTP QR data
  #   URLs), blob: (QR upload preview via URL.createObjectURL), and the exact
  #   S3 virtual-hosted origin of the exports bucket that serves payment QR
  #   presigned GET URLs (<bucket>.s3.<region>.amazonaws.com, boto3 default).
  # - connect-src: ws:/wss: removed; the app uses no WebSockets and an
  #   allowed ws: scheme is a plaintext downgrade vector.
  csp = "default-src 'self'; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data: blob: https://${var.exports_bucket_name}.s3.${var.aws_region}.amazonaws.com; connect-src 'self' https://*.amazonaws.com https://*.amazoncognito.com https://api.kernelworx.app https://api.dev.kernelworx.app https://login.dev.kernelworx.app https://login.kernelworx.app; frame-ancestors 'none'; base-uri 'self'"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${replace(local.site_domain, ".", "-")}-security-headers"
  comment = "Security headers for ${local.site_domain} (#166)"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    content_type_options {
      override = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    # #430: max-age/includeSubDomains are per-environment inputs. The
    # module default keeps dev on the 300s ramp; prod passes one year +
    # includeSubdomains. `preload` is deliberately omitted: it requires
    # includeSubDomains + max-age >= 31536000 AND listing on the HSTS
    # preload list, which is effectively irreversible, so it needs its own
    # go/no-go before being enabled.
    strict_transport_security {
      access_control_max_age_sec = var.hsts_max_age_sec
      include_subdomains         = var.hsts_include_subdomains
      override                   = true
    }
  }
}

output "response_headers_policy_id" {
  description = "ID of the security response headers policy"
  value       = aws_cloudfront_response_headers_policy.security.id
}
