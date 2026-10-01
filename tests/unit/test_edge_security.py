"""Focused tests for the single-distribution edge security architecture (#165/#166).

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the *meaning* of the edge architecture contract:

- Exactly one WAF exists anywhere: a CLOUDFRONT-scope aws_wafv2_web_acl
  attached via web_acl_id. No regional web ACLs, no
  aws_wafv2_web_acl_association resources.
- The WAF lets GitHub Actions CI ranges skip the per-IP rate rule via a
  deploy-time IP set scoped down into it, and rate limits other traffic at
  2000 requests per IP per 300s; the AWS managed
  core rule set is staged in Count. WAF access logging is deliberately gone
  (#665, CloudFront pricing plans Free tier): no logging configuration, no
  aws-waf-logs-* log group, no log-delivery resource policy. Every WAF
  resource no-ops when create = false so ephemeral environments create zero
  objects.
- The existing CloudFront distribution gains /graphql and auth ordered
  behaviors in place (prevent_destroy intact). #665: every behavior uses
  AWS-managed cache/origin-request policies (Managed-CachingDisabled +
  Managed-AllViewerExceptHostHeader on /graphql and the auth paths,
  Managed-CachingOptimized on the default S3 behavior) — no legacy
  forwarded_values or behavior-level TTLs anywhere; the auth paths run the
  viewer-response Location-rewrite function.
- Security headers come from the AWS-managed SecurityHeadersPolicy
  (67f7725c-6f97-4210-82d7-5512b31e9d03) attached to the default behavior and
  all auth behaviors. There is NO custom aws_cloudfront_response_headers_policy
  resource anywhere: custom policies are a Business-tier feature and the
  #665 Free-tier decision removed them, along with the per-environment HSTS
  ramp (#430) — the managed policy carries fixed max-age=31536000.
- The application CSP survives only as the <meta> tag in frontend/index.html;
  there is no CSP response header to mirror against. Accepted #665 trade-offs
  (managed XFO SAMEORIGIN instead of DENY, loss of frame-ancestors, meta-only
  CSP) are recorded in AGENTS.md and are not to be re-opened.
- Dev/prod wire the WAF into the distribution; ephemeral passes create =
  false and has no CloudFront at all. The api Route53 record is gone while
  the load-bearing login record remains.
- Behavior count: default + /graphql + /l* + /oauth2/* + /.well-known/* = 5,
  the CloudFront Free plan cap (hard, not increasable). /l* is a wildcard:
  no SPA route may ever start with /l. The favicons ship from S3 via the
  default behavior (the old /favicon.ico Cognito proxy behavior is gone).
- The dev/prod frontend build contract: deploy-shared.yml stops exporting
  VITE_APPSYNC_ENDPOINT / VITE_COGNITO_DOMAIN, while ephemeral-env.sh keeps
  exporting both as absolute values.
"""

from __future__ import annotations

import json
import re
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
    return load_hcl(TF_APP / "modules" / "cloudfront" / "main.tf")


# Stable AWS-published IDs of the managed policies the module pins (#665).
MANAGED_SECURITY_HEADERS_POLICY_ID = "67f7725c-6f97-4210-82d7-5512b31e9d03"
MANAGED_CACHE_DISABLED_POLICY_ID = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
MANAGED_CACHE_OPTIMIZED_POLICY_ID = "658327ea-f89d-4fab-a63d-7e88639e58f6"
MANAGED_ALL_VIEWER_EXCEPT_HOST_POLICY_ID = "b689b0a8-53d0-40ab-baf2-68738e2966ac"


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

    # GitHub Actions CI exemption — implemented as a scope-down on the
    # rate-based statement (NOT a terminal priority-1 allow rule, which would
    # also exempt CI traffic from the managed core rule set at priority 3).
    rate_rule = next(r for r in acl["rule"] if r["name"] == "rate-limit")
    assert rate_rule["priority"] == 2
    rate_stmt = block(block(rate_rule["statement"])["rate_based_statement"])
    scope_down = block(rate_stmt["scope_down_statement"])
    not_stmt = block(block(scope_down["not_statement"])["statement"])
    ip_set_ref = block(not_stmt["ip_set_reference_statement"])
    assert ip_set_ref["arn"] == "${aws_wafv2_ip_set.github_actions[0].arn}"
    assert not [r for r in acl["rule"] if r["name"] == "github-actions-allowlist"]
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
    assert managed["priority"] == 3
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


def test_waf_github_actions_ip_set_contract(waf_module):
    ip_set = first_resource(waf_module, "aws_wafv2_ip_set", "github_actions")
    assert ip_set["name"] == "${local.name}-github-actions"
    assert ip_set["scope"] == "CLOUDFRONT"
    assert ip_set["ip_address_version"] == "IPV4"
    assert ip_set["addresses"] == "${local.github_actions_cidrs}"

    lifecycle = block(ip_set["lifecycle"])
    preconditions = [block(p) for p in lifecycle.get("precondition", [])]
    assert len(preconditions) == 2
    assert 'contains(keys(local.github_meta_response), "actions")' in preconditions[0]["condition"]
    assert "10000" in preconditions[1]["condition"]

    data_http = [bodies for entry in waf_module.get("data", []) for dtype, bodies in entry.items() if dtype == "http"]
    assert data_http, "http data source for github_meta not found"
    meta_doc = list(data_http[0].values())[0]
    assert meta_doc["url"] == "https://api.github.com/meta"
    assert meta_doc["count"] == "${var.create ? 1 : 0}"


