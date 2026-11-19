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
        "shareProfileDirect",
        "revokeShare",
        "updateUnitCampaign",
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
        "scoutCampaign",
        "roster",
        "removeMembership",
        "unitCampaigns",
        "myUnits",
        "shareRead",
        "shares",
        "revokeShare",
        "deleteCampaign",
        "deleteProfile",
        "deleteOrder",
        "profiles",
        "deactivateUnitCampaign",
    }
    monkeypatch.setitem(
        stage2.STAGE_TWO_SUPPORT_DOCUMENTS,
        "removeMembership",
        stage2.STAGE_TWO_SUPPORT_DOCUMENTS["removeMembership"].replace("guardVersion", "guardVersions"),
    )
    assert stage2.stage_two_selection_violations(_sdl()) == [
        "removeUnitCampaignMembership.guardVersions: UnitCampaignMembership declares no guardVersions"
    ]


def test_the_lane_carries_a_document_for_every_record_it_has_to_take_back() -> None:
    """§2.8.7's cleanup order needs a call for each record class the lane can remove.

    A lane that cleans up "at the end" but has no document for, say, the seller profile leaves the
    profile and its campaigns behind and reports success anyway.  These are the documents the
    teardown asserts with, and the read-backs next to them are what make the removal a fact rather
    than a mutation that returned ``true``.
    """
    documents = stage2.STAGE_TWO_SUPPORT_DOCUMENTS
    removals = {
        "deleteCampaign": "deleteCampaign",
        "deleteProfile": "deleteSellerProfile",
        "deleteOrder": "deleteOrder",
    }
    for key, field in removals.items():
        assert field in documents[key], f"{key} does not send {field}"
        assert documents[key].lstrip().startswith("mutation"), f"{key} is not a mutation"
    for read_back in ("scoutCampaign", "profiles", "scoutCampaigns", "shares"):
        assert documents[read_back].lstrip().startswith("query"), f"{read_back} is not a read"
    assert '"revokeShare"' in documents["revokeShare"] or "revokeShare(input: $input)" in documents["revokeShare"]


def test_the_teardown_stops_where_the_product_stops_and_says_so() -> None:
    """The lane's cleanup boundary is the SDL's, not a wish.

    ``deleteCampaign``, ``deleteSellerProfile`` and ``deleteOrder`` exist, so the lane removes the
    Scout Campaign, the seller profile and the Orders it wrote.  No ``deleteUnit`` or
    ``deleteUnitCampaign`` exists anywhere in the shipped schema, so the Unit and its Unit Campaigns
    cannot be removed by any caller — the lane deactivates its Unit Campaign (the read side filters
    ``isActive``) and records the rest as left behind.  Proving the absence here is what stops the
    next reader from "adding the missing teardown call" out of thin air.
    """
    sdl = _sdl()
    for available in ("deleteCampaign(", "deleteSellerProfile(", "deleteOrder("):
        assert available in sdl, f"the SDL no longer carries {available}, so the teardown cannot claim it"
    for absent in ("deleteUnit(", "deleteUnitCampaign(", "deleteInventory"):
        assert absent not in sdl, f"{absent} now exists: the lane's teardown has to call it"
    payload = stage2._SAMPLES["UpdateUnitCampaignInput"]
    assert payload["isActive"] is False and "expectedVersion" in payload["version"], payload


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
        {
            "movementType": "STOCK_ADJUSTMENT",
            "kernelPhysicalDelta": 2,
            "reason": "Trade with Troop 7150; money settled outside app",
        },
        {"movementType": "STOCK_ADJUSTMENT", "kernelPhysicalDelta": -1, "reason": "Gift to outgoing volunteer"},
    ]
    assert stage2.movement_trail_violations(trail, expected) == []


