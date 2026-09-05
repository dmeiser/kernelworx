# CloudFront Response Headers Policy (#166)
# Attached to the default (/*) behavior. Delivers CSP (including
# frame-ancestors, which the client-side <meta> tag cannot enforce) plus the
# standard security headers on every site response.

locals {
  # Mirrors the frontend <meta> CSP (frontend/index.html) during migration,
  # plus frame-ancestors 'none' and base-uri 'self'. Tightening of
  # connect-src to 'self' is a later phase, after same-origin is universal.
  csp = "default-src 'self'; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data: https:; connect-src 'self' https://*.amazonaws.com https://*.amazoncognito.com https://api.kernelworx.app https://api.dev.kernelworx.app ws: wss:; frame-ancestors 'none'; base-uri 'self'"
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

    # Staged upward in later work; keep max-age small here.
    strict_transport_security {
      access_control_max_age_sec = 300
      override                   = true
    }
  }
}

output "response_headers_policy_id" {
  description = "ID of the security response headers policy"
  value       = aws_cloudfront_response_headers_policy.security.id
}
