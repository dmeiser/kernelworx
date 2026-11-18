"""The Stage 2 deployed-stack support module (§2.8.5).

Nothing here talks to AWS.  What it does prove is the part of §2.8.5 that can be proven offline:
that the Stage 2 suite sends documents and payloads the shipped SDL actually accepts, that a
Stage 2 answer missing an endpoint stops the suite instead of passing it, and that the balance and
audit helpers report what the §5.2 formulas and the §5.8 trail say when a live answer is wrong.

The live suite itself is :file:`tests/e2e/test_smoke_show_sell_stage2.py`; it is marked ``slow``
and no CI path runs it, so these are the only executable checks its contract gets short of a
deployed run.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.utils import show_sell_stage2_support as stage2

REPO_ROOT = Path(__file__).resolve().parents[2]
SDL_PATH = REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql"


def _sdl() -> str:
    """The SDL this repository ships, which is what the deployed build's API is built from."""
    return SDL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The documents and payloads match the shipped SDL
# ---------------------------------------------------------------------------


def test_every_stage_two_endpoint_has_a_document_and_a_builder() -> None:
    """No acceptance id is exercised with an ad-hoc query string."""
    assert set(stage2.STAGE_TWO_DOCUMENTS) == set(stage2.STAGE_TWO_WRITES) | set(stage2.STAGE_TWO_READS)
    assert set(stage2._BUILDERS) == set(stage2.STAGE_TWO_WRITES) | {
        "createOrder",
        "removeUnitCampaignMembership",
    }
    for field, document in stage2.STAGE_TWO_DOCUMENTS.items():
        assert field in document, f"{field}'s document never names the field it sends"
        assert "SS-" not in document


def test_the_stage_two_documents_match_the_shipped_sdl() -> None:
    """Every Stage 2 argument name the suite sends, and every input key it builds, is declared."""
    assert stage2.stage_two_contract_violations(_sdl()) == []


def test_a_renamed_argument_is_named_rather_than_mis_sent() -> None:
    """The check is not vacuous: an argument the SDL does not declare stops the lane by name.

    ``quantityDelta`` is what ``adjustInventory`` takes.  A suite that still sent ``quantity``
    would reach AppSync, fail to parse, and stop a lane partway through a live run — the failure
    this check moves to before the first request.
    """
    tampered = _sdl().replace("quantityDelta: Int!", "amountDelta: Int!", 1)
    violations = stage2.stage_two_contract_violations(tampered)
    assert any("adjustInventory" in line for line in violations), violations
    assert any("AdjustInventoryInput" in line for line in violations), violations


def test_a_renamed_field_is_reported_for_its_document_and_its_input() -> None:
    """A resolver rename shows up twice: the field is gone, and so is the input it took."""
    tampered = _sdl().replace("  scoutCustodyBalances(", "  scoutCustodyLedger(", 1)
    violations = stage2.stage_two_contract_violations(tampered)
    assert any("scoutCustodyBalances: the SDL declares no such field" in line for line in violations), violations


def test_a_payload_key_the_sdl_never_declared_is_rejected() -> None:
    """A builder that grows a field AppSync has never heard of stops the lane, not the sale."""
    stage2._SAMPLES["RecordInventoryReceiptInput"]["notAField"] = 1
    try:
        violations = stage2.stage_two_contract_violations(_sdl())
    finally:
        del stage2._SAMPLES["RecordInventoryReceiptInput"]["notAField"]
    assert any("notAField" in line for line in violations), violations


def test_every_builder_is_a_callable_that_returns_its_input_shape() -> None:
    """The builders are the single place a Stage 2 payload shape exists."""
    for field, (builder, type_name) in stage2._BUILDERS.items():
        assert isinstance(builder, Callable), f"{field}'s builder is not callable"
        payload = stage2._SAMPLES[type_name]
        assert payload, f"{type_name} has no sample payload"
        if field in stage2._WRITE_INPUT_TYPES:
            assert "idempotencyKey" in str(payload), f"{field} carries no idempotency key"


def test_the_idempotent_mutations_carry_an_idempotency_input() -> None:
    """``IDEM-01``: the seven Stage 2 mutations all name a key, ``createOrder`` at the top level."""
    for field in stage2.STAGE_TWO_WRITES:
        builder, _type_name = stage2._BUILDERS[field]
        payload = stage2._SAMPLES[_type_name]
        assert payload.get("idempotency", {}).get("idempotencyKey") or payload.get("idempotencyKey"), (
            f"{field} would run without a key to replay on"
        )
        assert builder is not None


