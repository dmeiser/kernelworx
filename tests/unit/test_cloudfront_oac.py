"""Focused tests for the CloudFront S3 origin migration from the deprecated
Origin Access Identity (OAI) to Origin Access Control (OAC) (#335), plus the
one-time destroy-ordering scaffold that fixes the resulting deploy failure.

#335/#359 removed aws_cloudfront_origin_access_identity.main from the config,
leaving a dangling destroy in state; because nothing references the OAI,
OpenTofu scheduled its destroy before/parallel to the OAC cutover and
CloudFront rejected it (CloudFrontOriginAccessIdentityInUse — the live
distribution still referenced the OAI until the cutover Deployed). The module
carries a one-time scaffold (to be removed in a follow-up once the legacy OAI
is destroyed in all environments):

- terraform_data.legacy_oai_destroy_gate polls
  `aws cloudfront get-distribution --query 'Distribution.Status'` until the
  distribution reaches Deployed (the OAI InUse check runs against the live
  config; UpdateDistribution returns at acceptance, before signing switches).
- aws_cloudfront_origin_access_identity.main is re-added with count = 0 purely
  to order the dangling state destroy after that gate.
- aws_s3_bucket_policy.static depends on the gate so the principal flip (OAI
  canonical user -> Service+SourceArn) cannot cut S3 access for the live
  distribution while it still signs as the OAI.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the *meaning* of the OAC contract:

- No aws_cloudfront_origin_access_identity resource exists anywhere in the
  tofu tree except the count-0 destroy-ordering scaffold in the cloudfront
  module (OAI is deprecated: no SSE-KMS, no dynamic requests, legacy request
  signing).
- The cloudfront module defines aws_cloudfront_origin_access_control.main
  with origin type "s3", signing behavior "always", and sigv4 signing.
- The distribution's S3 origin references the OAC and no longer sets an
  OAI path.
- The static bucket policy grants s3:GetObject to the
  cloudfront.amazonaws.com service principal, scoped to this distribution
  via the AWS:SourceArn condition (the OAC signing model), instead of the
  OAI canonical user, and waits for the Deployed gate before flipping.
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
        for name, oai in resources(doc, "aws_cloudfront_origin_access_identity"):
            # The only permitted occurrence is the one-time destroy-ordering
            # scaffold in the cloudfront module (count = 0, never created;
            # exists solely to order the dangling state destroy after the
            # Deployed gate). Remove this allowance with the scaffold.
            assert name == "main" and oai.get("count") == 0, (
                "aws_cloudfront_origin_access_identity is deprecated (#335); "
                "use aws_cloudfront_origin_access_control instead"
            )


def test_legacy_oai_scaffold_is_destroy_only(cloudfront_doc: dict) -> None:
    oai = first_resource(cloudfront_doc, "aws_cloudfront_origin_access_identity", "main")
    assert oai["count"] == 0, "scaffold must never create an OAI"
    assert oai["depends_on"] == ["${terraform_data.legacy_oai_destroy_gate}"], (
        "the dangling OAI destroy must be ordered after the Deployed gate"
    )


def test_legacy_oai_destroy_gate_polls_for_deployed(cloudfront_doc: dict) -> None:
    gate = first_resource(cloudfront_doc, "terraform_data", "legacy_oai_destroy_gate")
    assert gate["depends_on"] == ["${aws_cloudfront_distribution.site}"]
    provisioner = block(gate.get("provisioner"))
    assert "local-exec" in provisioner, "gate must run a local-exec poll"
    command = provisioner["local-exec"]["command"]
    assert "aws cloudfront get-distribution" in command
    assert "Distribution.Status" in command
    assert "Deployed" in command
    assert "exit 1" in command, "the gate must fail the apply if the distribution never deploys"


def test_bucket_policy_waits_for_deployed_gate(cloudfront_doc: dict) -> None:
    policy = first_resource(cloudfront_doc, "aws_s3_bucket_policy", "static")
    assert policy["depends_on"] == ["${terraform_data.legacy_oai_destroy_gate}"], (
        "the bucket-policy principal flip must wait for the OAC cutover to Deploy"
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
