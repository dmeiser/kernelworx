"""Contract tests for Cognito Advanced Security (user_pool_add_ons) on the user pool.

Issue #431: the pool must ship compromised-credential detection + adaptive auth
in AUDIT mode (detection without per-active-user ENFORCED billing). ENFORCED is
a deliberate, cost-bearing upgrade decision and must not appear here.
"""

from pathlib import Path

import hcl2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COGNITO_MAIN = REPO_ROOT / "tofu" / "application" / "modules" / "cognito" / "main.tf"


def _clean(val):
    """Strip the literal quote layer this python-hcl2 build wraps around tokens."""
    if isinstance(val, dict):
        return {_clean(k): _clean(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clean(x) for x in val]
    if isinstance(val, str) and val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


def _load(path: Path) -> dict:
    with path.open() as f:
        doc = hcl2.load(f)
    # Normalize the newer python-hcl2 shape (blocks as lists of one-key dicts)
    # into plain nested dicts.
    resources: dict = {}
    for entry in _clean(doc).get("resource", []):
        for rtype, names in entry.items():
            resources.setdefault(rtype, {}).update(names)
    return resources


def _user_pool(resources: dict) -> dict:
    pools = resources["aws_cognito_user_pool"]
    assert "main" in pools, "aws_cognito_user_pool.main must exist"
    return pools["main"]


def test_user_pool_add_ons_is_audit_mode():
    """Advanced Security must be enabled in AUDIT mode (detection, no enforcement cost)."""
    pool = _user_pool(_load(COGNITO_MAIN))
    add_ons = pool.get("user_pool_add_ons", [])
    assert add_ons, "aws_cognito_user_pool.main must have a user_pool_add_ons block (#431)"
    (block,) = add_ons
    assert block["advanced_security_mode"] == "AUDIT", (
        f"advanced_security_mode must be AUDIT, got {block['advanced_security_mode']!r}"
    )


def test_threat_protection_requires_plus_tier():
    """AWS rejects user_pool_add_ons on an ESSENTIALS pool (TierChangeNotAllowedException).

    Advanced Security (AUDIT or ENFORCED) requires the PLUS feature tier; the
    pool must not be pinned to ESSENTIALS/LITE while the add-ons block is set.
    """
    pool = _user_pool(_load(COGNITO_MAIN))
    if not pool.get("user_pool_add_ons"):
        pytest.skip("no user_pool_add_ons block to validate against")
    assert pool.get("user_pool_tier") == "PLUS", (
        f"user_pool_add_ons requires the PLUS tier, got {pool.get('user_pool_tier')!r} "
        "(AWS: TierChangeNotAllowedException on UpdateUserPool)"
    )


def test_enforced_mode_is_not_shipped():
    """ENFORCED mode is billed per active user; shipping it is a captain decision, not default."""
    pool = _user_pool(_load(COGNITO_MAIN))
    for block in pool.get("user_pool_add_ons", []):
        assert block["advanced_security_mode"] != "ENFORCED", (
            "ENFORCED Advanced Security must not be enabled by default (#431 cost gate)"
        )