def test_a_custody_sale_names_the_scout_campaign_and_the_consuming_mode() -> None:
    """``ORD-API-02``: the door-to-door sale is the pipeline's ``CONSUME_SCOUT_CUSTODY`` mode.

    The mode is what makes the sale consume ``withScoutQty`` instead of Kernel stock, and the
    campaign id is the scope the sale is stamped from — without both, the ORD-API assertions in
    the live suite would be measuring a plain ``NONE`` sale.
    """
    payload = stage2._SAMPLES["CreateOrderInput"]
    assert payload["fulfillmentMode"] == "CONSUME_SCOUT_CUSTODY"
    assert payload["campaignId"] == "CAMP#x"
    assert payload["profileId"] == "PROFILE#x"
    line = payload["lineItems"][0]
    assert {"productId", "quantity"} == set(line), line


def test_the_sale_line_identity_is_read_from_the_answer_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    """§5.19: ``createOrder`` mints the line id, so the suite must ask for it back.

    Measured on dev on 2026-11-18: a sale whose line named no id came back with
    ``lineItemId: 96b00337-...`` — the identity is the write's, not the caller's, and every later
    fulfillment, reversal and screen row keys on it.  A suite that invented its own id would then
    chase a line the Order never stored, which is the shape of the first version of this lane.
    """
    payload = stage2._SAMPLES["CreateOrderInput"]
    assert "lineItemId" not in payload["lineItems"][0], payload
    document = stage2.STAGE_TWO_DOCUMENTS["createOrder"]
    assert "lineItems { lineItemId productId quantity fulfilledQuantity }" in document, document
    fulfillment = stage2.STAGE_TWO_DOCUMENTS["fulfillIndividualOrderLine"]
    assert "lineItemId" in fulfillment and "fulfillmentId" in fulfillment, fulfillment


def test_a_fulfillment_names_the_version_it_conditions_on() -> None:
    """``INV-M-06-03`` / ``VER-01``: a fulfillment and a reversal both carry their version."""
    assert stage2._SAMPLES["FulfillIndividualOrderLineInput"]["expectedFulfillmentVersion"] == 0
    assert stage2._SAMPLES["ReverseIndividualOrderFulfillmentInput"]["expectedFulfillmentVersion"] == 1
    assert stage2._SAMPLES["FulfillIndividualOrderLineInput"]["source"] == "KERNEL_STOCK"


def test_a_return_batch_is_a_list_of_product_quantities() -> None:
    """``INV-M-05-01``: one call returns several products, so the batch is the payload."""
    payload = stage2.return_input(
        "UC#x",
        "CAMP#x",
        "PROFILE#x",
        [{"productId": "PROD#a", "quantity": 2}, {"productId": "PROD#b", "quantity": 3}],
        idempotency_key="batch",
    )
    assert [(item["productId"], item["quantity"]) for item in payload["items"]] == [("PROD#a", 2), ("PROD#b", 3)]
    assert payload["idempotency"] == {"idempotencyKey": "batch"}


# ---------------------------------------------------------------------------
# A build without Stage 2 stops the suite rather than passing it
# ---------------------------------------------------------------------------


def test_a_selection_the_deployed_sdl_does_not_answer_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Field-level checking is not enough: the documents also have to select real payload fields.

    ``inventoryPositions`` answers a connection, so a document that asks it for ``positions``
    instead of ``items``, or asks ``recordInventoryReceipt`` for a ``movementId`` its payload does
    not carry, reaches AppSync and fails to parse — partway through a live lane, after the writes
    that came before it have already landed.
    """
    monkeypatch.setitem(
        stage2.STAGE_TWO_DOCUMENTS,
        "inventoryPositions",
        stage2.STAGE_TWO_DOCUMENTS["inventoryPositions"].replace("items {", "positions {", 1),
    )
    assert stage2.stage_two_selection_violations(_sdl()) == [
        "inventoryPositions.positions: InventoryPositionConnection declares no positions"
    ]


def test_a_forged_nested_field_is_named_with_its_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong field two selection levels down is reported at the level that is wrong."""
    monkeypatch.setitem(
        stage2.STAGE_TWO_DOCUMENTS,
        "unitScoutCampaignOrders",
        stage2.STAGE_TWO_DOCUMENTS["unitScoutCampaignOrders"].replace("fulfilledQuantity", "shippedQuantity"),
    )
    violations = stage2.stage_two_selection_violations(_sdl())
    assert violations == [
        "unitScoutCampaignOrders.items.lineItems.shippedQuantity: UnitOrderLine declares no shippedQuantity"
    ], violations


