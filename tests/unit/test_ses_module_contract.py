"""Static contract for the dev SES slice (KW-PUBLIC-ORDERS-SES-1).

The captain's 2026-10-16 directive makes the dev sending identity a DEV-OWNED
SUBDOMAIN of the dev zone; the apex ``kernelworx.app`` zone (prod account, live
MX/SPF) is NEVER touched. These guards pin:

- only the dev environment instantiates the SES module; prod and ephemeral do
  not reference it at all;
- the module's DNS records land in ``var.zone_domain`` (dev passes its own
  zone, never the apex) and only ever create new CNAME names under the
  dev-owned mail subdomain — no TXT/MX/SPF record exists in the module;
- templates interpolate buyer data through SES Handlebars auto-escaping only
  (no ``{{{ }}}`` unescaped interpolation anywhere) and are namespaced per
  environment with the ``[DEV] `` subject prefix coming from a variable;
- the lambda/iam wiring keeps the ephemeral shape: SES env vars and the SES
  role grant exist only when the SES module outputs are passed, and the
  public-orders handler entry point is unchanged.
"""

import re
from pathlib import Path
from typing import Any, Dict

from tests.unit.test_edge_security import TF_APP, load_hcl

SES_MODULE = TF_APP / "modules" / "ses" / "main.tf"
SES_MODULE_DIR = TF_APP / "modules" / "ses"
DEV_MAIN = TF_APP / "environments" / "dev" / "main.tf"
PROD_MAIN = TF_APP / "environments" / "prod" / "main.tf"
EPHEMERAL_MAIN = TF_APP / "environments" / "ephemeral" / "main.tf"
LAMBDA_MAIN = TF_APP / "modules" / "lambda" / "main.tf"
IAM_MAIN = TF_APP / "modules" / "iam" / "main.tf"


def _module_blocks(env_main: Path) -> Dict[str, Any]:
    doc = load_hcl(env_main)
    modules: Dict[str, Any] = {}
    for block in doc.get("module", []):
        for name, attributes in block.items():
            modules[name] = attributes
    return modules


def test_only_dev_instantiates_the_ses_module() -> None:
    assert "ses" in _module_blocks(DEV_MAIN), "dev must instantiate the SES module"
    assert "ses" not in _module_blocks(PROD_MAIN), (
        "prod must not instantiate the SES module (apex zone is out of bounds)"
    )
    assert "ses" not in _module_blocks(EPHEMERAL_MAIN), (
        "ephemeral must not instantiate the SES module (zero-cost opt-out)"
    )


def test_dev_ses_module_is_scoped_to_the_dev_owned_zone() -> None:
    ses = _module_blocks(DEV_MAIN)["ses"]
    # The dev zone — never the apex kernelworx.app zone, which lives in the
    # prod account with live MX/SPF mail routing.
    assert ses["zone_domain"] == "${local.zone_domain}"
    assert ses["mail_subdomain"] == "orders"
    assert ses["subject_prefix"] == "[DEV] "


def test_ses_module_never_references_the_apex_zone() -> None:
    # The apex zone may be MENTIONED (comments, variable descriptions) but no
    # executable argument may name it: every DNS reference goes through
    # var.zone_domain, which dev sets to its own zone.
    offenders = [
        line
        for line in SES_MODULE.read_text().splitlines()
        if "kernelworx.app" in line and not line.lstrip().startswith("#") and "description" not in line
    ]
    assert offenders == [], f"executable lines must not name the apex zone: {offenders}"
    assert '"aws_route53_record"' in SES_MODULE.read_text()
    # The only records the module creates are the Easy DKIM CNAMEs.
    doc = load_hcl(SES_MODULE)
    records = doc.get("resource", [])
    seen_types = set()
    for block in records:
        for resource_type, instances in block.items():
            if resource_type != "aws_route53_record":
                continue
            for name, attributes in instances.items():
                seen_types.add(attributes["type"])
    assert seen_types == {"CNAME"}, f"the SES module may only create CNAME records: {seen_types}"


def test_ses_module_uses_the_environment_zone_data_lookup() -> None:
    doc = load_hcl(SES_MODULE)
    zone_lookups = [
        attributes
        for block in doc.get("data", [])
        for data_type, instances in block.items()
        if data_type == "aws_route53_zone"
        for _, attributes in instances.items()
    ]
    assert len(zone_lookups) == 1
    assert zone_lookups[0]["name"] == "${var.zone_domain}."
    assert zone_lookups[0]["private_zone"] is False