def test_a_write_that_ran_twice_is_reported_as_running_twice() -> None:
    """The duplicate a replayed mutation would leave behind is the trail's own evidence."""
    trail = [_movement(), _movement(movementId="Movement#2")]
    violations = stage2.movement_trail_violations(trail, [{"movementType": "RECEIPT", "kernelPhysicalDelta": 8}])
    assert violations == [
        "2 movements match {'movementType': 'RECEIPT', 'kernelPhysicalDelta': 8}: the write ran twice"
    ], violations


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
        _movement(
            movementId="Movement#2",
            movementType="STOCK_ADJUSTMENT",
            kernelPhysicalDelta=1,
            actorAccountId=None,
            reason="x",
        ),
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


# ---------------------------------------------------------------------------
# Cleanup is a gate: a failed or blocked step fails the run
# ---------------------------------------------------------------------------


def test_a_teardown_step_that_raises_comes_back_as_a_failed_verdict() -> None:
    """A refused mutation or an unmet read-back is a verdict, not a note in the record.

    Before this shape the lane caught ``GraphQLError`` in its teardown and appended an ordinary
    observation, so a refused ``deleteOrder`` left pytest green.  The verdict rule now lives in the
    support module, where a lane defect cannot hide behind a deployed stack.
    """
    for exc in (
        RuntimeError("deleteOrder refused: Forbidden"),
        AssertionError("custody balances still hold stock"),
        KeyError("unitScoutCampaignOrders"),
    ):

        def action(exc: BaseException = exc) -> str:
            raise exc

        row = stage2.run_cleanup_step("§2.8.7 teardown / ORD-API", action)
        assert row["result"] == stage2.CLEANUP_FAILED, exc
        assert type(exc).__name__ in row["summary"], row
        assert row["acceptance"] == "§2.8.7 teardown / ORD-API"


def test_a_step_the_environment_made_impossible_is_blocked_and_still_not_clean() -> None:
    """``blocked`` names a step the environment refused, and it never counts as cleanup done.

    The dev case is real: ``kernelworx-qa-ue1-dev`` is denied ``dynamodb:Scan`` on the Stage 2
    inventory table, so those rows are neither removed nor proven absent.  That belongs in the record
    as a gate that is not met.
    """

    def blocked() -> str:
        raise stage2.CleanupBlocked("BLOCKED kernelworx-inventory-ue1-dev: AccessDeniedException")

    rows = [
        stage2.cleanup_row("§2.8.7 teardown / INV-M-05", "returned 3 units, no custody row stands"),
        stage2.run_cleanup_step("§2.8.7 fixture sweep / lane", blocked),
    ]

    assert rows[1]["result"] == stage2.CLEANUP_BLOCKED
    assert stage2.cleanup_blocked(rows) == [
        "§2.8.7 fixture sweep / lane: CleanupBlocked: BLOCKED kernelworx-inventory-ue1-dev: AccessDeniedException"
    ]
    assert stage2.cleanup_problems(rows) == stage2.cleanup_blocked(rows)


def test_a_cleanup_gate_with_only_observations_is_clean() -> None:
    rows = [
        stage2.cleanup_row("§2.8.7 teardown / ORD-API", "deleted 3 Orders; none answer the campaign"),
        stage2.cleanup_row("§2.8.7 independent lane survived", "the canary lane answers the same rows"),
    ]
    stage2.assert_cleanup_clean(rows)
    assert stage2.cleanup_problems(rows) == []


def test_a_failed_cleanup_step_fails_the_run() -> None:
    """This is the regression the review asked for: cleanup failure and green cannot coexist.

    The lane calls :func:`~tests.e2e.utils.show_sell_stage2_support.assert_cleanup_clean` after it
    writes its evidence, so a failed teardown leaves both a record and a red run.
    """
    rows = [
        stage2.cleanup_row("§2.8.7 teardown / AUTH-P", "revokeShare refused: Forbidden", result=stage2.CLEANUP_FAILED)
    ]

    with pytest.raises(stage2.StageTwoCleanupError) as caught:
        stage2.assert_cleanup_clean(rows)
    assert "1 §2.8.7 cleanup step(s) not met" in str(caught.value)
    assert "revokeShare refused: Forbidden" in str(caught.value)