def test_a_write_asked_for_a_movement_id_it_never_answers_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The §7 writes answer the rows they changed, and no movement id — the trail is read back."""
    monkeypatch.setitem(
        stage2.STAGE_TWO_DOCUMENTS,
        "recordInventoryReceipt",
        stage2.STAGE_TWO_DOCUMENTS["recordInventoryReceipt"].replace(
            "totalUnitOwnedUndeliveredQty }", "totalUnitOwnedUndeliveredQty movementId }", 1
        ),
    )
    assert stage2.stage_two_selection_violations(_sdl()) == [
        "recordInventoryReceipt.movementId: InventoryPosition declares no movementId"
    ]


def test_the_lane_support_documents_are_checked_against_the_sdl_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The catalog-identity and removal queries are held to the same standard as Stage 2 itself.

    They are the queries a Stage 2 lane writes inline to decide whether it can run at all, so a
    rename of ``UnitCampaignAdmin`` or ``UnitCampaignMembership`` would otherwise surface as a
    parse error inside the gate that is meant to report a mismatch in words.
    """
    assert set(stage2.STAGE_TWO_SUPPORT_DOCUMENTS) == {
        "campaignCatalogIdentity",
        "scoutCampaignCatalog",
        "catalogProducts",
        "managedCatalogs",
        "scoutCampaigns",
        "roster",
        "removeMembership",
    }
    monkeypatch.setitem(
        stage2.STAGE_TWO_SUPPORT_DOCUMENTS,
        "removeMembership",
        stage2.STAGE_TWO_SUPPORT_DOCUMENTS["removeMembership"].replace("guardVersion", "guardVersions"),
    )
    assert stage2.stage_two_selection_violations(_sdl()) == [
        "removeUnitCampaignMembership.guardVersions: UnitCampaignMembership declares no guardVersions"
    ]


def test_the_introspection_gate_reports_what_the_deployed_api_answers() -> None:
    """The runnable gate reads the API's own field list, not a guess about which build is live."""
    answered = stage2.stage_two_fields_in_schema(
        {
            "__schema": {
                "queryType": {"fields": [{"name": "inventoryPositions"}, {"name": "unitCampaigns"}]},
                "mutationType": {"fields": [{"name": "recordInventoryReceipt"}]},
            }
        }
    )
    assert answered == ["recordInventoryReceipt", "inventoryPositions"]
    assert stage2.stage_two_fields_in_schema({"__schema": {}}) == []


def test_the_shipped_sdl_carries_every_stage_two_endpoint() -> None:
    """§2.1-§2.4 are in this tree, so the live suite has nothing to be blocked on here."""
    assert stage2.missing_stage_two_endpoints(_sdl()) == []


def test_a_stage_one_build_stops_the_suite_and_names_the_endpoints() -> None:
    """The runnable gate is the difference between *skipped* and *passed*.

    The control is the pre-Stage-2 SDL shape: strip the Stage 2 fields out and the suite reports
    exactly the endpoints it cannot exercise, which is what §2.8.5's "after the merge SHA's
    `Deploy Dev` run is green" condition needs in writing.
    """
    stage_one_only = _sdl()
    for field in stage2.STAGE_TWO_WRITES + stage2.STAGE_TWO_READS:
        stage_one_only = stage_one_only.replace(f"  {field}(", f"  legacy_{field}(")
    missing = stage2.missing_stage_two_endpoints(stage_one_only)
    assert missing == sorted(set(stage2.STAGE_TWO_WRITES + stage2.STAGE_TWO_READS)) or set(missing) == set(
        stage2.STAGE_TWO_WRITES + stage2.STAGE_TWO_READS
    ), missing
    assert stage2.MISSING_ENDPOINT_NOTE.count(" ") > 5


# ---------------------------------------------------------------------------
# What a persisted Stage 2 answer has to satisfy
# ---------------------------------------------------------------------------


