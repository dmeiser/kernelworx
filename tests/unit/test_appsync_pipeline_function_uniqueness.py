"""Pipeline function-ID uniqueness contract for AppSync resolvers.

AWS does not document duplicate function IDs in a pipeline config as supported
(the console even disables re-adding a function already in a pipeline), so a
pipeline step that must run the same code twice needs a second
`aws_appsync_function` resource instead of repeating the ID (#438's
verify_profile_write_access_fallback). These tests parse the OpenTofu
configuration (via python-hcl2) and assert that no pipeline resolver repeats a
function ID, and that the six write-mutation pipelines run the two-phase
owner check as primary-then-fallback.
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

WRITE_MUTATION_FIELDS = {
    "createCampaign",
    "updateCampaign",
    "deleteCampaign",
    "createOrder",
    "updateOrder",
    "deleteOrder",
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


def _pipeline_functions(attrs):
    configs = attrs.get("pipeline_config") or []
    assert len(configs) == 1, "pipeline resolver must declare exactly one pipeline_config"
    return [_norm(fn) for fn in configs[0].get("functions", [])]


def test_no_pipeline_repeats_a_function_id():
    offenders = []
    for name, attrs in _all_resolvers():
        if _norm(attrs.get("kind", "")) != "PIPELINE":
            continue
        functions = _pipeline_functions(attrs)
        if len(functions) != len(set(functions)):
            offenders.append(name)
    assert offenders == [], (
        "duplicate function IDs in a pipeline are not supported by AWS; "
        f"give the repeated step its own aws_appsync_function: {offenders}"
    )


def test_write_mutations_run_two_phase_owner_check_primary_then_fallback():
    resolvers = {_norm(attrs["field"]): (name, attrs) for name, attrs in _all_resolvers()}
    for field in sorted(WRITE_MUTATION_FIELDS):
        assert field in resolvers, f"{field} resolver missing"
        name, attrs = resolvers[field]
        assert _norm(attrs.get("kind", "")) == "PIPELINE", f"{name} must be a pipeline"
        functions = _pipeline_functions(attrs)
        primary = "aws_appsync_function.verify_profile_write_access.function_id"
        fallback = "aws_appsync_function.verify_profile_write_access_fallback.function_id"
        assert functions.count(primary) == 1, (
            f"{name}: expected verify_profile_write_access exactly once, got {functions}"
        )
        assert functions.count(fallback) == 1, (
            f"{name}: expected verify_profile_write_access_fallback exactly once, got {functions}"
        )
        assert functions.index(primary) < functions.index(fallback), (
            f"{name}: owner check (primary) must run before the GSI fallback step"
        )
