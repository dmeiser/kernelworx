"""Focused tests for the AppSync Lambda invoke policy guard (#327).

The `appsync_lambda` policy document previously fell back to
`resources = ["*"]` when `var.lambda_function_arns` was empty, granting the
AppSync service role `lambda:InvokeFunction` on every Lambda in the account.
The data source and role policy are now count-guarded and omitted entirely
when no Lambda ARNs are configured; the statement references only
`local.lambda_invoke_arns`.

These tests parse the OpenTofu module into a semantic model (via python-hcl2)
and assert the guard contract:

- Both `data.aws_iam_policy_document.appsync_lambda` and
  `aws_iam_role_policy.appsync_lambda` carry
  `count = length(local.lambda_invoke_arns) > 0 ? 1 : 0`, so an empty ARN
  list yields no policy at all.
- The invoke statement's resources are exactly `local.lambda_invoke_arns`;
  there is no `["*"]` wildcard fallback anywhere in the document.
"""

from __future__ import annotations

import json
from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
IAM_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"

EXPECTED_COUNT_EXPR = "length(local.lambda_invoke_arns) > 0 ? 1 : 0"


def _norm(value):
    """Strip the quote wrapper python-hcl2 adds around keys and strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ("__is_block__", "__comments__"):
                continue
            out[_norm(k)] = _norm(v)
        return out
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _load() -> dict:
    with IAM_MODULE.open() as f:
        return _norm(hcl2.load(f))


def _find(blocks: list[dict], btype: str, name: str) -> dict:
    matches = [b[btype][name] for b in blocks if btype in b and name in b[btype]]
    assert len(matches) == 1, f"expected exactly one {btype}.{name}, got {len(matches)}"
    return matches[0]


def _unwrap_interpolation(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return value[2:-1]
    return value


def test_appsync_lambda_policy_document_is_count_guarded():
    doc = _find(_load()["data"], "aws_iam_policy_document", "appsync_lambda")
    assert _unwrap_interpolation(doc["count"]) == EXPECTED_COUNT_EXPR


def test_appsync_lambda_role_policy_is_count_guarded():
    policy = _find(_load()["resource"], "aws_iam_role_policy", "appsync_lambda")
    assert _unwrap_interpolation(policy["count"]) == EXPECTED_COUNT_EXPR


def test_appsync_lambda_resources_have_no_wildcard_fallback():
    doc = _find(_load()["data"], "aws_iam_policy_document", "appsync_lambda")
    (statement,) = doc["statement"]
    assert statement["actions"] == ["lambda:InvokeFunction"]
    # hcl2 wraps interpolated identifiers in ${} and parses a bare reference
    # (no brackets) as a string; normalize to a list for comparison.
    raw = statement["resources"]
    raw = raw if isinstance(raw, list) else [raw]
    resources = [_unwrap_interpolation(r) for r in raw]
    assert resources == ["local.lambda_invoke_arns"]
    assert "*" not in resources