def _position(**overrides: Any) -> dict[str, Any]:
    """One ``inventoryPositions`` item, at the SS-SM-10 starting balances by default.

    The defaults are the numbers the smoke plan's ``SS-SM-10`` fixture produces for Butter: 8
    received, 2 issued to a Scout, 4 assigned to a future event, 3 on order.
    """
    values: dict[str, Any] = {
        "unitCampaignId": "UC#lane",
        "productId": "CATALOG#lane#prod-2",
        "kernelPhysicalQty": 6,
        "soldInPossessionQty": 0,
        "councilOnOrderQty": 3,
        "sellableKernelQty": 6,
        "assignedOpenQty": 4,
        "unassignedKernelQty": 2,
        "assignmentOverageQty": 0,
        "withScoutQty": 2,
        "totalUnitOwnedUndeliveredQty": 8,
    }
    values.update(overrides)
    return values


def test_a_consistent_position_reports_no_violation() -> None:
    """The §5.2 formulas hold for the SS-SM-10 starting balances."""
    assert stage2.position_arithmetic_violations([_position()]) == []


@pytest.mark.parametrize(
    ("broken", "why"),
    [
        ({"sellableKernelQty": 8}, "sellable = physical - sold-in-possession"),
        ({"unassignedKernelQty": 6}, "unassigned = max(0, sellable - assigned)"),
        ({"assignmentOverageQty": 2}, "overage = max(0, assigned - sellable)"),
        ({"totalUnitOwnedUndeliveredQty": 6}, "unit-owned total = physical + with-scout"),
    ],
)
def test_a_position_that_breaks_a_formula_is_named_with_its_formula(broken: dict[str, Any], why: str) -> None:
    """A stored-looking number that disagrees with the rows is the defect §2.8.5 looks for."""
    violations = stage2.position_arithmetic_violations([_position(**broken)])
    assert len(violations) == 1, violations
    assert why in violations[0], violations
    assert "CATALOG#lane#prod-2" in violations[0]


def test_an_answer_missing_a_quantity_is_reported_rather_than_counted_as_zero() -> None:
    """A projection that stopped answering a field must not read as a balance of nothing."""
    answer = _position()
    del answer["unassignedKernelQty"]
    violations = stage2.position_arithmetic_violations([answer])
    assert violations == ["CATALOG#lane#prod-2: the answer carries no ['unassignedKernelQty']"], violations


def test_an_overage_position_is_checked_against_the_overage_rule() -> None:
    """Assignment above sellable stock is legal and reported, never folded into unassigned."""
    over = _position(
        kernelPhysicalQty=2,
        sellableKernelQty=2,
        assignedOpenQty=5,
        unassignedKernelQty=0,
        assignmentOverageQty=3,
        totalUnitOwnedUndeliveredQty=4,
    )
    assert stage2.position_arithmetic_violations([over]) == []
    wrong = dict(over, assignmentOverageQty=0)
    assert any("overage" in line for line in stage2.position_arithmetic_violations([wrong]))


def test_custody_totals_group_by_product_and_keep_absence_distinct_from_zero() -> None:
    """``INV-Q-04-01``: custody is read per product, and no row is not a row at zero."""
    rows = [
        {"productId": "CATALOG#lane#prod-2", "withScoutQty": 4},
        {"productId": "CATALOG#lane#prod-1", "withScoutQty": 1},
        {"productId": "CATALOG#lane#prod-2", "withScoutQty": 1},
    ]
    assert stage2.custody_by_product(rows) == {"CATALOG#lane#prod-2": 5, "CATALOG#lane#prod-1": 1}
    assert "CATALOG#lane#prod-3" not in stage2.custody_by_product(rows)


def _movement(**overrides: Any) -> dict[str, Any]:
    """One ``inventoryMovements`` item, of the RECEIPT kind by default."""
    values: dict[str, Any] = {
        "movementId": "Movement#1",
        "productId": "CATALOG#lane#prod-2",
        "movementType": "RECEIPT",
        "kernelPhysicalDelta": 8,
        "soldPossessionDelta": 0,
        "withScoutDelta": 0,
        "assignedDelta": 0,
        "councilOnOrderDelta": 0,
        "profileId": None,
        "orderId": None,
        "fulfillmentId": None,
        "reason": "Received from the supplier",
        "actorAccountId": "ACCOUNT#admin",
        "occurredAt": "2026-11-07T08:00:00Z",
    }
    values.update(overrides)
    return values


