"""Wiring contract for the #329 structured-error passthrough on admin resolvers.

The `lambda_handler` decorator (src/utils/handlers.py) no longer raises;
decorated handlers return a structured `__isError` payload instead. AppSync
only surfaces that payload as a GraphQL error if the resolver's JS code
detects it (lambda_passthrough_resolver.js). These tests parse the OpenTofu
configuration into a semantic model (via python-hcl2) and assert the meaning
of the wiring contract:

- Every UNIT resolver on the admin_operations Lambda datasource carries the
  passthrough JS code and an APPSYNC_JS runtime, and none are converted to
  PIPELINE resolvers.
- No resolver on any other datasource carries that code: those handlers are
  not decorator-wrapped and still raise, so they must keep AppSync's default
  VTL behavior.
"""

from __future__ import annotations

from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
APPSYNC_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "appsync"
RESOLVER_FILES = [
    APPSYNC_MODULE / "resolvers_mutations.tf",
    APPSYNC_MODULE / "resolvers_queries.tf",
]
PASSTHROUGH_RESOLVER = "lambda_passthrough_resolver.js"

EXPECTED_ADMIN_FIELDS = {
    "adminResetUserPassword",
    "adminDeleteUser",
    "adminDeleteUserOrders",
    "adminDeleteUserCampaigns",
    "adminDeleteUserShares",
    "adminDeleteUserProfiles",
    "adminDeleteUserCatalogs",
    "createManagedCatalog",
    "adminDeleteShare",
    "adminUpdateCampaignSharedCode",
    "adminListUsers",
    "adminSearchUser",
    "adminGetUserProfiles",
    "adminGetUserCatalogs",
    "adminGetUserCampaigns",
    "adminGetUserSharedCampaigns",
    "adminGetProfileShares",
}


def _norm(value):
    """Decode a python-hcl2 scalar: strip its quote wrapper and ${...} interpolation."""
    if isinstance(value, str):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("${") and value.endswith("}"):
            value = value[2:-1]
    return value


def _all_resolvers():
    """Yield (name, attrs) for every aws_appsync_resolver in the module."""
    resolvers = []
    for path in RESOLVER_FILES:
        with path.open() as handle:
            parsed = hcl2.load(handle)
        for block in parsed["resource"]:
            for type_name, named in block.items():
                if _norm(type_name) != "aws_appsync_resolver":
                    continue
                for resolver_name, attrs in named.items():
                    resolvers.append((_norm(resolver_name), attrs))
    return resolvers


def _admin_resolvers():
    return [
        (name, attrs)
        for name, attrs in _all_resolvers()
        if _norm(attrs.get("data_source", "")) == "aws_appsync_datasource.admin_operations.name"
    ]


def test_admin_resolver_set_matches_expected_fields():
    admin_fields = {_norm(attrs["field"]) for _, attrs in _admin_resolvers()}
    assert admin_fields == EXPECTED_ADMIN_FIELDS


def test_every_admin_resolver_runs_passthrough_code_as_unit_resolver():
    admin = _admin_resolvers()
    assert len(admin) == len(EXPECTED_ADMIN_FIELDS)
    for name, attrs in admin:
        code = str(attrs.get("code", ""))
        assert PASSTHROUGH_RESOLVER in code, f"{name} missing passthrough code"
        runtimes = attrs.get("runtime") or []
        assert len(runtimes) == 1, f"{name} must declare exactly one runtime"
        assert _norm(runtimes[0].get("name", "")) == "APPSYNC_JS", f"{name} runtime"
        assert _norm(runtimes[0].get("runtime_version", "")) == "1.0.0", f"{name} runtime version"
        assert "kind" not in attrs, f"{name} must stay a UNIT resolver"


def test_passthrough_code_not_attached_to_other_datasources():
    offenders = []
    for name, attrs in _all_resolvers():
        if _norm(attrs.get("data_source", "")) == "aws_appsync_datasource.admin_operations.name":
            continue
        code = str(attrs.get("code", ""))
        if PASSTHROUGH_RESOLVER in code:
            offenders.append(name)
    assert offenders == [], (
        "non-admin resolvers must keep default VTL behavior; "
        f"passthrough code found on: {offenders}"
    )
