"""Leaf 2.2 — the inventory balance resolvers, end to end through the handler.

Resolver-level tests for §2.2.1-§2.2.4 (`INV-M-01`, `INV-M-02`, `INV-M-03`,
`INV-Q-01`, `INV-Q-02`, `AUTH-U`, `PAGE-01`). Each case goes through
``handle_unit_operation`` against moto, so it exercises the real auth check, the
real idempotency marker, the real conditional transaction, and the real payload
the browser would receive — the layer where "the balance moved by one" is either
true or not.

The two tables a Stage 2 write must NOT touch are asserted as explicitly as the
ones it must: a receipt that also created an Order, a payment, or a We Owe
obligation would make the stock count and the money impossible to reconcile
against each other (§2.2.1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    INVENTORY_MOVEMENTS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    RECORD_RECEIPT_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from tests.unit.show_sell_fixtures import (
    PACK_3149_FALL,
    PACK_3149_OLD,
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_CAMPAIGN = PACK_3149_OLD
# The one product the fixture catalog offers, spelled the way this application
# spells product ids: the catalog id is part of it.
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
MISSING_PRODUCT = f"{CATALOG_ID}#prod-404"
OTHER_CATALOG_PRODUCT = "CATALOG#fixture-public#prod-1"
PROFILE = "PROFILE#prof-devon-fixture"
EVENT = "SSE#fixture-morning"
MORNING = "2026-11-07T08:00:00+00:00"
AFTERNOON = "2026-11-07T13:00:00+00:00"


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """One resolver turn through the deployed entry point."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _ok(payload: Any) -> Dict[str, Any]:
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _receipt(
    caller: str = "Avery",
    *,
    product_id: str = PRODUCT,
    quantity: Any = 10,
    key: str = "receipt-1",
    occurred_at: Optional[str] = None,
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": CAMPAIGN,
        "productId": product_id,
        "quantity": quantity,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(RECORD_RECEIPT_FIELD, caller, mutation=mutation)


def _adjust(
    caller: str = "Avery",
    *,
    product_id: str = PRODUCT,
    delta: Any = -2,
    reason: Optional[str] = "counted miscount",
    key: str = "adjust-1",
    campaign: str = CAMPAIGN,
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": product_id,
        "quantityDelta": delta,
        **_idem(key),
    }
    if reason is not None:
        mutation["reason"] = reason
    return _call(ADJUST_INVENTORY_FIELD, caller, mutation=mutation)


def _council(
    caller: str = "Avery",
    *,
    product_id: str = PRODUCT,
    delta: Any = 5,
    reason: Optional[str] = "council promised a second case",
    key: str = "council-1",
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": CAMPAIGN,
        "productId": product_id,
        "quantityDelta": delta,
        **_idem(key),
    }
    if reason is not None:
        mutation["reason"] = reason
    return _call(ADJUST_COUNCIL_FIELD, caller, mutation=mutation)


def _positions(**arguments: Any) -> Any:
    return _call(INVENTORY_POSITIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN, **arguments})


def _movements(**arguments: Any) -> Any:
    return _call(INVENTORY_MOVEMENTS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN, **arguments})


def _rows(inventory_table: Any, campaign: str = CAMPAIGN) -> List[Dict[str, Any]]:
    """Every inventory row of one campaign partition, in sort-key order."""
    items: List[Dict[str, Any]] = []
    token: Optional[Dict[str, Any]] = None
    while True:
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": f"UNIT_CAMPAIGN#{campaign}"},
        }
        if token is not None:
            kwargs["ExclusiveStartKey"] = token
        page = inventory_table.query(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            break
    return items


def _balances(inventory_table: Any, campaign: str = CAMPAIGN) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table, campaign) if row.get("entityType") == "InventoryBalance"]


def _movement_rows(inventory_table: Any, campaign: str = CAMPAIGN) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table, campaign) if row.get("entityType") == "InventoryMovement"]


