"""Least-privilege contract for the AppSync DynamoDB data-source policy (#459).

The `appsync_dynamodb` policy document grants the AppSync service role its
DynamoDB permissions. No AppSync JS resolver or VTL template in the
application issues a `Scan` operation, so the action set must not include
`dynamodb:Scan` (kernelworx issue #459).

These tests parse the OpenTofu IAM module into a semantic model (via
python-hcl2) and assert the rendered statement's action list exactly, so a
regression that re-adds `dynamodb:Scan` — or any other unexpected action —
fails the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
IAM_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"

# The complete set of DynamoDB operations the AppSync resolvers use: point
# reads/writes, GSI/key-condition queries, and batch variants. Scan is
# deliberately absent — nothing in js-resolvers/ or mapping-templates/
# issues it (#459).
EXPECTED_ACTIONS = [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
]


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


def _statement():
    doc = _find(_load()["data"], "aws_iam_policy_document", "appsync_dynamodb")
    (statement,) = doc["statement"]
    return statement


def test_appsync_dynamodb_policy_has_exact_least_privilege_actions():
    actions = _statement()["actions"]
    assert isinstance(actions, list)
    assert sorted(actions) == sorted(EXPECTED_ACTIONS)


def test_appsync_dynamodb_policy_does_not_allow_scan():
    actions = _statement()["actions"]
    assert "dynamodb:Scan" not in actions
    # No wildcard superset that would smuggle Scan back in either.
    assert "*" not in actions
    assert not any(a.endswith(":*") for a in actions)


def test_appsync_dynamodb_policy_scoped_to_tables_and_indexes():
    raw = _statement()["resources"]
    raw = raw if isinstance(raw, list) else [raw]
    # hcl2 parses a function-call resources value as a single ${...}
    # interpolation string; unwrap before comparing the semantic reference.
    resources = [
        r[2:-1] if isinstance(r, str) and r.startswith("${") and r.endswith("}") else r
        for r in raw
    ]
    assert resources == ["concat(local.dynamodb_table_arns, local.dynamodb_index_arns)"]
