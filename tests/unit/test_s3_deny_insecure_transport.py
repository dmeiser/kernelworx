"""Deny-insecure-transport contract for the S3 buckets (#525).

Both application buckets (static assets, exports) must carry the standard
CIS/KICS control: a bucket-policy statement that Denies `s3:*` when
`aws:SecureTransport` is false. The exports bucket holds customer PII
(report CSVs, payment-method QR images) and the static bucket fronts the
site; every legitimate access path is already TLS (CloudFront OAC signing,
boto3 defaults, browser fetches against pre-signed `https://` URLs), so the
statement blocks only plaintext misconfiguration.

The static bucket's single bucket policy lives in the cloudfront module
(S3 allows exactly one policy per bucket; it grants the CloudFront service
principal via OAC), so the deny statement is asserted there alongside the
existing allow. The exports bucket's policy lives in the s3 module.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2, same approach as test_exports_bucket_lifecycle.py /
test_cloudfront_oac.py) and assert the *meaning* of the statements. They
fail on the pre-fix configuration (no deny statement anywhere) and pass
after the fix.
"""

from __future__ import annotations

import io

import hcl2
import pytest

from tests.unit.test_edge_security import (
    TF_APP,
    _clean,
    first_resource,
    load_hcl,
)

S3_MODULE = TF_APP / "modules" / "s3" / "main.tf"
CLOUDFRONT_MODULE = TF_APP / "modules" / "cloudfront" / "main.tf"


def _parse_jsonencode_policy(policy_expr: str) -> dict:
    """Parse the inner object of a jsonencode(...) policy argument."""
    prefix = "${jsonencode("
    assert isinstance(policy_expr, str) and policy_expr.startswith(prefix) and policy_expr.endswith(")}"), (
        "expected a jsonencode(...) policy expression"
    )
    inner = policy_expr[len(prefix) : -2]
    return _clean(hcl2.load(io.StringIO(f"policy = {inner}")))["policy"]


def _norm_expr(value: str) -> str:
    """Strip the ${...} wrapper python-hcl2 leaves on interpolations."""
    if isinstance(value, str):
        return value.replace("${", "").replace("}", "")
    return value


def _stmt_value(stmt: dict, *keys: str):
    """Read a statement field from either a jsonencode policy (JSON keys) or
    an aws_iam_policy_document data source (lowercase HCL block keys)."""
    for key in keys:
        if key in stmt:
            return stmt[key]
    return None


def _denies_insecure_transport(stmt: dict) -> bool:
    """True when the statement is the DenyInsecureTransport control: Deny
    s3:* when aws:SecureTransport is false (both condition encodings)."""
    condition = _stmt_value(stmt, "Condition", "condition")
    if isinstance(condition, list):  # data-source block shape
        matches = any(
            c.get("test") == "Bool"
            and _norm_expr(c.get("variable", "")) == "aws:SecureTransport"
            and c.get("values") == ["false"]
            for c in condition
        )
    else:  # jsonencode policy shape
        matches = condition == {"Bool": {"aws:SecureTransport": "false"}}
    return (
        _stmt_value(stmt, "Sid", "sid") == "DenyInsecureTransport"
        and _stmt_value(stmt, "Effect", "effect") == "Deny"
        and matches
    )


def _deny_insecure_statements(statements: list[dict]) -> list[dict]:
    return [s for s in statements if _denies_insecure_transport(s)]


@pytest.fixture(scope="module")
def s3_doc() -> dict:
    return load_hcl(S3_MODULE)


@pytest.fixture(scope="module")
def cloudfront_doc() -> dict:
    return load_hcl(CLOUDFRONT_MODULE)


