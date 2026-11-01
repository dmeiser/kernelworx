"""Campaign-keyed public-order settings pipeline wiring (#679 rev 7).

The settings pipelines are the owner-side half of the public-orders feature, and
after the campaign-level rework they are the ONLY way to read or write the
`publicOrders` map. These tests pin the wiring that makes them correct, because
every part of it is a sharp edge that a plausible-looking pipeline gets wrong:

- The pipeline must START by locating the campaign. The campaigns base table is
  keyed {profileId, campaignId} and the seller UI only knows the campaign id, so
  without the locator the two-phase pair has no partition key to read.
- The pair (`verify_profile_write_access` + `verify_profile_write_access_step2`)
  must run before anything reads or writes the settings, and the owner gate must
  sit between the pair and the settings step. A pipeline that puts the settings
  read before the gate discloses the share token to a share collaborator; one
  that puts the settings write before the gate lets a collaborator rotate it.
- The gate must make no DynamoDB call of its own: it decides off
  `ctx.stash.isOwner` (#438/#545). Re-deriving ownership from the stashed item's
  `ownerAccountId` is the #545 bug.
- The write pipeline's order is campaign check -> catalog check -> write. The
  catalog check is a separate function because it reads a different table, and
  the write must be last so a failed check never mutates the settings.
- No function may appear twice in one pipeline list (see
  test_appsync_pipeline_functions.py), which is why the locator stashes
  `ctx.stash.campaign` for the pair instead of the pair re-reading the campaign.

Parsed with python-hcl2 via the harness in test_edge_security.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_edge_security import TF_APP, load_hcl

APPSYNC_DIR = TF_APP / "modules" / "appsync"
JS_DIR = TF_APP / "appsync" / "js-resolvers"

QUERY_RESOLVERS = "resolvers_queries.tf"
MUTATION_RESOLVERS = "resolvers_mutations.tf"

LOCATOR = "aws_appsync_function.locate_campaign_public_settings"
PAIR_STEP1 = "aws_appsync_function.verify_profile_write_access"
PAIR_STEP2 = "aws_appsync_function.verify_profile_write_access_step2"
GATE = "aws_appsync_function.verify_public_settings_owner"
SETTINGS_READ = "aws_appsync_function.lookup_campaign_public_settings"
CAMPAIGN_CHECK = "aws_appsync_function.validate_campaign_settings_write"
CATALOG_CHECK = "aws_appsync_function.validate_public_settings_catalog"
SETTINGS_WRITE = "aws_appsync_function.write_campaign_public_order_settings"

SETTINGS_FUNCTIONS = (LOCATOR, SETTINGS_READ, CAMPAIGN_CHECK, SETTINGS_WRITE)


def _resolver_pipelines(resolver_file: str) -> dict[str, list[str]]:
    doc = load_hcl(APPSYNC_DIR / resolver_file)
    return {
        name: [fn for cfg in attrs.get("pipeline_config", []) for fn in cfg.get("functions", [])]
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for name, attrs in instances.items()
    }


def _pipeline(resolver_file: str, resolver_name: str) -> list[str]:
    pipelines = _resolver_pipelines(resolver_file)
    assert resolver_name in pipelines, f"{resolver_name} is not defined in {resolver_file}"
    return [_norm_ref(fn) for fn in pipelines[resolver_name]]


def _norm_ref(ref: object) -> str:
    """python-hcl2 renders a bare interpolation as `${expr}`; unwrap it."""
    text = ref if isinstance(ref, str) else str(ref)
    text = text.replace('"', "").strip()
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1].strip()
    # Every pipeline slot references the function's id attribute; compare on the
    # resource reference itself so the constants stay readable.
    if text.endswith(".function_id"):
        text = text[: -len(".function_id")]
    return text


def _read_query_pipeline() -> list[str]:
    return _pipeline(QUERY_RESOLVERS, "get_campaign_public_order_settings")


def _write_query_pipeline() -> list[str]:
    return _pipeline(MUTATION_RESOLVERS, "update_campaign_public_order_settings")


def _function_resources() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type != "aws_appsync_function":
                    continue
                for name, attrs in instances.items():
                    found[name] = attrs
    return found


# ---------------------------------------------------------------------------
# Both pipelines exist and are wired the campaign-keyed way
# ---------------------------------------------------------------------------


def test_both_settings_pipelines_exist() -> None:
    read = _read_query_pipeline()
    write = _write_query_pipeline()
    assert read, "getCampaignPublicOrderSettings must be a PIPELINE resolver"
    assert write, "updateCampaignPublicOrderSettings must be a PIPELINE resolver"


def test_each_pipeline_starts_by_locating_the_campaign() -> None:
    """The base table is keyed {profileId, campaignId}; the client only knows the
    campaign id, so the locator has to come first or the pair has no partition
    key to read."""
    for name, pipeline in (("read", _read_query_pipeline()), ("write", _write_query_pipeline())):
        assert pipeline[0] == LOCATOR, f"{name} pipeline must open with the campaign locator: {pipeline}"


def test_settings_pipelines_run_the_pair_then_the_owner_gate() -> None:
    for name, pipeline in (("read", _read_query_pipeline()), ("write", _write_query_pipeline())):
        for required in (LOCATOR, PAIR_STEP1, PAIR_STEP2, GATE):
            assert required in pipeline, f"{name} pipeline is missing {required}: {pipeline}"
        assert pipeline.index(PAIR_STEP1) < pipeline.index(PAIR_STEP2), f"{name} pair is out of order"
        assert pipeline.index(PAIR_STEP2) < pipeline.index(GATE), f"{name} gate must follow the pair"


def test_gate_precedes_every_settings_read_and_write() -> None:
    """A settings step before the gate discloses the share token to a WRITE-share
    collaborator (or rotates it) - the exact bug the gate exists to close."""
    for name, pipeline in (("read", _read_query_pipeline()), ("write", _write_query_pipeline())):
        gate_at = pipeline.index(GATE)
        for step in (SETTINGS_READ, SETTINGS_WRITE):
            if step in pipeline:
                assert gate_at < pipeline.index(step), f"{name} pipeline runs {step} before the owner gate"


def test_read_pipeline_ends_with_the_consistent_settings_read() -> None:
    pipeline = _read_query_pipeline()
    assert pipeline[-1] == SETTINGS_READ, (
        "the settings read must be last: it re-reads the campaign strongly "
        "consistently so a just-saved token is returned, not a lagging projection"
    )
    assert SETTINGS_WRITE not in pipeline, "the settings query must not write"


def test_write_pipeline_order_is_campaign_then_catalog_then_write() -> None:
    pipeline = _write_query_pipeline()
    assert pipeline[-1] == SETTINGS_WRITE, "the conditioned write must be the last step"
    assert pipeline.index(CAMPAIGN_CHECK) < pipeline.index(CATALOG_CHECK), (
        "the campaign check precedes the catalog check: the catalog id comes off the campaign item"
    )
    assert pipeline.index(CATALOG_CHECK) < pipeline.index(SETTINGS_WRITE), "a failed check must not mutate settings"
    assert SETTINGS_READ not in pipeline, "the write pipeline reads the campaign through the campaign check"


def test_settings_functions_are_bound_only_in_the_settings_pipelines() -> None:
    """A settings function wired into another pipeline would leak the share token
    or the counter into an unrelated response."""
    all_pipelines: list[tuple[str, str, list[str]]] = []
    for filename in (QUERY_RESOLVERS, MUTATION_RESOLVERS):
        for name, functions in _resolver_pipelines(filename).items():
            all_pipelines.append((filename, name, [_norm_ref(fn) for fn in functions]))

    settings_pipelines = {"get_campaign_public_order_settings", "update_campaign_public_order_settings"}
    for filename, name, pipeline in all_pipelines:
        if name in settings_pipelines:
            continue
        for step in SETTINGS_FUNCTIONS:
            assert step not in pipeline, f"{step} is wired into the unrelated pipeline {filename}:{name}"


def test_every_settings_function_is_declared_and_bound_once() -> None:
    functions = _function_resources()
    for label in (
        "locate_campaign_public_settings",
        "lookup_campaign_public_settings",
        "validate_campaign_settings_write",
        "write_campaign_public_order_settings",
        "verify_public_settings_owner",
        "validate_public_settings_catalog",
    ):
        assert label in functions, f"aws_appsync_function.{label} is not declared"

    bound = [
        ref
        for filename in (QUERY_RESOLVERS, MUTATION_RESOLVERS)
        for pipeline in _resolver_pipelines(filename).values()
        for ref in (_norm_ref(fn) for fn in pipeline)
    ]
    for label in (
        "locate_campaign_public_settings",
        "lookup_campaign_public_settings",
        "validate_campaign_settings_write",
        "write_campaign_public_order_settings",
        "verify_public_settings_owner",
        "validate_public_settings_catalog",
    ):
        # A function may be shared ACROSS pipelines (the locator serves both
        # settings pipelines); what AppSync rejects is a repeat WITHIN one list,
        # which test_pipeline_function_ids_are_unique already pins globally.
        assert bound.count(f"aws_appsync_function.{label}") >= 1, f"{label} is declared but never bound"
    for pipeline in (_read_query_pipeline(), _write_query_pipeline()):
        assert len(pipeline) == len(set(pipeline)), f"a settings pipeline repeats a function: {pipeline}"


def test_no_profile_keyed_settings_resolver_survives() -> None:
    """#679 rev 7 replaces the profile-keyed API outright: no PIPELINE resolver
    may still be attached to a profile-level settings field. Asserted on the
    parsed model (resolver field name), not on file text."""
    attached_fields = {
        (attrs.get("type"), attrs.get("field"))
        for filename in (QUERY_RESOLVERS, MUTATION_RESOLVERS)
        for resource in load_hcl(APPSYNC_DIR / filename).get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for attrs in instances.values()
    }
    for field in ("getProfilePublicOrderSettings", "updateProfilePublicOrderSettings"):
        assert ("Query", field) not in attached_fields, f"a resolver still backs the profile-level {field}"
        assert ("Mutation", field) not in attached_fields, f"a resolver still backs the profile-level {field}"

    # The campaign-keyed pair must be attached to exactly the campaign fields.
    assert ("Query", "getCampaignPublicOrderSettings") in attached_fields
    assert ("Mutation", "updateCampaignPublicOrderSettings") in attached_fields


def test_settings_function_js_files_exist_where_the_module_loads_them() -> None:
    """The module reads resolver code from dist/, which build-resolvers.mjs
    produces from js-resolvers/. A missing source fails every tofu plan with
    `Invalid function argument`, so pin the source path here."""
    functions = _function_resources()
    for label in (
        "locate_campaign_public_settings",
        "lookup_campaign_public_settings",
        "validate_campaign_settings_write",
        "write_campaign_public_order_settings",
        "verify_public_settings_owner",
        "validate_public_settings_catalog",
    ):
        code = str(functions[label]["code"])
        match = re.search(r"js_resolvers_dir\}/([\w./-]+)", code)
        assert match, f"aws_appsync_function.{label} does not load code from local.js_resolvers_dir: {code}"
        source = JS_DIR / match.group(1)
        assert source.exists(), f"aws_appsync_function.{label} loads missing source {source}"
        assert Path(source).name == match.group(1)
