"""Byte-identical Cognito admin group name across every implementation (#504).

The admin group is created out-of-band in the AWS console: there is no
`aws_cognito_user_group` in the OpenTofu configuration anywhere
(`grep -rn 'aws_cognito_user_group' tofu/` returns nothing), so its exact name
is an undeclared, unversioned contract that exists only in operator memory.

Five sites decide admin status from the `cognito:groups` JWT claim. They must
therefore agree byte-for-byte on the accepted spelling. `get_catalog_for_delete_fn.js`
once also accepted a lowercase `admin`, which let a member of a lowercase group
delete any catalog (including every `ADMIN_MANAGED` global catalog) while
`admin-operations` denied the same user - a broken access control invisible in
IaC and in the UI.

This test pins the literal at each site, so the next rename breaks CI rather
than production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ADMIN_GROUP = "ADMIN"

# Each site: path relative to the repo root, a regex with exactly one capture
# group around the group-name literal, and a human label for failures.
SITES = [
    (
        "tofu/application/appsync/js-resolvers/get_catalog_for_delete_fn.js",
        r"const isAdmin = groups\.includes\('([^']+)'\)",
        "deleteCatalog resolver (JS)",
    ),
    (
        "src/utils/auth.py",
        r'return "([^"]+)" in groups',
        "is_admin() (Python)",
    ),
    (
        "src/handlers/admin_operations.py",
        r'"isAdmin": "([^"]+)" in groups',
        "admin list-users (Python)",
    ),
    (
        "frontend/src/contexts/AuthContext.tsx",
        r"return groups\.includes\('([^']+)'\)",
        "AuthContext (frontend)",
    ),
    (
        "frontend/src/lib/amrTripwire.ts",
        r"return list\.includes\('([^']+)'\)",
        "amrTripwire (frontend)",
    ),
]


def _admin_literal(relpath: str, pattern: str) -> str:
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    matches = re.findall(pattern, source)
    assert matches, f"no admin group check matching {pattern!r} in {relpath}"
    assert len(matches) == 1, f"expected one admin group check in {relpath}, found {matches}"
    return matches[0]


@pytest.mark.parametrize(("relpath", "pattern", "label"), SITES, ids=[site[2] for site in SITES])
def test_admin_group_name_is_uppercase_admin(
    relpath: str, pattern: str, label: str
) -> None:
    """Every admin check accepts exactly the uppercase ADMIN group."""
    literal = _admin_literal(relpath, pattern)
    assert literal == ADMIN_GROUP, (
        f"{label} ({relpath}) checks the Cognito group {literal!r}, "
        f"but the admin group name is {ADMIN_GROUP!r}. The group is created "
        f"out-of-band, so the five call sites must agree byte-for-byte (#504)."
    )


@pytest.mark.parametrize(("relpath", "pattern", "label"), SITES, ids=[site[2] for site in SITES])
def test_no_site_accepts_a_lowercase_admin_spelling(
    relpath: str, pattern: str, label: str
) -> None:
    """No site adds an extra lowercase (or otherwise differing) group spelling.

    This is the specific regression: an OR-ed `|| groups.includes('admin')`
    in the resolver would still satisfy the check above only if the primary
    literal changed, so assert the single-accepting form explicitly.
    """
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    lowercase = re.findall(r"['\"]admin['\"]", source)
    assert not lowercase, (
        f"{label} ({relpath}) still references a lowercase 'admin' literal "
        f"at {lowercase}; only the uppercase {ADMIN_GROUP!r} group grants admin."
    )