def test_templates_use_auto_escaping_only_and_each_blocks() -> None:
    templates = sorted((SES_MODULE_DIR / "templates").glob("*.tpl"))
    assert len(templates) == 4
    for template in templates:
        body = template.read_text()
        assert "{{{" not in body, f"{template.name}: triple-brace unescaped interpolation is forbidden"
    # The module reads bodies with file() and the bodies are pure handlebars —
    # pinning file() keeps a future edit from switching to templatefile(),
    # whose ${...} interpolation would break on a stray sequence.
    module_source = SES_MODULE.read_text()
    assert "templatefile(" not in module_source, "SES templates must use file(); bodies contain handlebars openers"
    buyer_text = (SES_MODULE_DIR / "templates" / "order_confirm.txt.tpl").read_text()
    seller_text = (SES_MODULE_DIR / "templates" / "order_confirm_seller.txt.tpl").read_text()
    assert "{{#each lineItems}}" in buyer_text
    assert "{{#each lineItems}}" in seller_text
    assert "{{receiptUrl}}" in buyer_text, "the buyer email must carry the tokenized receipt link"
    assert "{{firstName}}" in buyer_text
    assert "{{buyerFirstName}}" in seller_text
    assert "{{#if buyerEmail}}" in seller_text


def test_template_names_are_namespaced_and_subject_prefixed() -> None:
    doc = load_hcl(SES_MODULE)
    template_resources = {}
    for block in doc.get("resource", []):
        for resource_type, instances in block.items():
            if resource_type == "aws_ses_template":
                template_resources.update(instances)
    assert set(template_resources) == {"order_confirm", "order_confirm_seller"}
    for attributes in template_resources.values():
        assert (
            attributes["name"] == "${local.order_template_name}"
            or attributes["name"] == "${local.order_seller_template_name}"
        )
        assert attributes["subject"].startswith("${var.subject_prefix}")
    # And the locals carry the per-environment namespacing (spec §6).
    locals_by_key = {key: value for block in doc.get("locals", []) for key, value in block.items()}
    assert locals_by_key["order_template_name"] == "order-confirm-${var.environment}"
    assert locals_by_key["order_seller_template_name"] == "order-confirm-seller-${var.environment}"


def test_identity_is_sesv2_with_easy_dkim() -> None:
    doc = load_hcl(SES_MODULE)
    identities = [
        attributes
        for block in doc.get("resource", [])
        for resource_type, instances in block.items()
        if resource_type == "aws_sesv2_email_identity"
        for _, attributes in instances.items()
    ]
    assert len(identities) == 1
    dkim = identities[0]["dkim_signing_attributes"][0]
    assert dkim["next_signing_key_length"] == "RSA_2048_BIT"


def test_lambda_ses_env_is_all_or_nothing() -> None:
    source = LAMBDA_MAIN.read_text()
    # The four wiring variables exist with empty defaults (the unconfigured shape).
    for var in (
        "ses_order_from_address",
        "ses_order_template_name",
        "ses_order_seller_template_name",
        "public_site_url",
    ):
        assert re.search(rf'variable "{var}"', source)
    assert '"public-orders" = {' in source
    assert "extra_env   = local.ses_env" in source


def test_iam_ses_grant_is_conditional_on_the_identity_arn() -> None:
    source = IAM_MAIN.read_text()
    assert 'variable "ses_order_identity_arn"' in source
    assert 'variable "ses_order_template_arns"' in source
    assert 'variable "ses_order_emails_enabled"' in source
    assert '"ses:SendTemplatedEmail"' in source
    # The grant only exists where the SES module is instantiated, and the
    # count keys off the STATIC flag: the identity arn is apply-time-unknown
    # on the creating apply (dev deploy 39006803271 failed plan with
    # "Invalid count argument" when counts keyed off the arn).
    assert source.count("var.ses_order_emails_enabled ? 1 : 0") == 2
    assert "var.ses_order_identity_arn != null ? 1 : 0" not in source


def test_dev_wires_ses_outputs_into_iam_and_lambda() -> None:
    source = DEV_MAIN.read_text()
    assert "ses_order_emails_enabled = true" in source
    assert "ses_order_identity_arn   = module.ses.identity_arn" in source
    assert "ses_order_template_arns  = module.ses.template_arns" in source
    assert "ses_order_from_address         = module.ses.from_address" in source
    assert '"https://${local.site_domain}"' in source
