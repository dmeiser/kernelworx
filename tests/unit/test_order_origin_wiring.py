"""Deployed wiring for the Order joined-scope capture (§1.4.3, data model §5.6).

An Order's ``unitId``/``unitCampaignId`` pair is written once, at creation, and is
never derived again. That is only sound if the read at creation answers the
question "joined to which Unit Campaign *right now*" -- and the Campaign row
cannot: its own link is a latest-link that removal deliberately keeps, so copying
it attributes a post-removal sale to a Unit the Scout had already left, and moves
unfulfilled public Orders into that Unit's Council numbers.

The unit tests in ``js-resolvers`` prove the resolvers' decision. This file pins
the deployed path that decision depends on, because every part of it is a shape a
plausible-looking pipeline gets wrong:

- The campaign must be re-read strongly before anything trusts it. The campaigns
  base table is keyed ``(profileId, campaignId)`` and the caller knows only the
  campaign id, so the ``campaignId-index`` locator is unavoidable -- but it is
  eventually consistent, and a resolver that trusts its projection lets a
  just-changed campaign decide what a just-created Order says.
- The join guard read sits on the unit_campaigns table, addressed by the campaign
  alone (``SCOUT_CAMPAIGN#<campaignId>`` / ``MEMBERSHIP_GUARD``), and must run
  before the write: after the write there is nothing left to ask.
- The minters must not read the Campaign's retained pair at all. A resolver that
  reads both sources and prefers the campaign row passes every mocked test and
  still mis-attributes the real sale.

Parsed with python-hcl2 through the harness in ``test_edge_security.py``.
"""

from __future__ import annotations

from tests.unit.test_edge_security import TF_APP, load_hcl
from tests.unit.test_public_settings_pipeline_wiring import _pipeline

APPSYNC_DIR = TF_APP / "modules" / "appsync"
JS_DIR = TF_APP / "appsync" / "js-resolvers"

LOCATOR = "aws_appsync_function.get_campaign_for_order"
STRONG_CAMPAIGN = "aws_appsync_function.get_campaign_strong_for_order"
GUARD = "aws_appsync_function.get_membership_guard_for_order"
ACTIVE_UNIT_CAMPAIGN = "aws_appsync_function.get_active_unit_campaign_for_order"
ORDER_WRITE = "aws_appsync_function.create_order"
PUBLIC_ORDER_WRITE = "aws_appsync_function.create_public_order"

GUARD_STEPS = (STRONG_CAMPAIGN, GUARD, ACTIVE_UNIT_CAMPAIGN)


def _function_attrs(file: str) -> dict[str, dict]:
    """Every ``aws_appsync_function`` in a module file, by resource name."""
    doc = load_hcl(APPSYNC_DIR / file)
    return {
        name: attrs
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_function"
        for name, attrs in instances.items()
    }


def _before(pipeline: list[str], first: str, second: str) -> bool:
    return pipeline.index(first) < pipeline.index(second)


def test_create_order_reads_join_scope_from_the_guard_before_it_writes() -> None:
    """The three origin reads run between the campaign locator and the PutItem."""
    pipeline = _pipeline("resolvers_mutations.tf", "create_order")

    for step in GUARD_STEPS:
        assert step in pipeline, f"{step} is not in the createOrder pipeline"
        assert _before(pipeline, step, ORDER_WRITE), f"{step} must run before the order write"

    assert _before(pipeline, LOCATOR, STRONG_CAMPAIGN), (
        "the campaign's base-table key is only learnable from the campaignId-index locator, so the "
        "strong re-read has to follow it -- and everything downstream then trusts the strong read"
    )
    assert _before(pipeline, GUARD, ACTIVE_UNIT_CAMPAIGN), (
        "the Unit behind the pointer cannot be named before the pointer is known"
    )


def test_public_create_order_reads_join_scope_from_the_guard_before_it_writes() -> None:
    """An unfulfilled public Order counts toward the Unit it was sold in, so its
    scope must come from the same current read, before the transaction write."""
    pipeline = _pipeline("resolvers_mutations.tf", "public_create_order")

    for step in (GUARD, ACTIVE_UNIT_CAMPAIGN):
        assert step in pipeline, f"{step} is not in the publicCreateOrder pipeline"
        assert _before(pipeline, step, PUBLIC_ORDER_WRITE), f"{step} must run before the order write"


def test_guard_reads_use_the_unit_campaigns_table_and_its_datasource() -> None:
    """The guard lives in the unit_campaigns table, not the campaigns table the
    pipeline already reaches: reading the wrong table answers a stale question."""
    functions = _function_attrs("functions_orders.tf")
    for step in (GUARD, ACTIVE_UNIT_CAMPAIGN):
        attrs = functions[step.split(".")[-1]]
        data_source = attrs["data_source"]
        assert "aws_appsync_datasource.unit_campaigns" in str(data_source), f"{step} reads the wrong table"

    datasources = load_hcl(APPSYNC_DIR / "datasources_dynamodb.tf")
    names = {
        name
        for resource in datasources.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_datasource"
        for name in instances
    }
    assert "unit_campaigns" in names, "no AppSync datasource reaches the unit_campaigns table"


def test_minters_take_the_origin_from_the_guard_and_not_the_campaign_link() -> None:
    """Both minters call ``orderOrigin`` with the guard and the Unit Campaign row.

    ``orderOrigin(campaign)`` would keep every existing mocked test green while
    still attributing a post-removal Order to the Unit the Scout left, so the
    pinning here is on the argument, not on the outcome.
    """
    create = (JS_DIR / "create_order_fn.js").read_text()
    public = (JS_DIR / "create_public_order_fn.js").read_text()
    origin_lib = (JS_DIR / "lib" / "order_origin.js").read_text()

    assert "orderOrigin(ctx.stash.membershipGuard, ctx.stash.activeUnitCampaign)" in create
    assert "orderOrigin(stash.membershipGuard, stash.activeUnitCampaign)" in public
    assert "orderOrigin(campaign)" not in create and "orderOrigin(campaign)" not in public

    # The origin module has no campaign input at all: there is nothing in it that
    # could fall back to the retained link.
    assert "campaign.unitCampaignId" not in origin_lib and "campaign.unitId" not in origin_lib


def test_guard_resolvers_are_wired_to_their_own_source_files() -> None:
    """Each new step's Terraform ``code`` loads the bundle built from its own
    source file. A pipeline step whose ``code`` points elsewhere is a step whose
    reviewed logic is not the logic that ships."""
    tf = (APPSYNC_DIR / "functions_orders.tf").read_text()
    for step in GUARD_STEPS:
        name = step.split(".")[-1]
        block = tf.split(f'resource "aws_appsync_function" "{name}"', 1)[1].split("\n}", 1)[0]
        assert f'code = file("${{local.js_resolvers_dir}}/{name}_fn.js")' in block, f"{step} loads the wrong bundle"
        assert (JS_DIR / f"{name}_fn.js").is_file(), f"{step} has no source file to bundle"
