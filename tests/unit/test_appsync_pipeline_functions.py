"""Pipeline function-list contract for AppSync PIPELINE resolvers.

AppSync does not document duplicate function IDs in a resolver's
``pipeline_config.functions`` list as supported: the console refuses to add a
function that is already in a pipeline, so the service likely rejects such
configs at UpdateResolver time. #438's two-phase profile-write authorization
originally listed ``verify_profile_write_access`` twice in six write-mutation
pipelines; the second slot now uses a dedicated
``verify_profile_write_access_step2`` aws_appsync_function resource.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2, the pattern established by test_edge_security.py and
test_monolithic_role_retirement.py) and assert the meaning of the contract:
every PIPELINE resolver's functions list references each
aws_appsync_function at most once.
"""

from __future__ import annotations

from tests.unit.test_edge_security import TF_APP, load_hcl

APPSYNC_DIR = TF_APP / "modules" / "appsync"

_RESOLVER_FILES = (
    "resolvers_mutations.tf",
    "resolvers_queries.tf",
)


def _pipeline_resolvers() -> list[tuple[str, str, list[str]]]:
    out = []
    for filename in _RESOLVER_FILES:
        path = APPSYNC_DIR / filename
        if not path.exists():
            continue
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type != "aws_appsync_resolver":
                    continue
                for name, attrs in instances.items():
                    if attrs.get("kind") != "PIPELINE":
                        continue
                    functions = []
                    for cfg in attrs.get("pipeline_config", []):
                        functions.extend(cfg.get("functions", []))
                    out.append((filename, name, functions))
    return out


def test_pipeline_function_ids_are_unique() -> None:
    failures = []
    for filename, name, functions in _pipeline_resolvers():
        seen: set[str] = set()
        for fn in functions:
            ref = fn if isinstance(fn, str) else str(fn)
            if ref in seen:
                failures.append(f"{filename}:{name} repeats {ref}")
            seen.add(ref)
    assert not failures, "duplicate pipeline function references:\n" + "\n".join(failures)


def _resolver_pipelines(resolver_file: str) -> dict[str, list[str]]:
    doc = load_hcl(APPSYNC_DIR / resolver_file)
    return {
        name: [fn for cfg in attrs.get("pipeline_config", []) for fn in cfg.get("functions", [])]
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for name, attrs in instances.items()
    }


def test_two_phase_write_check_uses_distinct_functions() -> None:
    functions: set[str] = set()
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type == "aws_appsync_function":
                    functions.update(instances)
    assert "verify_profile_write_access" in functions
    assert "verify_profile_write_access_step2" in functions
    # #547: the pre-#438 single-step owner verifier is retired; the two
    # profile-share/invite queries now run the shared two-phase pair like the
    # write mutations do.
    assert "verify_profile_write_or_owner" not in functions
    step1 = "${aws_appsync_function.verify_profile_write_access.function_id}"
    step2 = "${aws_appsync_function.verify_profile_write_access_step2.function_id}"
    write_mutations = (
        "create_campaign",
        "update_campaign",
        "delete_campaign",
        "create_order",
        "update_order",
        "delete_order",
    )
    resolvers = _resolver_pipelines("resolvers_mutations.tf")
    for mutation in write_mutations:
        pipeline = resolvers[mutation]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{mutation} must run the ownership read before the share-path lookup"
        )
    # #547: the profile-scoped read queries must decide ownership the same way -
    # the strongly consistent base-table GetItem (step 1) before the GSI locator
    # (step 2). Never the retired single-step GSI verifier.
    query_resolvers = _resolver_pipelines("resolvers_queries.tf")
    for query in ("list_shares_by_profile", "list_invites_by_profile"):
        pipeline = query_resolvers[query]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{query} must decide ownership by the strongly consistent base-table "
            "GetItem (step 1) before the GSI locator (step 2)"
        )
        assert "${aws_appsync_function.verify_profile_write_or_owner.function_id}" not in pipeline


def test_two_phase_fetch_profile_check_uses_distinct_functions() -> None:
    functions: set[str] = set()
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type == "aws_appsync_function":
                    functions.update(instances)
    assert "fetch_profile" in functions
    assert "fetch_profile_step2" in functions
    step1 = "${aws_appsync_function.fetch_profile.function_id}"
    step2 = "${aws_appsync_function.fetch_profile_step2.function_id}"
    two_phase_queries = (
        "payment_methods_for_profile",
        "get_profile",
    )
    doc = load_hcl(APPSYNC_DIR / "resolvers_queries.tf")
    resolvers = {
        name: attrs
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for name, attrs in instances.items()
    }
    for query in two_phase_queries:
        attrs = resolvers[query]
        pipeline = [fn for cfg in attrs.get("pipeline_config", []) for fn in cfg.get("functions", [])]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{query} must run the ownership read before the share-path lookup"
        )
