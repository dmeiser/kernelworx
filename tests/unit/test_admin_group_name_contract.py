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
    """Return the group-name literal captured by the pinned admin check."""
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    matches = re.findall(pattern, source)
    assert matches, f"no admin group check matching {pattern!r} in {relpath}"
    assert len(matches) == 1, f"expected one admin group check in {relpath}, found {matches}"
    return matches[0]


def _admin_expression(relpath: str, pattern: str) -> str:
    """Return the full matched admin-check expression (not just its literal)."""
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    found = re.findall(pattern, source)
    assert found, f"no admin group check matching {pattern!r} in {relpath}"
    expression = re.search(pattern, source).group(0)
    return expression


@pytest.mark.parametrize(("relpath", "pattern", "label"), SITES, ids=[site[2] for site in SITES])
def test_admin_group_name_is_uppercase_admin(relpath: str, pattern: str, label: str) -> None:
    """Every admin check accepts exactly the uppercase ADMIN group."""
    literal = _admin_literal(relpath, pattern)
    assert literal == ADMIN_GROUP, (
        f"{label} ({relpath}) checks the Cognito group {literal!r}, "
        f"but the admin group name is {ADMIN_GROUP!r}. The group is created "
        f"out-of-band, so the five call sites must agree byte-for-byte (#504)."
    )


@pytest.mark.parametrize(("relpath", "pattern", "label"), SITES, ids=[site[2] for site in SITES])
def test_no_site_accepts_a_lowercase_admin_spelling(relpath: str, pattern: str, label: str) -> None:
    """No pinned admin-check expression adds an extra lowercase spelling.

    Asserts only over the exact admin-check expressions pinned in SITES, not
    a whole-file scan: an innocuous lowercase 'admin' elsewhere in the file
    (a comment, a log message) does not grant admin and must not fail CI. The
    behavioral regression itself is covered by the node test
    "does not treat the lowercase group \"admin\" as admin (#504)" in
    get_catalog_for_delete_fn.test.js.
    """
    expression = _admin_expression(relpath, pattern)
    lowercase_in_expression = re.findall(r"['\"]admin['\"]", expression)
    assert not lowercase_in_expression, (
        f"{label} ({relpath}) admin check {expression!r} still accepts a "
        f"lowercase 'admin' spelling; only the uppercase {ADMIN_GROUP!r} "
        f"group grants admin (#504)."
    )
