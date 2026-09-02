"""Focused tests for the single-distribution edge security architecture (#165/#166).

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the *meaning* of the edge architecture contract:

- Exactly one WAF exists anywhere: a CLOUDFRONT-scope aws_wafv2_web_acl
  attached via web_acl_id. No regional web ACLs, no
  aws_wafv2_web_acl_association resources.
- The WAF rate rule blocks at 2000 requests per IP per 300s; the AWS managed
  core rule set is staged in Count; WAF logs land in an aws-waf-logs-*
  CloudWatch log group. Every WAF resource no-ops when create = false so
  ephemeral environments create zero objects.
- The existing CloudFront distribution gains /graphql and auth ordered
  behaviors in place (prevent_destroy intact): /graphql forwards exactly
  Authorization/Content-Type/Accept with caching disabled; the auth paths
  forward all cookies and run the viewer-response Location-rewrite function.
- The response headers policy on the default behavior enforces CSP including
  frame-ancestors 'none', XFO DENY, nosniff, Referrer-Policy, and HSTS
  max-age=300 with override=true on all of them.
- Dev/prod wire the WAF into the distribution; ephemeral passes create =
  false and has no CloudFront at all. The api Route53 record is gone while
  the load-bearing login record remains.
- The dev/prod frontend build contract: deploy-shared.yml stops exporting
  VITE_APPSYNC_ENDPOINT / VITE_COGNITO_DOMAIN, while ephemeral-env.sh keeps
  exporting both as absolute values.
"""

from __future__ import annotations

import json
from pathlib import Path

import hcl2
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TF_APP = REPO_ROOT / "tofu" / "application"


def _norm(key: str) -> str:
    """Strip the quote wrapper python-hcl2 adds around interpolated keys."""
    if isinstance(key, str) and key.startswith('"') and key.endswith('"'):
        return key[1:-1]
    return key


