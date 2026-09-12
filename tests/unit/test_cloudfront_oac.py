"""Focused tests for the CloudFront S3 origin migration from the deprecated
Origin Access Identity (OAI) to Origin Access Control (OAC) (#335).

The one-time destroy-ordering scaffold that fixed the resulting deploy
failure (#374 count = 0 + depends_on, inert; #377 removed-block forget +
out-of-band CLI destroy gate) served its purpose and was removed in
KW-OAI-SCAFFOLD-CLEANUP-1: the legacy OAI is deleted from every environment,
so the module carries only the permanent OAC wiring.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the *meaning* of the OAC contract:

- No aws_cloudfront_origin_access_identity resource or removed block exists
  anywhere in the tofu tree (OAI is deprecated: no SSE-KMS, no dynamic
  requests, legacy request signing).
- The cloudfront module defines aws_cloudfront_origin_access_control.main
  with origin type "s3", signing behavior "always", and sigv4 signing.
- The distribution's S3 origin references the OAC and no longer sets an
  OAI path.
- The static bucket policy grants s3:GetObject to the
  cloudfront.amazonaws.com service principal, scoped to this distribution
  via the AWS:SourceArn condition (the OAC signing model), instead of the
  OAI canonical user.
"""

from __future__ import annotations

import io
from pathlib import Path

import hcl2
import pytest

from tests.unit.test_edge_security import (
    TF_APP,
    _clean,
    block,
    first_resource,
    load_hcl,
    resources,
)

CLOUDFRONT_DIR = TF_APP / "modules" / "cloudfront"


def _tf_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.tf") if ".terraform" not in p.parts)


@pytest.fixture(scope="module")
def cloudfront_doc() -> dict:
    return load_hcl(CLOUDFRONT_DIR / "main.tf")


@pytest.fixture(scope="module")
def all_tofu_docs() -> list[dict]:
    return [load_hcl(p) for p in _tf_files(TF_APP)]


def test_no_origin_access_identity_anywhere(all_tofu_docs: list[dict]) -> None:
    for doc in all_tofu_docs:
        assert resources(doc, "aws_cloudfront_origin_access_identity") == [], (
            "aws_cloudfront_origin_access_identity is deprecated (#335); "
            "the legacy OAI is deleted from every environment and its state "
            "object forgotten"
        )


def test_oac_defined_with_s3_always_sigv4(cloudfront_doc: dict) -> None:
    oac = first_resource(cloudfront_doc, "aws_cloudfront_origin_access_control", "main")
    assert oac["origin_access_control_origin_type"] == "s3"
    assert oac["signing_behavior"] == "always"
    assert oac["signing_protocol"] == "sigv4"
    lifecycle = block(oac.get("lifecycle"))
    assert lifecycle.get("prevent_destroy") is True


def test_distribution_s3_origin_uses_oac(cloudfront_doc: dict) -> None:
    dist = first_resource(cloudfront_doc, "aws_cloudfront_distribution", "site")
    origins = dist.get("origin", [])
    s3_origins = [o for o in origins if str(o.get("origin_id", "")).startswith("S3-")]
    assert s3_origins, "expected an S3 origin on the distribution"
    for origin in s3_origins:
        assert origin.get("origin_access_control_id") == ("${aws_cloudfront_origin_access_control.main.id}"), (
            "S3 origin must sign requests via the OAC"
        )
        s3_origin_config = block(origin.get("s3_origin_config"))
        assert s3_origin_config.get("origin_access_identity", "") == ""


def test_bucket_policy_grants_cloudfront_service_principal(cloudfront_doc: dict) -> None:
    policy = first_resource(cloudfront_doc, "aws_s3_bucket_policy", "static")
    raw = policy["policy"]
    # policy is a jsonencode(...) template; parse the inner object into a
    # semantic model rather than matching raw text.
    prefix = "${jsonencode("
    assert isinstance(raw, str) and raw.startswith(prefix) and raw.endswith(")}")
    inner = raw[len(prefix) : -2]
    doc = _clean(hcl2.load(io.StringIO(f"policy = {inner}")))["policy"]
    statements = doc["Statement"]
    allow = [s for s in statements if s.get("Sid") == "AllowCloudFrontAccess"]
    assert len(allow) == 1
    stmt = allow[0]
    assert stmt["Effect"] == "Allow"
    assert stmt["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert stmt["Action"] == "s3:GetObject"
    # Scoped to this distribution only; no OAI canonical user anywhere.
    condition = stmt["Condition"]
    assert condition == {"StringEquals": {"AWS:SourceArn": "${aws_cloudfront_distribution.site.arn}"}}
    assert "canonical" not in str(stmt["Principal"]).lower()


def test_no_removed_block_for_legacy_oai(cloudfront_doc: dict) -> None:
    # KW-OAI-SCAFFOLD-CLEANUP-1: the one-time forget block is gone along with
    # the legacy OAI itself; nothing may remain that references it.
    assert not cloudfront_doc.get("removed"), (
        "the removed block for aws_cloudfront_origin_access_identity.main was "
        "one-time scaffold and must not survive the cleanup"
    )
    assert resources(cloudfront_doc, "terraform_data") == [], (
        "no terraform_data resources may remain in the cloudfront module"
    )
