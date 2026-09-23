"""Exports-bucket lifecycle contract (issue #442).

The exports bucket has versioning enabled, so its lifecycle configuration must
expire the accumulated noncurrent object versions and expired-object delete
markers, and abort abandoned multipart uploads — not just expire current
objects under reports/. This test parses the s3 module with python-hcl2 into a
semantic model and asserts the *meaning* of that contract (the same approach as
test_cloudfront_oac.py / test_edge_security.py), rather than grepping for
strings. It fails on the pre-#442 configuration and passes after the fix.
"""

import json
from pathlib import Path

import hcl2
import pytest

S3_MODULE = Path(__file__).resolve().parent.parent.parent / "tofu/application/modules/s3/main.tf"


def _norm(key: str) -> str:
    """Strip the quote wrapper python-hcl2 adds around interpolated keys."""
    if isinstance(key, str) and key.startswith('"') and key.endswith('"'):
        return key[1:-1]
    return key


def _clean(value):
    """Drop python-hcl2 bookkeeping keys and decode interpolated strings."""
    if isinstance(value, dict):
        return {_norm(k): _clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _load_module() -> dict:
    with open(S3_MODULE, encoding="utf-8") as f:
        return _clean(hcl2.load(f))


def _resources(doc: dict, resource_type: str) -> dict:
    """Return {label: body} for every resource of the given type."""
    found = {}
    for entry in doc.get("resource", []):
        for rtype, bodies in entry.items():
            if rtype != resource_type:
                continue
            for label, attrs in bodies.items():
                found[_norm(label)] = attrs
    return found


def _exports_lifecycle_rules(doc: dict) -> list:
    rules = []
    for body in _resources(doc, "aws_s3_bucket_lifecycle_configuration").values():
        if "exports" in json.dumps(body.get("bucket", "")):
            rules.extend(body.get("rule", []))
    return rules


def test_exports_bucket_versioning_enabled():
    versioning = _resources(_load_module(), "aws_s3_bucket_versioning")
    assert "exports" in versioning, "no versioning block for the exports bucket"
    assert versioning["exports"]["versioning_configuration"][0]["status"] == "Enabled"


def test_reports_lifecycle_expires_all_accumulated_objects():
    rules = _exports_lifecycle_rules(_load_module())
    assert rules, "no lifecycle configuration found for the exports bucket"

    rule = next((r for r in rules if r.get("id") == "expire-old-reports"), None)
    assert rule is not None, "expected the expire-old-reports lifecycle rule"
    assert rule["status"] == "Enabled"
    assert rule["filter"][0]["prefix"] == "reports/"

    # Current objects still expire after 7 days. AWS forbids combining Days
    # with ExpiredObjectDeleteMarker in one Expiration block, so the delete
    # marker must live in its own rule (see the second test below).
    expiration = rule["expiration"][0]
    assert expiration["days"] == 7
    assert "expired_object_delete_marker" not in expiration

    # Noncurrent versions must expire, or they accumulate permanently (#442).
    noncurrent = rule["noncurrent_version_expiration"][0]
    assert noncurrent["noncurrent_days"] > 0

    # Abandoned multipart uploads must be aborted (#442).
    abort = rule["abort_incomplete_multipart_upload"][0]
    assert abort["days_after_initiation"] > 0


def test_expired_object_delete_markers_cleaned_by_separate_rule():
    rules = _exports_lifecycle_rules(_load_module())

    marker_rule = next(
        (r for r in rules if r.get("id") == "expire-reports-delete-markers"),
        None,
    )
    assert marker_rule is not None, "expected a dedicated rule removing expired object delete markers"
    assert marker_rule["status"] == "Enabled"
    assert marker_rule["filter"][0]["prefix"] == "reports/"

    expiration = marker_rule["expiration"][0]
    assert expiration["expired_object_delete_marker"] is True
    # Days/Date and ExpiredObjectDeleteMarker are mutually exclusive in one
    # S3 Lifecycle Expiration, so the marker rule must set neither.
    assert "days" not in expiration
    assert "date" not in expiration


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
