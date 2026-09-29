# CloudFront Response Headers Policies (#166, #550)
# The `security` policy is attached to the default (/*) behavior. It delivers
# CSP (including frame-ancestors, which the client-side <meta> tag cannot
# enforce) plus the standard security headers on every site response. The
# `auth_security` policy is attached to the Cognito auth behaviors, whose
# documents are first-party content on the site origin too.

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
  #   URLs), blob: (QR upload preview via URL.createObjectURL), and the
  #   exact S3 virtual-hosted origins of the exports bucket that serves
  #   payment QR presigned GET URLs. Both the regional
  #   (<bucket>.s3.<region>.amazonaws.com) and legacy global
  #   (<bucket>.s3.amazonaws.com) virtual-hosted styles are listed: the
  #   pinned boto3/botocore in the Lambda layer defaults to the legacy
  #   global endpoint for us-east-1 presigned URLs, so an allowlist of only
  #   the regional host would block payment QR images in the browser.
  # - connect-src: ws:/wss: removed; the app uses no WebSockets and an
  #   allowed ws: scheme is a plaintext downgrade vector.
  csp = "default-src 'self'; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data: blob: https://${var.exports_bucket_name}.s3.${var.aws_region}.amazonaws.com https://${var.exports_bucket_name}.s3.amazonaws.com; connect-src 'self' https://*.amazonaws.com https://*.amazoncognito.com https://api.kernelworx.app https://api.dev.kernelworx.app https://login.dev.kernelworx.app https://login.kernelworx.app; frame-ancestors 'none'; base-uri 'self'"

  # #550: framing-only CSP for the Cognito hosted-UI documents proxied on the
  # auth paths. Deliberately narrow: Cognito's login/OAuth documents load
  # their own assets from the region cognito endpoint and run inline bootstrap
  # scripts, so the full application CSP above would break sign-in. Every
  # directive left unspecified is unrestricted, so this policy changes nothing
  # about how those documents load - it only forbids being framed, which is
  # the clickjacking primitive on a credential form.
  auth_csp = "frame-ancestors 'none'"
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

# CloudFront Response Headers Policy for the Cognito auth behaviors (#550)
# /login, /logout, /oauth2/*, /.well-known/* and /favicon.ico are served from
# Cognito through the distribution, so these responses are first-party content
# on the site origin. Without this policy they arrived with no security headers
# at all - notably no framing protection on the login form, which is the
# clickjacking/credential-theft target on the domain users trust. Carries the
# same HSTS inputs as the site policy (#430) plus the framing/nosniff/referrer
# trio, under the narrow auth CSP rather than the full application one.
resource "aws_cloudfront_response_headers_policy" "auth_security" {
  name    = "${replace(local.site_domain, ".", "-")}-auth-security-headers"
  comment = "Security headers for the Cognito hosted UI proxied on ${local.site_domain} (#550)"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.auth_csp
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