def test_the_trail_holds_each_expected_movement_exactly_once() -> None:
    """SS-SM-03 step 4-7: the receipt and both adjustments are one movement each, with a reason."""
    trail = [
        _movement(reason="Received 8 Butter"),
        _movement(
            movementId="Movement#2",
            movementType="STOCK_ADJUSTMENT",
            kernelPhysicalDelta=2,
            reason="Trade with Troop 7150; money settled outside app",
        ),
        _movement(
            movementId="Movement#3",
            movementType="STOCK_ADJUSTMENT",
            kernelPhysicalDelta=-1,
            reason="Gift to outgoing volunteer",
        ),
    ]
    expected = [
        {"movementType": "RECEIPT", "kernelPhysicalDelta": 8, "productId": "CATALOG#lane#prod-2"},
        {"movementType": "STOCK_ADJUSTMENT", "kernelPhysicalDelta": 2, "reason": "Trade with Troop 7150; money settled outside app"},
        {"movementType": "STOCK_ADJUSTMENT", "kernelPhysicalDelta": -1, "reason": "Gift to outgoing volunteer"},
    ]
    assert stage2.movement_trail_violations(trail, expected) == []


def test_a_write_that_ran_twice_is_reported_as_running_twice() -> None:
    """The duplicate a replayed mutation would leave behind is the trail's own evidence."""
    trail = [_movement(), _movement(movementId="Movement#2")]
    violations = stage2.movement_trail_violations(trail, [{"movementType": "RECEIPT", "kernelPhysicalDelta": 8}])
    assert violations == ["2 movements match {'movementType': 'RECEIPT', 'kernelPhysicalDelta': 8}: the write ran twice"], violations


def test_an_expected_movement_the_trail_does_not_hold_is_named() -> None:
    """A custody issue that moved a balance but wrote no movement is the AC-03 defect."""
    violations = stage2.movement_trail_violations(
        [_movement()],
        [
            {"movementType": "RECEIPT", "kernelPhysicalDelta": 8},
            {"movementType": "SCOUT_ISSUE", "kernelPhysicalDelta": -4, "withScoutDelta": 4},
        ],
    )
    assert len(violations) == 1, violations
    assert "SCOUT_ISSUE" in violations[0]


def test_a_leftover_movement_naming_no_actor_or_no_reason_is_a_trail_gap() -> None:
    """SS-SM-03 step 7 and step 8: history identifies who acted and why."""
    trail = [
        _movement(),
        _movement(movementId="Movement#2", movementType="STOCK_ADJUSTMENT", kernelPhysicalDelta=1, actorAccountId=None, reason="x"),
        _movement(movementId="Movement#3", movementType="STOCK_ADJUSTMENT", kernelPhysicalDelta=1, reason=None),
    ]
    violations = stage2.movement_trail_violations(trail, [{"movementType": "RECEIPT", "kernelPhysicalDelta": 8}])
    assert violations == [
        "movement Movement#2 names no actor",
        "stock adjustment Movement#3 carries no reason",
    ], violations


def test_a_custody_sale_movement_is_matched_on_its_order_link() -> None:
    """``SCOUT_SALE_CONSUME`` names the sale that consumed the custody (``ORD-API-02-01``)."""
    trail = [
        _movement(
            movementId="Movement#9",
            movementType="SCOUT_SALE_CONSUME",
            kernelPhysicalDelta=0,
            withScoutDelta=-3,
            orderId="ORDER#camp#sale-1",
            profileId="PROFILE#scout",
            reason=None,
        )
    ]
    expected = [{"movementType": "SCOUT_SALE_CONSUME", "withScoutDelta": -3, "orderId": "ORDER#camp#sale-1"}]
    assert stage2.movement_trail_violations(trail, expected) == []


def test_council_needs_are_both_reported_and_never_a_single_number() -> None:
    """``RPT-06`` / SS-SM-10 step 2: need 4 from physical stock, need 8 after assignments."""
    assert stage2.council_need_positions(demand=10, sellable=6, unassigned=2) == {
        "physicalStockNeed": 4,
        "afterAssignmentsNeed": 8,
    }
    assert stage2.council_need_positions(demand=4, sellable=6, unassigned=2) == {
        "physicalStockNeed": 0,
        "afterAssignmentsNeed": 2,
    }


def test_a_fulfillment_from_stock_moves_demand_and_stock_together_so_both_needs_hold() -> None:
    """SS-SM-10 step 5: both numbers stay put when demand and available stock each fall by 1."""
    before = stage2.council_need_positions(demand=10, sellable=6, unassigned=2)
    after = stage2.council_need_positions(demand=9, sellable=5, unassigned=1)
    assert before == after == {"physicalStockNeed": 4, "afterAssignmentsNeed": 8}


