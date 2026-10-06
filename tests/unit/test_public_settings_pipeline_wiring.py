"""Wiring contract for the owner-only public-order settings pipelines (#679).

The settings surface publishes a profile's payment QR codes to anonymous buyers
and opens anonymous writes, so its authorization is a security invariant, not an
implementation detail: both pipelines must run the two-phase write-access pair
(#438) and then the owner gate, and the gate must come BEFORE any function that
reads or writes the settings blob. A refactor that drops or reorders the gate
turns a WRITE-share collaborator into someone who can read the share token and
enable the feature, so this is pinned statically.

Parsing follows the python-hcl2 pattern established by test_edge_security.py and
reuses test_appsync_pipeline_functions.py's resolver-list extraction.
"""

from __future__ import annotations

from tests.unit.test_edge_security import TF_APP

APPSYNC_DIR = TF_APP / "modules" / "appsync"

PAIR = [
    "aws_appsync_function.verify_profile_write_access.function_id",
    "aws_appsync_function.verify_profile_write_access_step2.function_id",
]
GATE = "aws_appsync_function.verify_public_settings_owner.function_id"

READ_PIPELINE = ("resolvers_queries.tf", "get_profile_public_order_settings")
WRITE_PIPELINE = ("resolvers_mutations.tf", "update_profile_public_order_settings")


def _pipeline_functions(filename: str, resolver: str) -> list[str]:
    from tests.unit.test_appsync_pipeline_functions import _resolver_pipelines

    # python-hcl2 keeps the interpolation form, e.g.
    # "${aws_appsync_function.verify_profile_write_access.function_id}".
    return [str(fn) for fn in _resolver_pipelines(filename)[resolver]]


def _index_of(functions: list[str], ref: str) -> int:
    for position, entry in enumerate(functions):
        if ref in entry:
            return position
    raise AssertionError(f"{ref} is not in the pipeline: {functions}")


def _function_attrs(name: str) -> dict:
    from tests.unit.test_edge_security import first_resource, load_hcl

    return first_resource(load_hcl(APPSYNC_DIR / "functions_profiles.tf"), "aws_appsync_function", name)


def test_both_settings_pipelines_exist() -> None:
    from tests.unit.test_appsync_pipeline_functions import _pipeline_resolvers

    declared = {(filename, name) for filename, name, _ in _pipeline_resolvers()}
    assert READ_PIPELINE in declared, "getProfilePublicOrderSettings has no PIPELINE resolver"
    assert WRITE_PIPELINE in declared, "updateProfilePublicOrderSettings has no PIPELINE resolver"


def test_settings_pipelines_run_the_pair_then_the_owner_gate() -> None:
    for pipeline in (READ_PIPELINE, WRITE_PIPELINE):
        functions = _pipeline_functions(*pipeline)
        assert PAIR[0] in functions[0], f"{pipeline[1]} must start with the pair's step 1"
        assert PAIR[1] in functions[1], f"{pipeline[1]} must run the pair's step 2 second"
        assert any(GATE in fn for fn in functions), f"{pipeline[1]} is missing the owner-only gate"


def test_gate_precedes_every_settings_read_and_write() -> None:
    gated_after = [
        "aws_appsync_function.lookup_public_settings_campaign.function_id",
        "aws_appsync_function.validate_public_settings_write.function_id",
        "aws_appsync_function.validate_public_settings_catalog.function_id",
        "aws_appsync_function.write_public_order_settings.function_id",
    ]
    for pipeline in (READ_PIPELINE, WRITE_PIPELINE):
        functions = _pipeline_functions(*pipeline)
        gate_at = _index_of(functions, GATE)
        for step in gated_after:
            if any(step in fn for fn in functions):
                assert _index_of(functions, step) > gate_at, f"{pipeline[1]} runs {step} before the owner gate"


def test_write_pipeline_order_is_campaign_then_catalog_then_write() -> None:
    functions = _pipeline_functions(*WRITE_PIPELINE)
    campaign = _index_of(functions, "aws_appsync_function.validate_public_settings_write.function_id")
    catalog = _index_of(functions, "aws_appsync_function.validate_public_settings_catalog.function_id")
    write = _index_of(functions, "aws_appsync_function.write_public_order_settings.function_id")
    assert campaign < catalog < write, (
        "the anchor campaign must be confirmed before its catalog, and both before the write"
    )


def test_gate_makes_no_dynamodb_call_of_its_own() -> None:
    # The pair already decided ownership; a gate that issued its own read would
    # be a second, eventually-consistent authority on who the owner is.
    gate = _function_attrs("verify_public_settings_owner")
    assert gate["data_source"] == "${aws_appsync_datasource.none.name}"
    assert "verify_public_settings_owner_fn.js" in gate["code"]
