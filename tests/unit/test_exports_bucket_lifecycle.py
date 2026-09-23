"""Exports-bucket lifecycle contract (issue #442, widened bucket-wide).

The exports bucket has versioning enabled. The lifecycle configuration must:

* Expire the accumulated noncurrent object versions and expired-object delete
  markers, and abort abandoned multipart uploads, across the WHOLE bucket — not
  just under reports/. The bucket also stores payment-method QR-code images
  under a different prefix, and with versioning on, their versions and
  delete-markers would otherwise accumulate forever (#442).
* Keep the 7-day CURRENT-object expiration scoped to reports/ only: QR codes
  must NOT be deleted after 7 days.

S3 allows at most one whole-bucket (prefix-less) rule per configuration, so the
three cleanup actions share a single rule; the reports/-scoped current-object
expiration is a separate, filtered rule.

This test parses the s3 module with python-hcl2 into a semantic model and
asserts the *meaning* of that contract (the same approach as
test_cloudfront_oac.py / test_edge_security.py), rather than grepping for
strings. It fails on the pre-widen configuration (which scoped every rule to
reports/) and passes after the fix.
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


def _has_filter(rule: dict) -> bool:
    """True when the rule carries a Filter (any prefix), i.e. is not whole-bucket."""
    return "filter" in rule and bool(rule["filter"])


def test_exports_bucket_versioning_enabled():
    versioning = _resources(_load_module(), "aws_s3_bucket_versioning")
    assert "exports" in versioning, "no versioning block for the exports bucket"
    assert versioning["exports"]["versioning_configuration"][0]["status"] == "Enabled"


def test_cleanup_actions_are_whole_bucket():
    """NCV expiration, delete-marker cleanup, and multipart abort cover the
    whole bucket (no prefix filter). S3 allows only one prefix-less rule, so
    exactly one filter-less rule exists and it carries all three actions."""
    rules = _exports_lifecycle_rules(_load_module())
    assert rules, "no lifecycle configuration found for the exports bucket"

    unfiltered = [r for r in rules if not _has_filter(r)]
    assert len(unfiltered) == 1, (
        f"expected exactly one whole-bucket (filter-less) rule, "
        f"found {len(unfiltered)}"
    )
    whole = unfiltered[0]
    assert whole["status"] == "Enabled"

    # Noncurrent versions must expire, or they accumulate permanently (#442).
    noncurrent = whole["noncurrent_version_expiration"][0]
    assert noncurrent["noncurrent_days"] > 0

    # Abandoned multipart uploads must be aborted (#442).
    abort = whole["abort_incomplete_multipart_upload"][0]
    assert abort["days_after_initiation"] > 0

    # Expired-object delete markers must be removed (#442). This action cannot
    # share a rule with a Days-based Expiration, but it CAN share a rule with
    # NoncurrentVersionExpiration, which is why it lives on the whole-bucket
    # rule rather than its own (S3 permits only one prefix-less rule).
    expiration = whole["expiration"][0]
    assert expiration["expired_object_delete_marker"] is True
    # Days/Date and ExpiredObjectDeleteMarker are mutually exclusive in one
    # S3 Lifecycle Expiration, so the marker-carrying rule sets neither.
    assert "days" not in expiration
    assert "date" not in expiration


def test_current_object_expiration_stays_reports_scoped():
    """The 7-day CURRENT-object expiration applies to reports/ only, so QR
    codes under a different prefix are never deleted after 7 days."""
    rules = _exports_lifecycle_rules(_load_module())

    report_rule = next(
        (r for r in rules if r.get("filter") and r["filter"][0].get("prefix") == "reports/"),
        None,
    )
    assert report_rule is not None, "expected the reports/-scoped lifecycle rule"
    assert report_rule["status"] == "Enabled"

    expiration = report_rule["expiration"][0]
    assert expiration["days"] == 7
    assert "expired_object_delete_marker" not in expiration

    # The reports/-scoped rule must not also carry the whole-bucket cleanup
    # actions; those belong on the single filter-less rule.
    assert "noncurrent_version_expiration" not in report_rule
    assert "abort_incomplete_multipart_upload" not in report_rule

    # No other rule may expire current objects (no second Days-based rule).
    for r in rules:
        if r is report_rule:
            continue
        if "expiration" in r:
            exp = r["expiration"][0]
            assert "days" not in exp, "a second Days-based current-object rule must not exist"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