def _seed_balance(
    inventory_table: Any,
    *,
    physical: int,
    reserved: int = 0,
    on_order: int = 0,
    product_id: str = PRODUCT,
    version: int = 1,
) -> Dict[str, Any]:
    item = inv.build_inventory_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        kernel_physical_qty=physical,
        sold_in_possession_qty=reserved,
        council_on_order_qty=on_order,
        now_iso=MORNING,
        version=version,
    )
    inventory_table.put_item(Item=item)
    return item


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    inventory_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world plus the inventory table these mutations write."""
    return seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
    )


# --- INV-M-01: recordInventoryReceipt (§2.2.1) -----------------------------------


def test_inv_m_01_01_first_receipt_opens_a_balance_and_appends_one_movement(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-01-01: one write, one audit row, and the position that came back."""
    position = _ok(_receipt(quantity=12, occurred_at=MORNING))

    assert position["unitCampaignId"] == CAMPAIGN
    assert position["productId"] == PRODUCT
    assert position["kernelPhysicalQty"] == 12
    assert position["soldInPossessionQty"] == 0
    assert position["councilOnOrderQty"] == 0
    assert position["version"] == 1
    assert position["sellableKernelQty"] == 12
    assert position["withScoutQty"] == 0
    assert position["createdAt"] == MORNING

    balances = _balances(inventory_table)
    assert len(balances) == 1 and balances[0]["version"] == 1
    movements = _movement_rows(inventory_table)
    assert len(movements) == 1
    movement = movements[0]
    assert movement["movementType"] == "RECEIPT"
    assert movement["kernelPhysicalDelta"] == 12
    assert movement["actorAccountId"] == account_id("Avery")
    assert movement["inventoryVersion"] == 1
    assert movement["idempotencyKey"] == "receipt-1"
    assert movement["occurredAt"] == MORNING
    assert "version" not in movement