def test_a_blocked_cleanup_step_is_reported_and_fatal_only_under_the_strict_gate() -> None:
    """A step the environment refused is not the lane's failure, and it is never passed over.

    The lane reports it in ``cleanup.json`` as ``blocked`` with the error, and
    ``SS_STRICT_CLEANUP=1`` (``stage2.STRICT_CLEANUP``) turns it fatal — the state the gate reaches
    when the Stage 2 table grant lands for the QA identity.
    """
    rows = [
        stage2.cleanup_row(
            "§2.8.7 fixture sweep / lane",
            "BLOCKED kernelworx-inventory-ue1-dev: AccessDeniedException",
            result=stage2.CLEANUP_BLOCKED,
        )
    ]
    stage2.assert_cleanup_clean(rows)
    with pytest.raises(stage2.StageTwoCleanupError) as caught:
        stage2.assert_cleanup_clean(rows, strict=True)
    assert "BLOCKED kernelworx-inventory-ue1-dev" in str(caught.value)
    assert stage2.cleanup_failures(rows) == []
    assert stage2.cleanup_problems(rows) == stage2.cleanup_blocked(rows)


def test_the_strict_cleanup_gate_is_an_environment_switch_not_a_code_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flipping it has to be a runbook decision a reviewer can see, not an edit."""
    monkeypatch.delenv("SS_STRICT_CLEANUP", raising=False)
    assert stage2.STRICT_CLEANUP is False
    monkeypatch.setattr(stage2, "STRICT_CLEANUP", True)
    with pytest.raises(stage2.StageTwoCleanupError):
        stage2.assert_cleanup_clean(
            [stage2.cleanup_row("§2.8.7 fixture sweep / lane", "BLOCKED …", result=stage2.CLEANUP_BLOCKED)]
        )
    monkeypatch.setattr(stage2, "STRICT_CLEANUP", False)
    with pytest.raises(stage2.StageTwoCleanupError):
        stage2.assert_cleanup_clean(
            [stage2.cleanup_row("§2.8.7 teardown / ORD-API", "deleteOrder refused", result=stage2.CLEANUP_FAILED)]
        )


def test_a_sweep_report_is_judged_by_which_class_of_row_survived() -> None:
    """A surviving row is not one thing: the class says whether the lane may call itself clean.

    The sweeper's exit code only says something was left behind, and the lane used to read that as its
    own pass or fail.  Another tenant's row surviving is the proof the sweep was narrow enough; a row this
    lane's tokens named that no reviewed rule can attribute is residue nobody looked at, and is the lane's
    failure; the two residues checklist §2.8.7 accepts as amended (WORK-162) are recorded with their
    counts and are fatal only for a strict run; and a table no product read can answer is a gate that
    stays open, because nothing about it is proven.
    """
    clean: dict[str, list[str]] = {
        "left": [],
        "failed": [],
        "unknown": [],
        "history": [],
        "blocked": [],
        "unproven": [],
    }

    assert stage2.sweep_verdict(**clean) == stage2.CLEANUP_OBSERVED, (
        "kept rows are not passed to this function: they are the sweep working as intended"
    )
    for cls in ("left", "failed", "unknown"):
        assert stage2.sweep_verdict(**{**clean, cls: [f"{cls} inventory row"]}) == stage2.CLEANUP_FAILED, cls
    for cls in ("history", "blocked"):
        assert stage2.sweep_verdict(**{**clean, cls: [f"{cls} inventory row"]}) == stage2.CLEANUP_OBSERVED, cls
        assert (
            stage2.sweep_verdict(**{**clean, cls: [f"{cls} inventory row"]}, strict=True) == stage2.CLEANUP_BLOCKED
        ), f"{cls}: SS_STRICT_CLEANUP=1 is the reversal path the amendment names"
    assert (
        stage2.sweep_verdict(**{**clean, "unknown": ["UNKNOWN units row"], "blocked": ["BLOCKED table"]})
        == stage2.CLEANUP_FAILED
    ), "a survivor nobody can attribute outranks the permission that hid the rest"
    assert stage2.sweep_verdict(**{**clean, "blocked": ["BLOCKED table"], "unproven": ["table (dynamodb:Scan)"]}) == (
        stage2.CLEANUP_BLOCKED
    ), "an unreadable table no product read answers is residue that is neither removed nor proven absent"
    assert stage2.sweep_verdict(**clean, exit_code=1) == stage2.CLEANUP_FAILED, (
        "a non-zero sweep with nothing in the report to explain it is a failed cleanup, not a clean table"
    )
    assert (
        stage2.sweep_verdict(**{**clean, "history": ["HISTORY inventory row"]}, exit_code=1) == stage2.CLEANUP_OBSERVED
    ), "the sweeper exits non-zero over the accepted residue too — that exit is explained, not guessed at"


def test_the_two_accepted_residues_are_recorded_and_not_reported_as_cleaned() -> None:
    """Amendment B accepts a retained audit trail and an unreadable table; it does not hide either one.

    The lane has no supported path to an ``InventoryMovement`` delete and no grant to scan the Stage 2
    tables, so those two residues are a decision rather than a defect.  They still have to reach the record
    with their counts, and ``SS_STRICT_CLEANUP=1`` has to turn them back into a failed run — the acceptance
    is reversible without an edit, which is what keeps it an acceptance rather than a quiet default.
    """
    residue = {
        "left": [],
        "failed": [],
        "unknown": [],
        "history": ["HISTORY inventory row"],
        "blocked": ["BLOCKED kernelworx-inventory-ue1-dev: dynamodb:Scan"],
        "unproven": [],
    }

    accepted = stage2.cleanup_row(
        "§2.8.7 fixture sweep / lane",
        "1 lane history row(s) retained (inventory 1), 1 table(s) unreadable "
        "(kernelworx-inventory-ue1-dev: dynamodb:Scan); residue proven by product read: "
        "kernelworx-inventory-ue1-dev: inventoryMovements answered 13 row(s)",
        result=stage2.sweep_verdict(**residue),
    )
    assert accepted["result"] == stage2.CLEANUP_OBSERVED, "accepted residue is not the lane's fault"
    assert stage2.cleanup_problems([accepted]) == [], "the acceptance makes it non-fatal, not unsaid"
    assert "inventoryMovements answered 13 row(s)" in accepted["summary"], (
        "the row says what proves the residue is there, rather than asserting that it is gone"
    )

    strict = stage2.cleanup_row(
        "§2.8.7 fixture sweep / lane",
        accepted["summary"],
        result=stage2.sweep_verdict(**residue, strict=True),
    )
    assert strict["result"] == stage2.CLEANUP_BLOCKED
    assert stage2.cleanup_problems([strict]) == stage2.cleanup_blocked([strict])
    assert stage2.cleanup_failures([strict]) == [], "a residue this lane cannot remove is not its failure"
    with pytest.raises(stage2.StageTwoCleanupError):
        stage2.assert_cleanup_clean([strict], strict=True)


def test_the_lane_counts_its_residue_before_the_teardown_that_hides_it() -> None:
    """Amendment B's counts exist only while a read still answers, so the order in the ``finally`` is the gate.

    The sweep deletes the Unit and Unit Campaign rows every Stage 2 query is keyed on.  Counted afterwards,
    those reads answer ``NOT_FOUND`` and a careless record would print that as zero residue while the
    append-only movement rows sit on in the same partition.  So the census has to come first, then the
    product teardown, then the sweep.
    """
    tree = _spec_tree()
    test = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "test_show_sell_stage2_journey"
    )
    journey_try = next(node for node in ast.walk(test) if isinstance(node, ast.Try) and node.finalbody)
    calls = ast.Module(body=journey_try.finalbody, type_ignores=[])

    def first(name: str) -> int:
        return min(
            (node.lineno for node in ast.walk(calls) if isinstance(node, ast.Call) and name in ast.unparse(node.func)),
            default=0,
        )

    census, teardown, sweep = first("_residue_census"), first("_teardown_lane"), first("_lane_table_sweep")
    assert census and teardown and sweep, "the lane still counts, takes down, and sweeps its own lane"
    assert census < teardown < sweep, (
        "the residue census has to be read before the teardown and the sweep hide the rows it counts"
    )
    census_call = next(
        node for node in ast.walk(calls) if isinstance(node, ast.Call) and "_residue_census" in ast.unparse(node.func)
    )
    assert any(getattr(arg, "id", "") == "identities" for arg in census_call.args), (
        "the census reads through the fixture identities, never an AWS client of its own"
    )


def test_an_unanswerable_table_keeps_the_sweep_gate_open() -> None:
    """The amendment accepts residue it can name, not residue it has no way to see."""
    row = stage2.cleanup_row(
        "§2.8.7 fixture sweep / lane",
        "0 row(s) deleted, 3 table(s) unreadable (kernelworx-inventory-ue1-dev: dynamodb:Scan); "
        "residue no product read can prove: kernelworx-inventory-ue1-dev (dynamodb:Scan)",
        result=stage2.sweep_verdict(
            left=[],
            failed=[],
            unknown=[],
            history=[],
            blocked=["BLOCKED kernelworx-inventory-ue1-dev: dynamodb:Scan"],
            unproven=["kernelworx-inventory-ue1-dev (dynamodb:Scan)"],
        ),
    )

    assert row["result"] == stage2.CLEANUP_BLOCKED
    assert stage2.cleanup_blocked([row]), "the step is reported open, never as a cleanup that happened"
    assert "no product read can prove" in row["summary"]


def test_the_lane_reads_every_survivor_class_and_never_passes_on_the_exit_code_alone() -> None:
    """The report is only as good as the parser, so the classes have to survive the trip into the record."""
    sweep = next(
        node
        for node in ast.walk(_spec_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "_lane_table_sweep"
    )
    source = ast.unparse(sweep)
    support = Path(stage2.__file__).read_text(encoding="utf-8")

    for cls in ("LEFT", "FAILED", "kept", "UNKNOWN", "HISTORY"):
        assert f"startswith('{cls}')" in source, f"the lane stops seeing the sweeper's {cls} class"
    assert 'line.startswith("BLOCKED")' in support, "a denied table still reaches the record"
    assert "sweep_verdict" in source, "the verdict comes from the classes, not from a count"
    assert "unproven=" in source, (
        "a table this identity cannot read is only accepted where a product read answers its rows"
    )
    assert "exit_code=code" in source, (
        "a non-zero exit the record cannot explain is a failed cleanup, not an observed one"
    )


def test_every_table_the_sweep_cannot_read_is_answered_by_a_named_product_read() -> None:
    """Amendment B's acceptance is conditional: the residue has to be nameable without a scan.

    ``kernelworx-qa-ue1-dev`` is denied ``dynamodb:Scan`` on exactly the Stage 2 inventory, orders and
    order-fulfillment tables (``docs/QA_FIXTURE_RUNBOOK.md``), and the lane holds no other AWS path.  So the
    record answers each of those three with the application's own queries, scoped to the ids this lane was
    answered.  A fourth unreadable table with no entry here is reported as residue nobody can prove, which
    is the whole point of the mapping being a table rather than a sentence.
    """
    tree = _spec_tree()
    assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_RESIDUE_READS"
    )
    mapping: dict[str, tuple[str, ...]] = ast.literal_eval(assignment.value)

    assert set(mapping) == {"inventory", "orders", "order-fulfillments"}, (
        "the stand-ins are pinned to the tables the measured IAM reach denies; a new one names its read or "
        "stays unproven"
    )
    for documents in mapping.values():
        assert documents, "a table answered by nothing is not answered"
        for document in documents:
            assert document in stage2.STAGE_TWO_DOCUMENTS, f"{document} is not a query this lane can run"

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_lane_table_sweep"
    ]
    assert calls, "the lane still sweeps its own rows"
    for call in calls:
        assert len(call.args) + len(call.keywords) >= 3, (
            f"the sweep at line {call.lineno} names no product read to stand in for a table it cannot open"
        )
    probe = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_residue_probe")
    assert "except" in ast.unparse(probe), (
        "a probe that cannot run proves nothing: it must return no answer rather than an absent row"
    )


def test_an_unrecognized_cleanup_verdict_is_refused_at_the_row() -> None:
    """There is no third verdict that means "fine, move on"."""
    with pytest.raises(AssertionError, match="unknown cleanup result"):
        stage2.cleanup_row("§2.8.7 teardown", "something happened", result="blocked-then-retried")


def test_the_journey_judges_cleanup_after_it_has_written_the_evidence() -> None:
    """The record of a failed teardown is what a reviewer reads, and the run still has to fail."""
    tree = _spec_tree()
    test = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "test_show_sell_stage2_journey"
    )
    journey_try = next(node for node in ast.walk(test) if isinstance(node, ast.Try) and node.finalbody)
    final = journey_try.finalbody
    calls = [
        (ast.unparse(node.func), node.lineno)
        for node in ast.walk(ast.Module(body=final, type_ignores=[]))
        if isinstance(node, ast.Call)
    ]
    written = [line for name, line in calls if "_write_evidence" in name]
    judged = [line for name, line in calls if "assert_cleanup_clean" in name]
    assert written and judged, f"the finally block must write evidence and then judge cleanup: {calls}"
    assert written[0] < judged[0], "evidence first, verdict second"
    assert stage2.assert_cleanup_clean, "the gate is the support module's, so the unit suite can execute it"


def test_the_journey_records_every_cleanup_row_with_its_own_verdict() -> None:
    """A cleanup row is recorded with ``result=row["result"]``, never with the default."""
    tree = _spec_tree()
    test = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "test_show_sell_stage2_journey"
    )
    journey_try = next(node for node in ast.walk(test) if isinstance(node, ast.Try) and node.finalbody)
    final = journey_try.finalbody
    records = [
        node
        for node in ast.walk(ast.Module(body=final, type_ignores=[]))
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "record"
    ]
    assert records, "the finally block records the cleanup rows"
    for call in records:
        kwargs = {keyword.arg for keyword in call.keywords}
        assert "result" in kwargs, f"record at line {call.lineno} drops the verdict and defaults to observed"


def test_every_teardown_step_reports_through_the_verdict_helper() -> None:
    """One verdict rule, so a step cannot invent a friendlier outcome than the gate has."""
    tree = _spec_tree()
    teardown = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_teardown_lane"
    )
    appended = [
        (ast.unparse(call.func), ast.unparse(call.args[0]) if call.args else "")
        for call in ast.walk(teardown)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "append"
    ]
    verdicts = [expr for target, expr in appended if target == "rows.append"]
    assert verdicts, "the teardown collects a verdict per step"
    assert all("run_cleanup_step" in expr for expr in verdicts), (
        f"every verdict comes from stage2.run_cleanup_step: {verdicts}"
    )
    assert any("run_cleanup_step" in ast.unparse(call) for call in ast.walk(teardown) if isinstance(call, ast.Call)), (
        "the teardown must decide each verdict with stage2.run_cleanup_step"
    )
    assert not any(isinstance(node, ast.Try) for node in ast.walk(teardown) if node is not teardown), (
        "the teardown has no local try/except left to downgrade a refusal into an observation"
    )


def test_the_lane_sweeps_tables_through_the_fixture_script_and_never_through_aws() -> None:
    """The Unit and Unit Campaign rows go through ``scripts/qa_fixture.py sweep``.

    Project memory (AGENTS.md, "Show & Sell QA login fixture on the dev pool") says the acceptance
    harness holds no AWS credentials: a second path to a fixture row is a path that drifts.  So the
    lane names its own tokens and the sanctioned sweeper decides what is fixture-owned, and the
    support module reaches it by subprocess, not by boto3.
    """
    support = Path(stage2.__file__).read_text(encoding="utf-8")
    spec_source = _spec_source()

    assert '"sweep"' in support and "subprocess.run" in support, "the lane must call the sanctioned sweeper"
    assert "qa_fixture.py" in str(stage2.QA_FIXTURE_SCRIPT) and stage2.QA_FIXTURE_SCRIPT.is_file()
    for needle in ("boto3", 'client("dynamodb")'):
        assert needle not in support and needle not in spec_source, f"the lane reaches for AWS directly: {needle}"
    assert "_lane_table_sweep" in spec_source and "fixture_sweep" in spec_source
    assert "--lane" in support, "each sweep is narrowed by the lane's own tokens"


def test_the_lane_names_its_rows_by_kind_never_by_free_text() -> None:
    """A destructive sweep runs with ``--yes`` already given, so free text is not a scoping mechanism.

    ``scripts/qa_fixture.py sweep`` refuses a token that does not name its kind, and the refusal is
    worthless if the caller that builds the tokens hands over a bare ``DATA_ID``.  So the lane's token
    builder is pinned to the kinds its rows are actually keyed on, which is also the list that closes
    the attribution gap: a balance or custody row names a Unit Campaign and a product, a join-code
    pointer names a campaign id and a code, a roster row names a profile, and an active-join guard is
    the one row only its own Scout Campaign id can select.
    """
    builder = next(
        node
        for node in ast.walk(_spec_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "_lane_sweep_tokens"
    )
    kinds = {
        node.value
        for node in ast.walk(builder)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in stage2.LANE_TOKEN_KINDS
    }

    assert "data-id" in kinds, "the run's own DATA_ID is a kind, not a bare string"
    assert kinds >= set(stage2.LANE_TOKEN_KINDS), f"the lane stops naming part of what it wrote: {sorted(kinds)}"
    for call in ast.walk(builder):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "append":
            first = call.args[0] if call.args else None
            assert isinstance(first, ast.JoinedStr), "every token is kind=value"


def test_a_prior_lane_sweep_names_a_guard_by_its_campaign_id() -> None:
    """A prior run's active-join guard is only reachable by that run's Scout Campaign id.

    Every lane shares the same four fixture identities, and ``build_membership_guard_item`` writes one
    ``SCOUT_CAMPAIGN#<campaignId>/MEMBERSHIP_GUARD`` row per Scout Campaign, so a sweep that named only
    a profile would delete the guard of a Campaign another lane is still joined to.  The sweeper's rule
    requires the exact Campaign identity; the prior-lane sweep therefore reads each prior Unit
    Campaign's roster — the read that answers ``campaignId`` — while the join still exists, and hands
    those ids over as ``campaign=`` tokens.  A guard it cannot name is left and reported.
    """
    sweep = next(
        node
        for node in ast.walk(_spec_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "_sweep_prior_lanes"
    )
    source = ast.unparse(sweep)
    token_prefixes = {
        node.value
        for node in ast.walk(sweep)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.rstrip().endswith("=")
        and node.value.rstrip()[:-1] in stage2.LANE_TOKEN_KINDS
    }

    assert "'roster'" in source, "the prior run's Scout Campaign ids come from its roster rows"
    assert "campaign=" in token_prefixes, (
        f"the sweep stops naming the Campaigns whose guards it wants: {token_prefixes}"
    )
    assert "scout_campaign_ids" in source, "the Campaign ids are read before the profile delete takes them"


def test_the_lane_deactivates_only_the_campaigns_it_created() -> None:
    """A Unit this run reused can carry another run's Campaigns, and they are not this run's to switch off.

    Lane construction reuses a Unit that already answers this run's tenant key (``unitCreation`` says
    which happened), so the Unit's campaign list is not the same set as the campaigns this run created.
    The teardown therefore names its own campaign ids — the one it built plus the move leg's
    destination — and reports what it left alone.
    """
    teardown = next(
        node for node in ast.walk(_spec_tree()) if isinstance(node, ast.FunctionDef) and node.name == "_teardown_lane"
    )
    deactivate = next(
        node
        for node in ast.walk(teardown)
        if isinstance(node, ast.FunctionDef) and node.name == "deactivate_lane_campaigns"
    )

    created_binding = next(
        node
        for node in ast.walk(deactivate)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "created"
    )
    assert "extraCampaignIds" in ast.unparse(created_binding), (
        "the move leg's destination Campaign is part of what this run created"
    )
    guards = [ast.unparse(node.test) for node in ast.walk(deactivate) if isinstance(node, ast.If)]
    assert any("created" in test for test in guards), (
        f"deactivateUnitCampaign runs without a lane-created check: {guards}"
    )
    writes = [
        node
        for node in ast.walk(deactivate)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "deactivate_unit_campaign_input"
    ]
    assert writes, "the teardown still deactivates the lane's Unit Campaigns"
    assert "not_ours" in ast.unparse(deactivate), "what it left alone has to be in the record, not inferred"


def test_every_field_the_canary_snapshot_reads_is_one_its_query_selects() -> None:
    """A field the document never asks for reads as missing, and ``or 0`` turns that into a number.

    The first version of the canary snapshot summed ``totalQuantity``: the shipped ``Order`` type has no
    such field, so the sum was always 0 and the attached record said "0 units ordered" about a canary
    that had a sale.  The snapshot now walks the line quantities the selection carries, and refuses an
    Order that answers none.  The Unit Campaign's ``isActive`` is part of the snapshot for the same
    reason — the teardown's last GraphQL step is a deactivation, and a canary that was switched off
    would otherwise still answer identical balances.
    """
    document = stage2.STAGE_TWO_DOCUMENTS["unitScoutCampaignOrders"]
    snapshot = next(
        node for node in ast.walk(_spec_tree()) if isinstance(node, ast.FunctionDef) and node.name == "_lane_snapshot"
    )

    def selected(field: str) -> bool:
        return any(line.strip().rstrip("{").strip() == field for line in document.splitlines())

    def keys_read_from(loop: ast.For) -> set[str]:
        name = getattr(loop.target, "id", "")
        reads: set[str] = set()
        for node in ast.walk(loop):
            if (
                isinstance(node, ast.Subscript)
                and getattr(node.value, "id", "") == name
                and isinstance(node.slice, ast.Constant)
            ):
                reads.add(str(node.slice.value))
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "get"
                and getattr(node.func.value, "id", "") == name
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                reads.add(str(node.args[0].value))
        return reads

    order_loops = [
        node
        for node in ast.walk(snapshot)
        if isinstance(node, ast.For) and "orders" in ast.unparse(node.iter) and getattr(node.target, "id", "") == "row"
    ]
    assert order_loops, "the snapshot walks the Orders the read answered"
    reads = set().union(*(keys_read_from(loop) for loop in order_loops))
    assert {"orderId", "lineItems"} <= reads
    for field in reads:
        assert selected(field), f"unitScoutCampaignOrders does not select {field!r}"
    line_loops = [
        node for node in ast.walk(snapshot) if isinstance(node, ast.For) and getattr(node.iter, "id", "") == "lines"
    ]
    assert line_loops, "the snapshot sums line quantities, not an Order-level total"
    assert any(
        isinstance(node, ast.Assign) and "lineItems" in ast.unparse(node.value) for node in ast.walk(snapshot)
    ), "the lines being summed come from the selection's lineItems"
    for loop in line_loops:
        for field in keys_read_from(loop):
            assert selected(field), f"the lineItems selection does not carry {field!r}"
    assert "unitCampaignActive" in ast.unparse(snapshot)
    assert "totalQuantity" not in _sdl() and "totalQuantity" not in _spec_source()


def test_the_sweeper_is_wired_into_the_runbook_the_lane_is_run_from() -> None:
    """A cleanup path nobody can run is a cleanup path nobody runs."""
    runbook = (REPO_ROOT / "tests" / "e2e" / "README.md").read_text(encoding="utf-8")
    assert "qa_fixture.py sweep" in runbook or "qa_fixture.py\n    sweep" in runbook, (
        "tests/e2e/README.md must carry the sweep command the lane calls"
    )


def test_every_stage_two_screenshot_masks_the_join_code() -> None:
    """A Stage 2 tab is a Unit Campaign page, and it renders the live join code like the others."""
    for call in ast.walk(_spec_tree()):
        if not (isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "screenshot"):
            continue
        assert any(keyword.arg == "mask" for keyword in call.keywords), (
            f"page.screenshot at line {call.lineno} has no mask"
        )
    signature = next(
        node for node in ast.walk(_spec_tree()) if isinstance(node, ast.FunctionDef) and node.name == "_screenshot"
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