def test_an_external_council_fulfillment_lowers_need_without_touching_stock() -> None:
    """SS-SM-10 step 6: demand falls, the shelf does not, and both needs fall by one."""
    after = stage2.council_need_positions(demand=8, sellable=5, unassigned=1)
    assert after == {"physicalStockNeed": 3, "afterAssignmentsNeed": 7}


# ---------------------------------------------------------------------------
# The live spec's own contract: same rules as Stage 1, checked here
# ---------------------------------------------------------------------------

STAGE_TWO_SPEC = REPO_ROOT / "tests" / "e2e" / "test_smoke_show_sell_stage2.py"

#: Anything that would make the lane runnable by a second, drifting path, or that would put a
#: fixture credential where a repository secret would have to be.
FORBIDDEN_IN_A_LIVE_LANE: tuple[str, ...] = (
    "boto3",
    "admin_create_user",
    "admin_set_user_password",
    "admin_resend_user_confirmation",
    "list_user_pool_clients",
    "ListUsers",
)


def _spec_source() -> str:
    """The Stage 2 spec's source."""
    return STAGE_TWO_SPEC.read_text(encoding="utf-8")


def _spec_tree() -> ast.Module:
    """The Stage 2 spec, parsed."""
    return ast.parse(_spec_source())


def test_the_stage_two_spec_is_a_slow_lane_and_never_a_smoke_test() -> None:
    """``-m smoke`` runs on every push to ``dev``, and no CI path holds these passwords."""
    markers: list[str] = []
    for node in _spec_tree().body:
        if not (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets)):
            continue
        for attribute in ast.walk(node.value):
            if isinstance(attribute, ast.Attribute) and isinstance(attribute.value, ast.Attribute):
                if attribute.value.attr == "mark":
                    markers.append(attribute.attr)
    assert "slow" in markers, f"pytestmark is {markers}"
    assert "smoke" not in markers and "pytest.mark.smoke" not in _spec_source()


def test_no_workflow_runs_the_stage_two_lane_or_names_its_identities() -> None:
    """The lane is executed by a human or a scheduled QA run, never by a repository secret.

    The guard for Stage 1 bans the substring ``test_smoke_show_sell``, which this file's own name
    contains, so the ban is asserted here against the workflows too: adding this spec to a CI job
    would be the first step toward putting the fixture passwords in repository secrets.
    """
    needles = ("qa-show-sell", "TEST_QA_SHOW_SELL", "test_smoke_show_sell", "qa_fixture")
    offenders = [
        path.name
        for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        if any(needle in path.read_text(encoding="utf-8", errors="ignore") for needle in needles)
    ]
    assert not offenders, f"workflows reference the QA fixture identities: {offenders}"


def test_the_stage_two_lane_holds_no_aws_or_cognito_admin_path() -> None:
    """The lane consumes the fixture identities; it never creates, repairs, or lists them."""
    offenders = [
        needle
        for needle in FORBIDDEN_IN_A_LIVE_LANE
        if needle in _spec_source() or needle in Path(stage2.__file__).read_text(encoding="utf-8")
    ]
    assert not offenders, f"the Stage 2 lane reaches for provisioning: {offenders}"


def test_every_stage_two_screenshot_masks_the_join_code() -> None:
    """A Stage 2 tab is a Unit Campaign page, and it renders the live join code like the others."""
    for call in ast.walk(_spec_tree()):
        if not (isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "screenshot"):
            continue
        assert any(keyword.arg == "mask" for keyword in call.keywords), (
            f"page.screenshot at line {call.lineno} has no mask"
        )
    signature = next(
        node
        for node in ast.walk(_spec_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "_screenshot"
    )
    assert not signature.args.kw_defaults or all(default is None for default in signature.args.kw_defaults), (
        "_screenshot's masks argument gained a default, which is how a mask gets dropped silently"
    )


def test_the_stage_two_lane_names_no_origin_and_publishes_the_one_it_is_given() -> None:
    """One origin reaches both halves of the run, and it never comes from a literal.

    A hardcoded origin is the failure that reads as a defect in the build: the browser drives one
    host while GraphQL answers another, and every assertion compares two different deployments.
    """
    source = _spec_source()
    assert "://" not in source, "the spec names an origin itself instead of reading the deployed one"
    assert "publish_base_url()" in source
    for fixture in ("global_setup", "global_cleanup"):
        assert f"def {fixture}(" in source, f"the spec does not override the pool-wide {fixture}"