def _assert_deny_statement(stmt: dict, bucket_arn_expr: str, bucket_label: str) -> None:
    """The deny statement covers s3:* on the bucket and its objects for every
    principal, and only fires on plaintext (aws:SecureTransport=false), so
    HTTPS access — including all existing principals — is left intact."""
    actions = _stmt_value(stmt, "Action", "actions")
    assert actions == "s3:*" or actions == ["s3:*"]
    principal = _stmt_value(stmt, "Principal", "principals")
    if isinstance(principal, list):  # data-source principals { ... } block
        assert principal == [{"type": "*", "identifiers": ["*"]}]
    else:
        assert principal in ("*", {"AWS": "*"}), "deny must apply to every principal"
    resources = [_norm_expr(r) for r in _stmt_value(stmt, "Resource", "resources")]
    assert resources == [bucket_arn_expr, f"{bucket_arn_expr}/*"], (
        f"{bucket_label}: deny must cover the bucket and its objects"
    )


def test_exports_bucket_policy_denies_insecure_transport(s3_doc: dict) -> None:
    """The exports bucket gets its own policy (in the s3 module) with the
    DenyInsecureTransport statement (#525)."""
    policy = first_resource(s3_doc, "aws_s3_bucket_policy", "exports")
    assert policy["bucket"] == "${aws_s3_bucket.exports.id}", "exports bucket policy must attach to the exports bucket"
    data = s3_doc.get("data", [])
    deny_docs = [
        body
        for entry in data
        for dtype, bodies in entry.items()
        if dtype == "aws_iam_policy_document"
        for label, body in bodies.items()
        if body.get("statement", [{}])[0].get("sid") == "DenyInsecureTransport"
    ]
    assert deny_docs, "no aws_iam_policy_document carries the DenyInsecureTransport statement"
    stmt = deny_docs[0]["statement"][0]
    _assert_deny_statement(stmt, "aws_s3_bucket.exports.arn", "exports")

    # The policy document must not silently grant anything: existing exports
    # access is via IAM roles, so the bucket policy carries the deny only.
    assert len(deny_docs[0]["statement"]) == 1
    assert policy["policy"] == "${data.aws_iam_policy_document.exports_deny_insecure_transport.json}"


def test_static_bucket_policy_denies_insecure_transport(cloudfront_doc: dict) -> None:
    """The static bucket's single policy (cloudfront module) gains the
    DenyInsecureTransport statement without dropping the CloudFront grant,
    and no second policy for the static bucket appears anywhere (#525)."""
    policy = first_resource(cloudfront_doc, "aws_s3_bucket_policy", "static")
    doc = _parse_jsonencode_policy(policy["policy"])
    statements = doc["Statement"]

    denies = _deny_insecure_statements(statements)
    assert len(denies) == 1, "static bucket policy must deny non-TLS requests"
    _assert_deny_statement(denies[0], "var.static_bucket_arn", "static")

    # Existing access pattern intact: CloudFront still reaches the bucket
    # over HTTPS via the OAC service-principal grant scoped to this
    # distribution.
    allows = [s for s in statements if s.get("Sid") == "AllowCloudFrontAccess"]
    assert len(allows) == 1
    assert allows[0]["Effect"] == "Allow"
    assert allows[0]["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert allows[0]["Action"] == "s3:GetObject"
    assert allows[0]["Condition"] == {"StringEquals": {"AWS:SourceArn": "${aws_cloudfront_distribution.site.arn}"}}


def test_static_bucket_has_no_second_policy(s3_doc: dict) -> None:
    """S3 allows exactly one policy per bucket; the static bucket's policy
    lives in the cloudfront module, so the s3 module must not add another."""
    for entry in s3_doc.get("resource", []):
        for rtype, bodies in entry.items():
            if rtype != "aws_s3_bucket_policy":
                continue
            for label, body in bodies.items():
                assert "static" not in str(body.get("bucket", "")), (
                    "a second aws_s3_bucket_policy for the static bucket must not exist"
                )


def test_no_other_buckets_gain_a_policy(s3_doc: dict) -> None:
    """Scope guard: only the exports bucket gains a policy in the s3 module
    (#525 touches the static and exports buckets and nothing else)."""
    policies = {}
    for entry in s3_doc.get("resource", []):
        for rtype, bodies in entry.items():
            if rtype != "aws_s3_bucket_policy":
                continue
            policies.update(bodies)
    assert list(policies) == ["exports"], f"unexpected bucket policies in the s3 module: {list(policies)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