def test_waf_access_logging_resources_absent(waf_module):
    """#665: WAF access logs are not eligible on the CloudFront Free pricing
    plan, so the whole logging stack is gone: logging configuration,
    aws-waf-logs-* log group, and the log-delivery resource policy (plus the
    IAM policy document data source that only fed it). The web ACL, IP set,
    rate rule, managed core rules, and CloudWatch metrics all stay."""
    assert resources(waf_module, "aws_wafv2_web_acl_logging_configuration") == []
    assert resources(waf_module, "aws_cloudwatch_log_group") == []
    assert resources(waf_module, "aws_cloudwatch_log_resource_policy") == []
    assert not [
        bodies
        for entry in waf_module.get("data", [])
        for dtype, bodies in entry.items()
        if dtype == "aws_iam_policy_document"
    ]


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
    reqs = block(block(doc["terraform"][0])["required_providers"][0])
    aws_req = reqs["aws"]
    assert aws_req["version"] == "~> 6.56"
    http_req = reqs["http"]
    assert http_req["source"] == "hashicorp/http"
    assert http_req["version"] == "~> 3.0"
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
    # #665: managed policies replace forwarded_values + behavior TTLs.
    # Managed-CachingDisabled keeps TTLs at 0; Managed-AllViewerExceptHostHeader
    # forwards Authorization/Content-Type/Accept and all cookies.
    assert behavior["cache_policy_id"] == "${local.managed_cache_disabled_policy_id}"
    assert behavior["origin_request_policy_id"] == "${local.managed_all_viewer_except_host_policy_id}"
    assert "forwarded_values" not in behavior
    for legacy in ("min_ttl", "default_ttl", "max_ttl"):
        assert legacy not in behavior

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

    expected_paths = ["/l*", "/oauth2/*", "/.well-known/*"]
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
        # Cookies must flow to Cognito: same managed pair as /graphql (#665).
        assert behavior["cache_policy_id"] == "${local.managed_cache_disabled_policy_id}"
        assert behavior["origin_request_policy_id"] == "${local.managed_all_viewer_except_host_policy_id}"
        assert "forwarded_values" not in behavior
        for legacy in ("min_ttl", "default_ttl", "max_ttl"):
            assert legacy not in behavior
        assoc = behavior["function_association"][0]
        assert assoc["event_type"] == "viewer-response"
        assert assoc["function_arn"] == "${aws_cloudfront_function.auth_location_rewrite[0].arn}"


def _all_cache_behaviors(cloudfront_module) -> list[dict]:
    """Every cache behavior body: the default plus each ordered behavior content."""
    dist = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    behaviors = [block(dist["default_cache_behavior"])]
    for spec in dist.get("dynamic", []):
        if "ordered_cache_behavior" in spec:
            behaviors.extend(spec["ordered_cache_behavior"]["content"])
    return behaviors


def test_no_custom_response_headers_policy_anywhere(cloudfront_module):
    """#665: custom response headers policies are a Business-tier feature, so
    none may exist in the module - the AWS-managed SecurityHeadersPolicy is
    the only headers mechanism."""
    assert resources(cloudfront_module, "aws_cloudfront_response_headers_policy") == []
    # The hsts ramp inputs (#430) died with the custom policies: the managed
    # policy's fixed max-age=31536000 is the only HSTS now.
    defaults = variable_defaults(cloudfront_module)
    assert "hsts_max_age_sec" not in defaults
    assert "hsts_include_subdomains" not in defaults


def test_all_cache_behaviors_attach_managed_security_headers_policy(cloudfront_module):
    """#166/#550/#665: the default behavior and every auth behavior carry the
    AWS-managed SecurityHeadersPolicy (nosniff, Referrer-Policy, HSTS
    max-age=31536000, XFO SAMEORIGIN). It is a managed policy, so it is
    referenced by the stable AWS-published ID pinned in the module locals."""
    locals_block = block(cloudfront_module["locals"])
    assert locals_block["managed_security_headers_policy_id"] == MANAGED_SECURITY_HEADERS_POLICY_ID
    for behavior in _all_cache_behaviors(cloudfront_module):
        if behavior.get("path_pattern") == "/graphql":
            # API responses never carried a headers policy and still don't.
            assert "response_headers_policy_id" not in behavior
            continue
        assert behavior.get("response_headers_policy_id") == "${local.managed_security_headers_policy_id}", (
            f"behavior {behavior.get('path_pattern', '(default)')} must attach the managed SecurityHeadersPolicy"
        )