def test_inv_m_01_02_a_second_receipt_increments_the_same_balance(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-01-02: stock arriving twice is one balance at two versions."""
    _ok(_receipt(quantity=12, key="receipt-1", occurred_at=MORNING))
    position = _ok(_receipt(quantity=5, key="receipt-2", occurred_at=AFTERNOON))

    assert position["kernelPhysicalQty"] == 17
    assert position["version"] == 2
    assert len(_balances(inventory_table)) == 1
    assert [row["kernelPhysicalDelta"] for row in _movement_rows(inventory_table)] == [12, 5]
    assert [row["inventoryVersion"] for row in _movement_rows(inventory_table)] == [1, 2]


def test_inv_m_01_03_a_quantity_that_is_not_positive_is_refused_without_a_write(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-01-03: zero, negative, and non-integer quantities never reach storage."""
    for quantity in (0, -4, "twelve", None, True):
        assert_is_error(_receipt(quantity=quantity, key=f"receipt-{quantity}"), "INVALID_INPUT")
    assert _rows(inventory_table) == []


def test_inv_m_01_04_stock_for_a_product_the_campaign_does_not_sell_is_refused(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-01-04: the campaign's own catalog is the allowlist, not the caller's word."""
    for product in (MISSING_PRODUCT, OTHER_CATALOG_PRODUCT):
        assert_is_error(_receipt(product_id=product, quantity=4, key=f"receipt-{product}"), "INVALID_INPUT")
    assert _rows(inventory_table) == []


def test_inv_m_01_05_a_retry_returns_the_original_result_and_moves_nothing_again(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-01-05: the same key and payload answer identically, once."""
    first = _ok(_receipt(quantity=12, key="receipt-1", occurred_at=MORNING))
    again = _ok(_receipt(quantity=12, key="receipt-1", occurred_at=MORNING))

    assert again == first
    assert len(_balances(inventory_table)) == 1
    assert _balances(inventory_table)[0]["version"] == 1
    assert len(_movement_rows(inventory_table)) == 1


def test_inv_m_01_06_a_retry_with_a_changed_payload_is_refused(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-01-06: one key cannot mean two different receipts.

    The shared mutation machinery answers a reused key whose content differs with
    ``INVALID_INPUT`` / ``IDEMPOTENCY_FINGERPRINT_MISMATCH`` — the caller's key was
    wrong, not the state of the row — and writes nothing either way.
    """
    _ok(_receipt(quantity=12, key="receipt-1"))
    refused = assert_is_error(_receipt(quantity=99, key="receipt-1"), "INVALID_INPUT")
    assert "idempotencyKey" in refused["message"]
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 12
    assert len(_movement_rows(inventory_table)) == 1


def test_inv_m_01_07_a_receipt_creates_no_order_payment_credit_or_obligation(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, campaigns_table: Any
) -> None:
    """INV-M-01-07: stock count and money stay separate records."""
    before = campaigns_table.scan()["Items"]
    _ok(_receipt(quantity=12, key="receipt-1"))
    _ok(_adjust(delta=-3, key="adjust-1"))
    _ok(_council(delta=4, key="council-1"))

    assert orders_table.scan().get("Items", []) == []
    after = campaigns_table.scan()["Items"]
    assert [row.get("totalOrders") for row in after] == [row.get("totalOrders") for row in before]
    assert [row.get("totalRevenue") for row in after] == [row.get("totalRevenue") for row in before]
    # Only balance and audit rows exist in the campaign's inventory partition: no
    # sale, obligation, allocation, or custody row appeared.
    assert {row["entityType"] for row in _rows(inventory_table)} == {"InventoryBalance", "InventoryMovement"}


def test_inv_m_01_08_a_backdated_receipt_lands_where_its_instant_sorts(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The business moment, not the terminal clock, orders the audit trail."""
    _ok(_receipt(quantity=3, key="receipt-old", occurred_at="2026-11-07T08:00:00+00:00"))
    _ok(_receipt(quantity=4, key="receipt-new", occurred_at="2026-11-07T09:00:00+00:00"))
    assert [row["occurredAt"] for row in _movement_rows(inventory_table)] == [
        "2026-11-07T08:00:00+00:00",
        "2026-11-07T09:00:00+00:00",
    ]


def test_inv_m_01_09_a_campaign_whose_catalog_row_is_gone_is_not_found(
    world: Dict[str, Any], catalogs_table: Any, inventory_table: Any
) -> None:
    """The catalog guard reads the campaign's own catalog; a missing row is NOT_FOUND.

    A campaign pointing at nothing has no allowlist to check the product against,
    and inventing one would let stock in for a catalog the Unit never had.
    """
    for row in catalogs_table.scan()["Items"]:
        if row.get("catalogId") == CATALOG_ID:
            key = {field["AttributeName"]: row[field["AttributeName"]] for field in catalogs_table.key_schema}
            catalogs_table.delete_item(Key=key)

    assert_is_error(_receipt(quantity=4, key="receipt-no-catalog"), "NOT_FOUND")
    assert _rows(inventory_table) == []


def test_a_position_that_vanished_after_the_commit_is_an_internal_fault(
    world: Dict[str, Any], inventory_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reply is rebuilt from the committed row, and a row that is gone is a fault.

    Answering with a zero position would report stock that the mutation just moved,
    so the resolver says INTERNAL_ERROR instead — and the write itself stays
    committed, because the transaction already won.
    """

    def no_rows(*_args: Any, **_kwargs: Any) -> Dict[str, List[Dict[str, Any]]]:
        return {"balance": [], "allocations": [], "custody": []}

    monkeypatch.setattr(inv, "inventory_position_rows", no_rows)
    assert_is_error(_receipt(quantity=6, key="receipt-vanished"), "INTERNAL_ERROR")

    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 6


# --- INV-M-02: adjustInventory (§2.2.2) ------------------------------------------


def test_inv_m_02_01_a_gift_or_trade_moves_stock_and_says_why(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-02-01/02: a signed adjustment with a reason, and nothing else."""
    _ok(_receipt(quantity=10, key="receipt-1"))
    position = _ok(_adjust(delta=-3, reason="gifted two Kernels to Troop 7150", key="adjust-1"))

    assert position["kernelPhysicalQty"] == 7
    assert position["sellableKernelQty"] == 7
    assert position["version"] == 2
    movement = _movement_rows(inventory_table)[-1]
    assert movement["movementType"] == "STOCK_ADJUSTMENT"
    assert movement["kernelPhysicalDelta"] == -3
    assert movement["reason"] == "gifted two Kernels to Troop 7150"
    assert movement["inventoryVersion"] == 2
    # A trade records no money here: taking payment is a different operation, so
    # nothing sale-shaped may appear in the partition this write owns.
    assert {row["entityType"] for row in _rows(inventory_table)} == {"InventoryBalance", "InventoryMovement"}


def test_inv_m_02_02_an_adjustment_below_the_reserved_quantity_is_refused(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-02-03: ``kernelPhysicalQty >= soldInPossessionQty >= 0`` (§4.1)."""
    _seed_balance(inventory_table, physical=6, reserved=4, version=3)
    assert_is_error(_adjust(delta=-3, key="adjust-1"), "INVALID_INPUT")

    balance = _balances(inventory_table)[0]
    assert balance["kernelPhysicalQty"] == 6
    assert balance["version"] == 3
    assert _movement_rows(inventory_table) == []
    # Down to the reservation exactly is legal.
    assert _ok(_adjust(delta=-2, key="adjust-2"))["kernelPhysicalQty"] == 4


def test_inv_m_02_03_an_adjustment_below_zero_physical_stock_is_refused(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """A count cannot go negative, and the caller gets the actionable verdict."""
    _seed_balance(inventory_table, physical=3)
    assert_is_error(_adjust(delta=-4, key="adjust-1"), "INVALID_INPUT")
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 3
    assert _movement_rows(inventory_table) == []


def test_inv_m_02_04_a_missing_reason_or_a_zero_delta_is_refused(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-02-04: an adjustment with no explanation is an untraceable stock change."""
    _seed_balance(inventory_table, physical=10)
    assert_is_error(_adjust(reason=None, key="adjust-1"), "INVALID_INPUT")
    assert_is_error(_adjust(reason="   ", key="adjust-2"), "INVALID_INPUT")
    assert_is_error(_adjust(delta=0, key="adjust-3"), "INVALID_INPUT")
    assert len(_movement_rows(inventory_table)) == 0
    assert _balances(inventory_table)[0]["version"] == 1


def test_inv_m_02_05_a_stale_read_loses_the_whole_transaction(world: Dict[str, Any], inventory_table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-M-02-05 (race): the version guard cancels the plan, movement included."""
    _seed_balance(inventory_table, physical=10, version=4)
    stale = dict(_balances(inventory_table)[0], version=3, kernelPhysicalQty=9)
    monkeypatch.setattr(inv, "read_inventory_balance", lambda *_a, **_k: stale)

    assert_is_error(_adjust(delta=-2, key="adjust-1"), "CONFLICT")

    balance = _balances(inventory_table)[0]
    assert balance["version"] == 4 and balance["kernelPhysicalQty"] == 10
    assert _movement_rows(inventory_table) == [], "a lost race may not leave an audit row behind"


def test_inv_m_02_06_a_retry_of_an_adjustment_applies_once(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-02-06: the marker replays the answer the first attempt committed."""
    _seed_balance(inventory_table, physical=10)
    first = _ok(_adjust(delta=-4, key="adjust-1"))
    again = _ok(_adjust(delta=-4, key="adjust-1"))

    assert again == first
    assert again["kernelPhysicalQty"] == 6
    assert _balances(inventory_table)[0]["version"] == 2
    assert len(_movement_rows(inventory_table)) == 1


def test_inv_m_02_07_an_adjustment_may_count_out_a_product_the_catalog_dropped(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """A receipt needs a catalog product; a count-out does not, or the stock is stranded."""
    _seed_balance(inventory_table, physical=4, product_id=MISSING_PRODUCT)
    position = _ok(_adjust(product_id=MISSING_PRODUCT, delta=-4, reason="product dropped, stock counted out", key="adjust-1"))

    assert position["kernelPhysicalQty"] == 0
    assert _movement_rows(inventory_table)[-1]["productId"] == MISSING_PRODUCT


# --- INV-M-03: adjustCouncilOnOrder (§2.2.3) -------------------------------------


def test_inv_m_03_01_the_on_order_balance_moves_alone(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-03-01: expected Council supply is counted beside the Kernels, not inside them."""
    _seed_balance(inventory_table, physical=10, reserved=2)
    _ok(_council(delta=6, key="council-1"))

    balance = _balances(inventory_table)[0]
    assert balance["councilOnOrderQty"] == 6
    assert balance["kernelPhysicalQty"] == 10
    assert balance["soldInPossessionQty"] == 2
    assert balance["version"] == 2

    position = _ok(_positions())["items"][0]
    assert position["councilOnOrderQty"] == 6
    assert position["sellableKernelQty"] == 8
    assert position["withScoutQty"] == 0
    movement = _movement_rows(inventory_table)[-1]
    assert movement["movementType"] == "COUNCIL_ON_ORDER_ADJUST"
    assert movement["councilOnOrderDelta"] == 6
    assert movement["kernelPhysicalDelta"] == 0


def test_inv_m_03_02_a_zero_delta_is_refused_and_zero_result_is_not(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-03-02: bringing the balance to zero is a real answer; a no-op is not."""
    _seed_balance(inventory_table, physical=10, on_order=5)
    assert_is_error(_council(delta=0, key="council-1"), "INVALID_INPUT")
    assert _balances(inventory_table)[0]["councilOnOrderQty"] == 5
    assert _ok(_council(delta=-5, key="council-2"))["councilOnOrderQty"] == 0


def test_inv_m_03_03_the_on_order_balance_cannot_go_negative(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-03-03: a promise cannot be un-promised twice."""
    _seed_balance(inventory_table, physical=10, on_order=3)
    assert_is_error(_council(delta=-4, key="council-1"), "INVALID_INPUT")
    balance = _balances(inventory_table)[0]
    assert balance["councilOnOrderQty"] == 3 and balance["version"] == 1
    assert _movement_rows(inventory_table) == []


def test_inv_m_03_04_a_retry_of_an_on_order_adjustment_applies_once(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-03-04: replay returns the same position and one movement."""
    _seed_balance(inventory_table, physical=10)
    first = _ok(_council(delta=6, key="council-1"))
    again = _ok(_council(delta=6, key="council-1"))

    assert again == first
    assert _balances(inventory_table)[0]["councilOnOrderQty"] == 6
    assert len(_movement_rows(inventory_table)) == 1


def test_inv_m_03_05_a_reason_is_optional_on_the_on_order_path(world: Dict[str, Any], inventory_table: Any) -> None:
    """The API contract makes this the one adjustment whose note is optional."""
    _seed_balance(inventory_table, physical=10)
    _ok(_council(delta=2, reason=None, key="council-1"))
    assert "reason" not in _movement_rows(inventory_table)[-1]


# --- AUTH-U: Unit Admin only, for every Stage 2 field ----------------------------


@pytest.mark.parametrize(
    ("field", "arguments"),
    [
        (RECORD_RECEIPT_FIELD, {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantity": 4, **_idem("a")}}),
        (ADJUST_INVENTORY_FIELD, {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantityDelta": -1, "reason": "miscount", **_idem("b")}}),
        (ADJUST_COUNCIL_FIELD, {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantityDelta": 1, **_idem("c")}}),
        (INVENTORY_POSITIONS_FIELD, {"unitCampaignId": CAMPAIGN}),
        (INVENTORY_MOVEMENTS_FIELD, {"unitCampaignId": CAMPAIGN}),
    ],
    ids=["recordInventoryReceipt", "adjustInventory", "adjustCouncilOnOrder", "inventoryPositions", "inventoryMovements"],
)
def test_auth_u_no_caller_outside_the_units_admin_list_reaches_a_stage_two_field(
    world: Dict[str, Any], inventory_table: Any, field: str, arguments: Dict[str, Any]
) -> None:
    """AUTH-U: no session, a removed admin, a Scout, and another Unit's admin are all denied."""
    # No session at all.
    assert_is_error(_call(field, None, arguments=arguments), "UNAUTHORIZED")
    for caller in ("Blake", "Devon", "Riley", "Taylor"):
        # A revoked grant reads like a Unit that does not exist, so a denial never
        # confirms which Units are in this tenant.
        assert_is_error(_call(field, caller, arguments=arguments), "NOT_FOUND")
    assert _rows(inventory_table) == []


def test_auth_u_a_campaign_of_another_unit_is_not_an_access_path(world: Dict[str, Any], inventory_table: Any) -> None:
    """A Crew admin may not write a Pack campaign's stock by naming its id."""
    assert_is_error(_call(ADJUST_INVENTORY_FIELD, "Riley", mutation={
        "unitCampaignId": CAMPAIGN,
        "productId": PRODUCT,
        "quantityDelta": -1,
        "reason": "wrong unit",
        **_idem("cross"),
    }), "NOT_FOUND")
    assert _rows(inventory_table) == []


def test_auth_u_an_unknown_campaign_is_not_found_before_any_write(world: Dict[str, Any], inventory_table: Any) -> None:
    assert_is_error(
        _call(
            RECORD_RECEIPT_FIELD,
            "Avery",
            mutation={"unitCampaignId": "uc-does-not-exist", "productId": PRODUCT, "quantity": 4, **_idem("x")},
        ),
        "NOT_FOUND",
    )
    assert _rows(inventory_table) == []


# --- INV-Q-01: inventoryPositions (§2.2.4) ---------------------------------------


def test_inv_q_01_01_positions_answer_per_product_with_the_derived_quantities(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-Q-01-01: the board's numbers come from the raw rows on every read."""
    _seed_balance(inventory_table, physical=10, reserved=4)
    _seed_balance(inventory_table, physical=6, product_id=OTHER_CATALOG_PRODUCT)
    inventory_table.put_item(
        Item=inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at="2026-11-07T08:00:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            allocated_qty=5,
            now_iso=MORNING,
        )
    )
    inventory_table.put_item(
        Item=inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=PROFILE,
            campaign_id="CAMPAIGN#camp-devon-fixture",
            with_scout_qty=3,
            now_iso=MORNING,
        )
    )

    items = _ok(_positions())["items"]
    assert [item["productId"] for item in items] == sorted([PRODUCT, OTHER_CATALOG_PRODUCT])
    first = items[0]
    assert first["kernelPhysicalQty"] == 10 and first["soldInPossessionQty"] == 4
    assert first["sellableKernelQty"] == 6
    assert first["assignedOpenQty"] == 5
    assert first["unassignedKernelQty"] == 1
    assert first["assignmentOverageQty"] == 0
    assert first["withScoutQty"] == 3
    assert first["totalUnitOwnedUndeliveredQty"] == 13
    assert first["version"] == 1
    # The other product's position sees none of this.
    assert items[1]["withScoutQty"] == 0 and items[1]["assignedOpenQty"] == 0


def test_inv_q_01_02_an_explicit_product_list_answers_in_order_including_zeros(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-Q-01-02: a catalog product with nothing received still renders."""
    _seed_balance(inventory_table, physical=7)
    items = _ok(_positions(productIds=[MISSING_PRODUCT, PRODUCT]))["items"]

    assert [item["productId"] for item in items] == [MISSING_PRODUCT, PRODUCT]
    assert items[0]["kernelPhysicalQty"] == 0 and items[0]["version"] == 0
    assert items[0]["createdAt"] is None and items[0]["updatedAt"] is None
    assert items[1]["kernelPhysicalQty"] == 7

    assert_is_error(_positions(productIds=[f"p-{index}" for index in range(16)]), "INVALID_INPUT")
    assert_is_error(_positions(productIds=[PRODUCT, PRODUCT]), "INVALID_INPUT")


def test_inv_q_01_03_a_position_never_reports_a_negative_unassigned_count(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """Over-assignment is an overage the admin can act on, not a negative remainder."""
    _seed_balance(inventory_table, physical=3)
    for event_id, allocated in (("SSE#morning", 2), ("SSE#afternoon", 2)):
        inventory_table.put_item(
            Item=inv.build_event_inventory_allocation_item(
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                show_and_sell_id=event_id,
                start_at="2026-11-07T08:00:00+00:00",
                end_at="2026-11-07T12:00:00+00:00",
                allocated_qty=allocated,
                now_iso=MORNING,
            )
        )
    item = _ok(_positions())["items"][0]
    assert item["assignedOpenQty"] == 4
    assert item["unassignedKernelQty"] == 0
    assert item["assignmentOverageQty"] == 1


def test_inv_q_01_04_a_released_allocation_stops_counting_as_assigned(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The position reads status, so a released event frees its stock without a rewrite."""
    _seed_balance(inventory_table, physical=6)
    inventory_table.put_item(
        Item=inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at="2026-11-07T08:00:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            allocated_qty=4,
            status=inv.ALLOCATION_RELEASED,
            now_iso=MORNING,
        )
    )
    item = _ok(_positions())["items"][0]
    assert item["assignedOpenQty"] == 0 and item["unassignedKernelQty"] == 6


# --- INV-Q-02: inventoryMovements (§2.2.4) ---------------------------------------


def _seed_movements(inventory_table: Any) -> None:
    """Three receipts and one custody issue across two products."""
    for index, moment in enumerate(("2026-11-07T08:00:00+00:00", "2026-11-07T09:00:00+00:00", "2026-11-08T08:00:00+00:00")):
        inventory_table.put_item(
            Item=inv.build_inventory_movement_item(
                movement_id=f"mov-{index}",
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                movement_type=inv.RECEIPT,
                actor_account_id=account_id("Avery"),
                occurred_at=moment,
                idempotency_key=f"seed-receipt-{index}",
                kernel_physical_delta=4,
                reason=None,
                inventory_version=index + 1,
            )
        )
    inventory_table.put_item(
        Item=inv.build_inventory_movement_item(
            movement_id="mov-issue",
            unit_campaign_id=CAMPAIGN,
            product_id=OTHER_CATALOG_PRODUCT,
            movement_type=inv.SCOUT_ISSUE,
            actor_account_id=account_id("Avery"),
            occurred_at="2026-11-07T10:00:00+00:00",
            idempotency_key="seed-issue-1",
            kernel_physical_delta=-2,
            with_scout_delta=2,
            profile_id=PROFILE,
            show_and_sell_id=EVENT,
            reason="issued for the morning slot",
            inventory_version=1,
        )
    )
    for product_id, physical in ((PRODUCT, 12), (OTHER_CATALOG_PRODUCT, 0)):
        inventory_table.put_item(
            Item=inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN, product_id=product_id, kernel_physical_qty=physical, now_iso=MORNING
            )
        )


def test_inv_q_02_01_history_comes_back_newest_first_with_the_audit_fields(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-Q-02-01: actor, reason, source links, and the version each movement produced."""
    _seed_movements(inventory_table)
    items = _ok(_movements())["items"]

    assert [item["movementId"] for item in items] == ["mov-2", "mov-issue", "mov-1", "mov-0"]
    issue = items[1]
    assert issue["movementType"] == "SCOUT_ISSUE"
    assert issue["actorAccountId"] == account_id("Avery")
    assert issue["reason"] == "issued for the morning slot"
    assert issue["profileId"] == PROFILE and issue["showAndSellId"] == EVENT
    assert issue["kernelPhysicalDelta"] == -2 and issue["withScoutDelta"] == 2
    assert issue["inventoryVersion"] == 1
    assert issue["idempotencyKey"] == "seed-issue-1"


def test_inv_q_02_02_every_filter_selects_its_own_slice(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-Q-02-02: product, type, event, Scout, and window are all honoured."""
    _seed_movements(inventory_table)

    assert [item["movementId"] for item in _ok(_movements(productId=PRODUCT))["items"]] == ["mov-2", "mov-1", "mov-0"]
    assert [item["movementId"] for item in _ok(_movements(movementType="SCOUT_ISSUE"))["items"]] == ["mov-issue"]
    assert [item["movementId"] for item in _ok(_movements(showAndSellId=EVENT))["items"]] == ["mov-issue"]
    assert [item["movementId"] for item in _ok(_movements(profileId=PROFILE))["items"]] == ["mov-issue"]
    # The window is inclusive at both ends: this start is exactly ``mov-1``.
    window = _ok(_movements(dateRange={"startAt": "2026-11-07T09:00:00+00:00", "endAt": "2026-11-07T23:59:59+00:00"}))["items"]
    assert [item["movementId"] for item in window] == ["mov-issue", "mov-1"]
    combined = _ok(_movements(productId=PRODUCT, movementType="RECEIPT", dateRange={"startAt": "2026-11-08T00:00:00+00:00"}))["items"]
    assert [item["movementId"] for item in combined] == ["mov-2"]
    assert_is_error(_movements(movementType="DONATION"), "INVALID_INPUT")


def test_inv_q_02_03_a_window_wider_than_366_days_is_refused(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-Q-02-03: an unbounded window is a full-partition scan wearing a filter."""
    _seed_movements(inventory_table)
    assert_is_error(
        _movements(dateRange={"startAt": "2025-01-01T00:00:00+00:00", "endAt": "2026-11-07T00:00:00+00:00"}),
        "INVALID_INPUT",
    )
    assert_is_error(_movements(dateRange={"startAt": AFTERNOON, "endAt": MORNING}), "INVALID_INPUT")


def test_inv_q_02_04_a_movement_read_sees_only_its_own_campaign(world: Dict[str, Any], inventory_table: Any) -> None:
    """Two campaigns of the same Unit never share an audit trail."""
    _seed_movements(inventory_table)
    inventory_table.put_item(
        Item=inv.build_inventory_movement_item(
            movement_id="mov-other",
            unit_campaign_id=OTHER_CAMPAIGN,
            product_id=PRODUCT,
            movement_type=inv.RECEIPT,
            actor_account_id=account_id("Avery"),
            occurred_at="2025-04-01T08:00:00+00:00",
            idempotency_key="seed-other",
            kernel_physical_delta=1,
        )
    )
    assert [item["movementId"] for item in _ok(_movements())["items"]][0] != "mov-other"
    other = _call(INVENTORY_MOVEMENTS_FIELD, "Avery", arguments={"unitCampaignId": OTHER_CAMPAIGN})
    assert [item["movementId"] for item in _ok(other)["items"]] == ["mov-other"]


def test_inv_q_02_05_the_movement_detail_reconciles_with_the_position(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """Detail reconciliation: the audit trail sums to the balance it produced.

    The two views are read separately and must agree exactly — an admin who adds up
    the movements of a product has to land on the position the board shows, or the
    stock count cannot be defended after the fact (§2.2.4). Each movement also names
    the balance version it created, so a reader can tell that no write is missing
    between two rows of history.
    """
    _ok(_receipt(quantity=10, key="reconcile-receipt"))
    _ok(_council(delta=4, key="reconcile-council"))
    _ok(_adjust(delta=-3, key="reconcile-adjust", reason="case left on the trailer"))
    inventory_table.put_item(
        Item=inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at="2026-11-07T08:00:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            allocated_qty=5,
            now_iso=MORNING,
        )
    )
    inventory_table.put_item(
        Item=inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=PROFILE,
            campaign_id="CAMPAIGN#camp-devon-fixture",
            with_scout_qty=2,
            now_iso=MORNING,
        )
    )

    movements = _ok(_movements())["items"]
    position = _ok(_positions())["items"][0]
    assert [item["movementType"] for item in movements] == [
        inv.STOCK_ADJUSTMENT,
        inv.COUNCIL_ON_ORDER_ADJUST,
        inv.RECEIPT,
    ]
    assert len(movements) == len(_movement_rows(inventory_table))

    totals = {
        field: sum(item[field] for item in movements)
        for field in (
            "kernelPhysicalDelta",
            "soldPossessionDelta",
            "withScoutDelta",
            "assignedDelta",
            "councilOnOrderDelta",
        )
    }
    assert totals == {
        "kernelPhysicalDelta": 7,
        "soldPossessionDelta": 0,
        "withScoutDelta": 0,
        "assignedDelta": 0,
        "councilOnOrderDelta": 4,
    }
    assert position["kernelPhysicalQty"] == totals["kernelPhysicalDelta"]
    assert position["councilOnOrderQty"] == totals["councilOnOrderDelta"]
    assert position["soldInPossessionQty"] == totals["soldPossessionDelta"] == 0
    # Custody and allocation rows are read from their own rows, never inferred from
    # the movement deltas: only the Scout issue and a sale move those quantities.
    assert position["withScoutQty"] == 2 and position["assignedOpenQty"] == 5
    assert position["sellableKernelQty"] == 7 and position["unassignedKernelQty"] == 2
    assert position["totalUnitOwnedUndeliveredQty"] == 9

    assert [item["inventoryVersion"] for item in movements] == [3, 2, 1]
    assert position["version"] == 3
    assert {item["actorAccountId"] for item in movements} == {account_id("Avery")}
    assert movements[0]["reason"] == "case left on the trailer"
    assert movements[1]["reason"] == "council promised a second case"
    assert movements[2]["reason"] is None


# --- PAGE-01: the shared page contract on both Stage 2 reads ---------------------


def test_page_01_a_page_carries_a_cursor_that_continues_the_same_scope(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """PAGE-01: two pages of one history are complete, ordered, and non-overlapping."""
    _seed_movements(inventory_table)
    first = _ok(_movements(page={"limit": 2}))
    assert [item["movementId"] for item in first["items"]] == ["mov-2", "mov-issue"]
    assert first["pageInfo"]["hasNextPage"] is True
    assert first["pageInfo"]["endCursor"]

    second = _ok(_movements(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert [item["movementId"] for item in second["items"]] == ["mov-1", "mov-0"]
    assert second["pageInfo"]["hasNextPage"] is False
    assert second["pageInfo"]["endCursor"] is None

    positions = _ok(_positions(page={"limit": 1}))
    assert len(positions["items"]) == 1 and positions["pageInfo"]["hasNextPage"] is True
    tail = _ok(_positions(page={"limit": 1, "cursor": positions["pageInfo"]["endCursor"]}))
    assert len(tail["items"]) == 1 and tail["pageInfo"]["hasNextPage"] is False


def test_page_01_a_cursor_from_one_scope_is_refused_in_another(world: Dict[str, Any], inventory_table: Any) -> None:
    """PAGE-01: a cursor is a positional claim inside one specific result set."""
    _seed_movements(inventory_table)
    unfiltered = _ok(_movements(page={"limit": 2}))
    cursor = unfiltered["pageInfo"]["endCursor"]

    assert_is_error(_movements(page={"limit": 2, "cursor": cursor}, productId=PRODUCT), "INVALID_INPUT")
    assert_is_error(_movements(page={"limit": 2, "cursor": cursor}, movementType="RECEIPT"), "INVALID_INPUT")
    positions = _ok(_positions(page={"limit": 1}))
    assert_is_error(_movements(page={"limit": 2, "cursor": positions["pageInfo"]["endCursor"]}), "INVALID_INPUT")
    assert_is_error(_movements(page={"limit": 2, "cursor": "bm90LWEtY3Vyc29y"}), "INVALID_INPUT")
    assert_is_error(_movements(page={"limit": 101}), "INVALID_INPUT")


def test_page_01_a_filtered_page_is_not_short(world: Dict[str, Any], inventory_table: Any) -> None:
    """The filter runs before the page window, so a page is never padded by filtered rows."""
    _seed_movements(inventory_table)
    page = _ok(_movements(page={"limit": 2}, movementType="RECEIPT"))
    assert [item["movementId"] for item in page["items"]] == ["mov-2", "mov-1"]
    assert page["pageInfo"]["hasNextPage"] is True
    rest = _ok(_movements(page={"limit": 2, "cursor": page["pageInfo"]["endCursor"]}, movementType="RECEIPT"))
    assert [item["movementId"] for item in rest["items"]] == ["mov-0"]
    assert rest["pageInfo"]["hasNextPage"] is False