def _clean(value):
    """Drop python-hcl2 bookkeeping keys and decode interpolated strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ("__is_block__", "__comments__"):
                continue
            out[_norm(k)] = _clean(v)
        return out
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def load_hcl(path: Path) -> dict:
    with path.open() as f:
        return _clean(hcl2.load(f))


def block(value):
    """hcl2 parses nested blocks as single-element lists; unwrap them."""
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return value


def resources(doc: dict, resource_type: str) -> list[tuple[str, dict]]:
    """Return [(label, body), ...] for every resource of the given type."""
    found = []
    for entry in doc.get("resource", []):
        for rtype, bodies in entry.items():
            if rtype != resource_type:
                continue
            for label, attrs in bodies.items():
                found.append((_norm(label), attrs))
    return found


def modules(doc: dict, name: str) -> list[dict]:
    found = []
    for entry in doc.get("module", []):
        for label, attrs in entry.items():
            if _norm(label) == name:
                found.append(attrs)
    return found


def dynamic_blocks(body: dict, block_name: str) -> list[dict]:
    """Unwrap `dynamic "<block_name>" { content { ... } }` entries to content dicts."""
    out = []
    for entry in body.get("dynamic", []):
        spec = entry.get(block_name)
        if not spec:
            continue
        for content in spec["content"]:
            out.append(content)
    return out


def first_resource(doc: dict, resource_type: str, label: str) -> dict:
    matches = [body for lbl, body in resources(doc, resource_type) if lbl == label]
    assert matches, f"resource {resource_type}.{label} not found"
    return matches[0]


def variable_defaults(doc: dict) -> dict:
    defaults = {}
    for entry in doc.get("variable", []):
        for name, attrs in entry.items():
            defaults[_norm(name)] = attrs.get("default")
    return defaults


@pytest.fixture(scope="module")
def waf_module() -> dict:
    return load_hcl(TF_APP / "modules" / "waf" / "main.tf")


@pytest.fixture(scope="module")
def cloudfront_module() -> dict:
    doc = load_hcl(TF_APP / "modules" / "cloudfront" / "main.tf")
    doc["response_headers"] = load_hcl(TF_APP / "modules" / "cloudfront" / "response-headers.tf")
    return doc


@pytest.fixture(scope="module")
def route53_module() -> dict:
    return load_hcl(TF_APP / "modules" / "route53" / "main.tf")


# ---------------------------------------------------------------------------
# WAF module (#165)
# ---------------------------------------------------------------------------


def test_waf_is_the_only_waf_and_is_cloudfront_scoped():
    acls = []
    associations = 0
    for tf in TF_APP.rglob("*.tf"):
        doc = load_hcl(tf)
        acls.extend(resources(doc, "aws_wafv2_web_acl"))
        associations += len(resources(doc, "aws_wafv2_web_acl_association"))
    assert len(acls) == 1, f"expected exactly one web ACL across the app, found {len(acls)}"
    _, acl = acls[0]
    assert acl["scope"] == "CLOUDFRONT"
    assert associations == 0, "aws_wafv2_web_acl_association must not exist anywhere"


def test_waf_default_allows_and_rate_rule_blocks_2000_per_300s(waf_module):
    acl = first_resource(waf_module, "aws_wafv2_web_acl", "main")
    assert "allow" in block(acl["default_action"])

    rate_rule = next(r for r in acl["rule"] if r["name"] == "rate-limit")
    assert rate_rule["priority"] == 1
    # Action is a dynamic block keyed on var.rate_rule_action; the default is
    # Block, with Count available for observation runs.
    action_dyn = block(rate_rule["action"])["dynamic"]
    keyed = {list(d)[0]: list(d.values())[0]["for_each"] for d in action_dyn}
    assert set(keyed) == {"block", "count"}
    assert keyed["block"] == '${var.rate_rule_action == "Block" ? [1] : []}'

    stmt = block(rate_rule["statement"])["rate_based_statement"]
    stmt = block(stmt)
    # The limit/window are variable-driven; the variable defaults above pin
    # the shipped 2000 requests / 300s contract.
    assert stmt["limit"] == "${var.rate_limit}"
    assert stmt["aggregate_key_type"] == "IP"
    assert stmt["evaluation_window_sec"] == "${var.rate_evaluation_window}"

    defaults = variable_defaults(waf_module)
    assert defaults["rate_limit"] == 2000
    assert defaults["rate_evaluation_window"] == 300
    assert defaults["rate_rule_action"] == "Block"


def test_waf_core_managed_rules_staged_in_count(waf_module):
    acl = first_resource(waf_module, "aws_wafv2_web_acl", "main")
    managed = next(r for r in dynamic_blocks(acl, "rule") if r["name"] == "aws-core-managed-rules")
    assert managed["priority"] == 2
    group = block(block(managed["statement"])["managed_rule_group_statement"])
    assert group["name"] == "AWSManagedRulesCommonRuleSet"
    assert group["vendor_name"] == "AWS"
    # Count override while staged; Block is a later, variable-driven flip.
    override_dyn = block(managed["override_action"])["dynamic"]
    keyed = {list(d)[0]: list(d.values())[0]["for_each"] for d in override_dyn}
    assert keyed["count"] == '${var.managed_rule_action == "Count" ? [1] : []}'

    defaults = variable_defaults(waf_module)
    assert defaults["enable_core_managed_rules"] is True
    assert defaults["managed_rule_action"] == "Count"


def test_waf_logging_to_aws_waf_logs_log_group(waf_module):
    log_group = first_resource(waf_module, "aws_cloudwatch_log_group", "waf")
    assert log_group["name"].startswith("aws-waf-logs-")
    assert log_group["retention_in_days"] == "${var.log_retention_days}"

    logging = first_resource(waf_module, "aws_wafv2_web_acl_logging_configuration", "main")
    assert logging["resource_arn"] == "${aws_wafv2_web_acl.main[0].arn}"
    assert logging["log_destination_configs"] == ["${aws_cloudwatch_log_group.waf[0].arn}"]
    assert "aws_cloudwatch_log_resource_policy" in logging["depends_on"][0]

    data_docs = [
        bodies for entry in waf_module["data"] for dtype, bodies in entry.items() if dtype == "aws_iam_policy_document"
    ]
    assert data_docs, "waf_log_delivery policy document not found"
    doc = list(data_docs[0].values())[0]
    principal = block(block(doc["statement"][0])["principals"][0])
    assert principal["identifiers"] == ["delivery.logs.amazonaws.com"]


def test_waf_create_false_zero_objects(waf_module):
    # Every resource in the module must be gated on var.create so ephemeral
    # environments plan zero WAF objects at zero cost.
    for entry in waf_module["resource"]:
        for bodies in entry.values():
            for label, body in bodies.items():
                assert body.get("count") == "${var.create ? 1 : 0}", f"{_norm(label)} is not gated on var.create"


def test_waf_provider_pinned_and_cloudfront_region_us_east_1():
    tf_file = TF_APP / "modules" / "waf" / "terraform.tf"
    doc = load_hcl(tf_file)
    aws_req = block(block(doc["terraform"][0])["required_providers"][0])["aws"]
    assert aws_req["version"] == "~> 6.56"
    # CLOUDFRONT-scope WAFs require the us-east-1 provider, which the dev/prod
    # environments pin as the default region.
    for env in ("dev", "prod"):
        env_doc = load_hcl(TF_APP / "environments" / env / "main.tf")
        provider = block(env_doc["provider"])["aws"]
        assert provider["region"] == "${var.aws_region}"
        region_default = variable_defaults(env_doc)["aws_region"]
        assert region_default == "us-east-1"


# ---------------------------------------------------------------------------
# CloudFront distribution (#165/#166)
# ---------------------------------------------------------------------------


def test_distribution_prevent_destroy_and_single_distribution(cloudfront_module):
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    lifecycle = block(dist["lifecycle"])
    assert lifecycle["prevent_destroy"] is True
    # In-place attributes on the existing distribution: exactly one distribution.
    all_dists = resources(cloudfront_module, "aws_cloudfront_distribution")
    assert len(all_dists) == 1
    assert dist["web_acl_id"] == "${var.web_acl_id}"


def test_graphql_behavior_same_origin_no_cache(cloudfront_module):
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    behaviors = [b for b in dynamic_blocks(dist, "ordered_cache_behavior") if b["path_pattern"] == "/graphql"]
    assert len(behaviors) == 1
    behavior = behaviors[0]
    assert behavior["target_origin_id"] == "${local.api_origin_id}"
    assert behavior["forwarded_values"][0]["headers"] == ["Authorization", "Content-Type", "Accept"]
    assert behavior["forwarded_values"][0]["cookies"][0]["forward"] == "none"
    assert behavior["min_ttl"] == 0
    assert behavior["default_ttl"] == 0
    assert behavior["max_ttl"] == 0

    # The API origin is the AppSync default endpoint hostname with TLS
    # protocols inside the provider-accepted enum (the TLSv1.3 plan blocker
    # from the failed dev deploy).
    api_origin = next(o for o in dynamic_blocks(dist, "origin") if o["origin_id"] == "${local.api_origin_id}")
    cfg = block(api_origin["custom_origin_config"])
    allowed = {"SSLv3", "TLSv1", "TLSv1.1", "TLSv1.2"}
    assert set(cfg["origin_ssl_protocols"]) <= allowed
    assert cfg["origin_protocol_policy"] == "https-only"

    auth_origin = next(o for o in dynamic_blocks(dist, "origin") if o["origin_id"] == "${local.auth_origin_id}")
    cfg = block(auth_origin["custom_origin_config"])
    assert set(cfg["origin_ssl_protocols"]) <= allowed


def test_auth_behaviors_proxy_cognito_with_location_rewrite(cloudfront_module):
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    fn = first_resource(cloudfront_module, "aws_cloudfront_function", "auth_location_rewrite")
    assert fn["runtime"] == "cloudfront-js-2.0"
    code = fn["code"]
    # The rewrite anchors on the auth origin and targets the site domain,
    # preserving the redirect path/query (Cognito returns absolute redirects).
    assert "${var.auth_origin_domain}" in code
    assert "${local.site_domain}" in code
    assert "indexOf(prefix) === 0" in code

    expected_paths = ["/login", "/logout", "/oauth2/*", "/.well-known/*", "/favicon.ico"]
    # The auth behaviors iterate local.auth_path_patterns; the local itself is
    # the contract (root paths, no /auth prefix).
    locals_block = block(cloudfront_module["locals"])
    assert locals_block["auth_path_patterns"] == expected_paths

    auth_specs = [e["ordered_cache_behavior"] for e in dist.get("dynamic", []) if "ordered_cache_behavior" in e]
    auth_spec = next(
        s for s in auth_specs if s["for_each"] == "${var.auth_origin_domain != null ? local.auth_path_patterns : []}"
    )
    behavior = auth_spec["content"][0]
    assert behavior["path_pattern"] == "${ordered_cache_behavior.value}"
    for behavior in [behavior]:
        assert behavior["target_origin_id"] == "${local.auth_origin_id}"
        assert behavior["forwarded_values"][0]["cookies"][0]["forward"] == "all"
        assoc = behavior["function_association"][0]
        assert assoc["event_type"] == "viewer-response"
        assert assoc["function_arn"] == "${aws_cloudfront_function.auth_location_rewrite[0].arn}"


def test_response_headers_policy_enforces_security_headers(cloudfront_module):
    doc = cloudfront_module["response_headers"]
    policy = first_resource(doc, "aws_cloudfront_response_headers_policy", "security")
    sec = block(policy["security_headers_config"])

    # The CSP text lives in a local; the policy references it.
    csp = block(sec["content_security_policy"])
    assert csp["override"] is True
    assert csp["content_security_policy"] == "${local.csp}"
    locals_block = block(doc["locals"])
    csp_text = locals_block["csp"]
    assert "frame-ancestors 'none'" in csp_text
    assert "default-src 'self'" in csp_text

    frame = block(sec["frame_options"])
    assert frame["frame_option"] == "DENY"
    assert frame["override"] is True

    cto = block(sec["content_type_options"])
    assert cto["override"] is True

    ref = block(sec["referrer_policy"])
    assert ref["referrer_policy"] == "strict-origin-when-cross-origin"
    assert ref["override"] is True

    hsts = block(sec["strict_transport_security"])
    assert hsts["access_control_max_age_sec"] == 300
    assert hsts["override"] is True

    # The policy is attached to the default (/*) behavior.
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    default = block(dist["default_cache_behavior"])
    assert default["response_headers_policy_id"] == ("${aws_cloudfront_response_headers_policy.security.id}")


def test_spa_fallback_and_s3_default_behavior_unchanged(cloudfront_module):
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    default = block(dist["default_cache_behavior"])
    assert default["target_origin_id"] == "S3-${var.static_bucket_id}"
    errors = {e["error_code"]: e["response_page_path"] for e in dist["custom_error_response"]}
    assert errors.get(404) == "/index.html"
    assert errors.get(403) == "/index.html"


# ---------------------------------------------------------------------------
# Environment wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_env_wires_single_waf_into_distribution(env_name):
    doc = load_hcl(TF_APP / "environments" / env_name / "main.tf")
    waf_mods = modules(doc, "waf")
    assert len(waf_mods) == 1
    cf_mods = modules(doc, "cloudfront")
    assert len(cf_mods) == 1
    assert cf_mods[0]["web_acl_id"] == "${module.waf.web_acl_id}"
    # AppSync default endpoint hostname, custom-domain name deliberately unused.
    assert cf_mods[0]["api_origin_domain"] == (
        '${replace(replace(module.appsync.api_url, "https://", ""), "/graphql", "")}'
    )
    assert cf_mods[0]["auth_origin_domain"] == "${local.login_domain}"


def test_ephemeral_waf_noops_without_cloudfront():
    doc = load_hcl(TF_APP / "environments" / "ephemeral" / "main.tf")
    waf_mods = modules(doc, "waf")
    assert len(waf_mods) == 1
    assert waf_mods[0]["create"] is False
    assert modules(doc, "cloudfront") == []


def test_route53_api_record_removed_login_record_kept(route53_module):
    record_names = [label for label, _ in resources(route53_module, "aws_route53_record")]
    assert "api" not in record_names, "the unreferenced api record must be removed"
    assert "login" in record_names, "login record is load-bearing origin plumbing"


# ---------------------------------------------------------------------------
# Frontend build contract
# ---------------------------------------------------------------------------


def test_deploy_workflow_stops_setting_absolute_frontend_endpoints():
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml").read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    build_steps = [s for s in steps if "Build and deploy frontend" in s.get("name", "")]
    assert len(build_steps) == 1
    env = build_steps[0].get("env", {})
    assert "VITE_APPSYNC_ENDPOINT" not in env
    assert "VITE_COGNITO_DOMAIN" not in env
    assert env["VITE_OAUTH_REDIRECT_SIGNIN"] == "${{ steps.tofu_outputs.outputs.site_url }}"
    assert env["VITE_OAUTH_REDIRECT_SIGNOUT"] == "${{ steps.tofu_outputs.outputs.site_url }}"


def test_ephemeral_env_keeps_absolute_frontend_endpoints():
    script = (REPO_ROOT / "scripts" / "ephemeral-env.sh").read_text()
    assert "export VITE_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)" in script
    assert "export VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN" in script