def test_managed_cache_policies_and_no_legacy_settings(cloudfront_module):
    """#665: every behavior uses managed cache policies - no legacy
    forwarded_values, no behavior-level min/max/default TTLs anywhere.
    /graphql and the auth behaviors pair Managed-CachingDisabled with
    Managed-AllViewerExceptHostHeader; the default S3 behavior uses
    Managed-CachingOptimized with no origin request policy."""
    locals_block = block(cloudfront_module["locals"])
    assert locals_block["managed_cache_disabled_policy_id"] == MANAGED_CACHE_DISABLED_POLICY_ID
    assert locals_block["managed_cache_optimized_policy_id"] == MANAGED_CACHE_OPTIMIZED_POLICY_ID
    assert locals_block["managed_all_viewer_except_host_policy_id"] == MANAGED_ALL_VIEWER_EXCEPT_HOST_POLICY_ID

    default = _all_cache_behaviors(cloudfront_module)[0]
    assert default["cache_policy_id"] == "${local.managed_cache_optimized_policy_id}"
    assert "origin_request_policy_id" not in default

    for behavior in _all_cache_behaviors(cloudfront_module):
        assert "forwarded_values" not in behavior
        for legacy in ("min_ttl", "default_ttl", "max_ttl"):
            assert legacy not in behavior, f"legacy {legacy} survives on {behavior.get('path_pattern', '(default)')}"


def test_behavior_count_within_free_tier_cap(cloudfront_module):
    """The CloudFront Free plan caps cache behaviors at 5 (hard, not
    increasable). Realized count: default + /graphql + the auth path
    patterns. /l* is a wildcard covering /login and /logout - no SPA route
    may ever start with /l."""
    locals_block = block(cloudfront_module["locals"])
    auth_paths = locals_block["auth_path_patterns"]
    assert auth_paths == ["/l*", "/oauth2/*", "/.well-known/*"]
    assert 1 + 1 + len(auth_paths) <= 5


def test_distribution_carries_no_price_class(cloudfront_module):
    """#665: the Free flat-rate plan rejects any distribution that carries a
    price class. UpdateDistribution fails with "Distributions with the Free
    pricing plan can't have the following features: Price class" (deploy run
    36811076298), so the attribute must stay unset rather than pinned to
    PriceClass_100."""
    distribution = first_resource(cloudfront_module, "aws_cloudfront_distribution", "site")
    assert "price_class" not in distribution, (
        "price_class is unsupported on the CloudFront flat-rate plan - omit it entirely"
    )


def test_index_html_carries_the_only_site_csp():
    """#665: the application CSP is meta-only. The custom response headers
    policy that used to deliver it as a header is gone (Business-tier
    feature), so the <meta> tag in frontend/index.html is the only CSP.
    There is no header CSP to mirror against; assert the meta tag itself."""
    html = (REPO_ROOT / "frontend" / "index.html").read_text()
    match = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert match, "index.html must carry the meta CSP - it is the only CSP left (#665)"
    csp = match.group(1)

    # The enumerated img-src and no-WebSockets connect-src invariants (#440)
    # survive on the meta copy.
    img_src = csp.split("img-src ")[1].split(";")[0]
    assert "https:" not in img_src.split(), "img-src must not allow arbitrary https: images"
    assert "'self'" in img_src
    assert "data:" in img_src
    assert "blob:" in img_src
    for env in ("dev", "prod"):
        assert f"https://kernelworx-exports-ue1-{env}.s3.us-east-1.amazonaws.com" in img_src
        assert f"https://kernelworx-exports-ue1-{env}.s3.amazonaws.com" in img_src

    connect_src = csp.split("connect-src ")[1].split(";")[0]
    assert "ws:" not in connect_src
    assert "wss:" not in connect_src


def test_img_src_allows_real_presigned_qr_url_host(cloudfront_module):
    """#440 regression: a real boto3-generated presigned QR URL must load.

    The pinned boto3/botocore in the Lambda layer defaults to the legacy
    global S3 endpoint for us-east-1, so presigned GET URLs carry the
    <bucket>.s3.amazonaws.com host. Generates a real presigned URL and
    asserts its host is admitted by the baked frontend <meta> CSP - the only
    CSP since #665 removed the header copy.
    """
    from urllib.parse import urlparse

    import boto3

    html = (REPO_ROOT / "frontend" / "index.html").read_text()
    meta_csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html).group(1)

    for env in ("dev", "prod"):
        bucket = f"kernelworx-exports-ue1-{env}"
        s3 = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": "payment-qr-codes/a/b.png"},
            ExpiresIn=3600,
        )
        host = urlparse(url).netloc

        meta_img_src = meta_csp.split("img-src ")[1].split(";")[0]
        assert f"https://{host}" in meta_img_src.split(), f"{env} meta CSP blocks presigned QR host {host}"


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
    assert cf_mods[0]["web_acl_id"] == "${module.waf.web_acl_arn}"
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
