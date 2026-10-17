# SES module — application transactional mail for public-order confirmations
# (KW-PUBLIC-ORDERS-SES-1, spec §6).
#
# Per the captain's 2026-10-16 directive, the DEV sending identity is a
# DEV-OWNED SUBDOMAIN of the environment's own zone (default
# orders.dev.kernelworx.app). The apex kernelworx.app zone is prod-account,
# carries live MX/SPF mail routing, and is NEVER touched here: this module
# only manages records under var.zone_domain, which dev sets to its own zone
# (dev.kernelworx.app). The apex shared-identity design from spec §6/Q1 was
# superseded for dev by the captain's directive; prod's SES slice is a separate
# pre-launch task.
#
# Ephemeral environments do not instantiate this module at all (the #665 WAF
# pattern): zero SES objects, zero cost, and the mailer's "no SES env vars ->
# no client" branch is the ephemeral shape.
#
# The account stays in the SES sandbox until production access is requested
# (a named pre-launch gate, deliberately NOT part of this task): dev may only
# send to sandbox-verified recipients.
#
# Verification is DKIM-based (SES Easy DKIM, RSA_2048_BIT): the identity
# flips to verified once the three CNAME records exist in the zone, so no
# _amazonses TXT record is needed. Every record this module creates is a new
# name inside the dev-owned subdomain — nothing pre-existing can collide.

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod)"
  type        = string
}

variable "create" {
  description = "Whether to create the SES resources (false = opt out; environments without SES do not instantiate this module at all)"
  type        = bool
  default     = true
}

variable "manage_dns" {
  description = "Whether to create the DKIM CNAME records in the environment's Route53 zone. Set false only when DNS is managed outside this stack; the identity and templates are still created."
  type        = bool
  default     = true
}

variable "zone_domain" {
  description = "The environment-owned Route53 zone that receives the DKIM records (dev: dev.kernelworx.app). Must NEVER be the apex kernelworx.app zone — that zone is prod-account and out of bounds for this module."
  type        = string
}

variable "mail_subdomain" {
  description = "Subdomain of the zone that becomes the SES sending identity"
  type        = string
  default     = "orders"
}

variable "subject_prefix" {
  description = "Prefix prepended to every template subject so a dev send can never be mistaken for a prod notice (spec §6). Dev passes \"[DEV] \"."
  type        = string
  default     = ""
}

locals {
  mail_domain  = "${var.mail_subdomain}.${var.zone_domain}"
  from_address = "orders@${local.mail_domain}"

  # Namespaced per environment (spec §6) so identities/templates never collide
  # across environments that share an account.
  order_template_name        = "order-confirm-${var.environment}"
  order_seller_template_name = "order-confirm-seller-${var.environment}"
}

resource "aws_sesv2_email_identity" "orders" {
  count = var.create ? 1 : 0

  email_identity = local.mail_domain

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }

  tags = {
    Name = "orders-${var.environment}"
  }
}

# The dev-owned zone receiving the DKIM records. The data lookup is scoped to
# var.zone_domain (an environment-owned zone); the apex kernelworx.app zone is
# never referenced here.
data "aws_route53_zone" "mail" {
  count = var.create && var.manage_dns ? 1 : 0

  name         = "${var.zone_domain}."
  private_zone = false
}

# Easy DKIM CNAMEs: <token>._domainkey.<mail_subdomain>.<zone> -> <token>.dkim.amazonses.com.
# New names under the dev-owned subdomain only — additive by construction, and
# the identity verification is driven by these records (no _amazonses TXT).
#
# Easy DKIM always yields exactly three CNAME tokens, and the token list is
# known only after the identity is applied — keying a for_each over it
# hard-fails every plan ("Invalid for_each argument ... known only after
# apply"). So the record count is the static DKIM contract (3) and each
# record reads its token positionally; the token itself is still SES-managed
# data, never hardcoded here.
resource "aws_route53_record" "dkim" {
  count = var.create && var.manage_dns ? 3 : 0

  zone_id = data.aws_route53_zone.mail[0].zone_id
  name    = "${aws_sesv2_email_identity.orders[0].dkim_signing_attributes[0].tokens[count.index]}._domainkey.${local.mail_domain}"
  type    = "CNAME"
  ttl     = 300
  records = ["${aws_sesv2_email_identity.orders[0].dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

# Order-confirmation templates (spec §6: buyer + seller variants, namespaced per
# environment). Template safety is one canonical rule: buyer-supplied strings
# interpolate through SES Handlebars auto-escaping ONLY — no pre-escaping in the
# handler (double-escaping) and no triple-brace unescaped interpolations
# (disables escaping). Pinned by tests/unit/test_ses_module_contract.py.
#
# SESv2 has no template resource in this provider line (~> 6.56), so the v1
# aws_ses_template resource is used; the Lambda calls ses:SendTemplatedEmail
# accordingly (the IAM action matches the API actually called).
resource "aws_ses_template" "order_confirm" {
  count = var.create ? 1 : 0

  name    = local.order_template_name
  subject = "${var.subject_prefix}Your KernelWorx order confirmation"
  text    = file("${path.module}/templates/order_confirm.txt.tpl")
  html    = file("${path.module}/templates/order_confirm.html.tpl")
}

resource "aws_ses_template" "order_confirm_seller" {
  count = var.create ? 1 : 0

  name    = local.order_seller_template_name
  subject = "${var.subject_prefix}New public order for {{campaignName}}"
  text    = file("${path.module}/templates/order_confirm_seller.txt.tpl")
  html    = file("${path.module}/templates/order_confirm_seller.html.tpl")
}

# Outputs
output "identity_arn" {
  description = "ARN of the SES domain identity (for the IAM send grant)"
  value       = var.create ? aws_sesv2_email_identity.orders[0].arn : ""
}

output "template_arns" {
  description = "ARNs of the order-confirmation templates (for the IAM send grant)"
  value = var.create ? [
    "arn:${data.aws_partition.current.partition}:ses:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:template/${local.order_template_name}",
    "arn:${data.aws_partition.current.partition}:ses:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:template/${local.order_seller_template_name}",
  ] : []
}

output "from_address" {
  description = "Sending address the public-orders mailer uses"
  value       = local.from_address
}

output "order_template_name" {
  description = "Namespaced buyer confirmation template name"
  value       = local.order_template_name
}

output "order_seller_template_name" {
  description = "Namespaced seller notification template name"
  value       = local.order_seller_template_name
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_partition" "current" {}
