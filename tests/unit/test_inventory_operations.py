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
    ISSUE_STOCK_FIELD,
    MY_SCOUT_CUSTODY_FIELD,
    RECORD_RECEIPT_FIELD,
    RETURN_STOCK_FIELD,
    SCOUT_CUSTODY_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils.dynamodb import get_dynamodb_client
from tests.unit.show_sell_fixtures import (
    PACK_3149_FALL,
    PACK_3149_OLD,
    PROFILES,
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


def _profile(name: str) -> str:
    """One persona's Scout profile id, spelled the way the profiles table spells it."""
    return str(PROFILES[name]["profileId"])


def _scout_campaign(name: str) -> str:
    """The Scout Campaign id that belongs to one persona's profile."""
    return str(PROFILES[name]["campaignId"])


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
    shares_table: Any,
    inventory_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world plus the inventory table these mutations write.

    The shares table comes along for ``myScoutCustody`` (§2.3.3): its participant door
    is a Profile READ/Owner/WRITE check, so the fixture shares Riley-READ-on-Avery and
    Taylor-WRITE-on-Devon are the access the read has to honour and the revoked-access
    case has to be able to remove.
    """
    return seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )


# --- INV-M-01: recordInventoryReceipt (§2.2.1) -----------------------------------


def test_inv_m_01_01_first_receipt_opens_a_balance_and_appends_one_movement(
    world: Dict[str, Any], inventory_table: Any
) -> None:
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


def test_inv_m_02_05_a_stale_read_loses_the_whole_transaction(
    world: Dict[str, Any], inventory_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    position = _ok(
        _adjust(product_id=MISSING_PRODUCT, delta=-4, reason="product dropped, stock counted out", key="adjust-1")
    )

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


def test_inv_m_03_04_a_retry_of_an_on_order_adjustment_applies_once(
    world: Dict[str, Any], inventory_table: Any
) -> None:
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
        (
            RECORD_RECEIPT_FIELD,
            {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantity": 4, **_idem("a")}},
        ),
        (
            ADJUST_INVENTORY_FIELD,
            {
                "input": {
                    "unitCampaignId": CAMPAIGN,
                    "productId": PRODUCT,
                    "quantityDelta": -1,
                    "reason": "miscount",
                    **_idem("b"),
                }
            },
        ),
        (
            ADJUST_COUNCIL_FIELD,
            {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantityDelta": 1, **_idem("c")}},
        ),
        (INVENTORY_POSITIONS_FIELD, {"unitCampaignId": CAMPAIGN}),
        (INVENTORY_MOVEMENTS_FIELD, {"unitCampaignId": CAMPAIGN}),
        (SCOUT_CUSTODY_FIELD, {"unitCampaignId": CAMPAIGN}),
        (
            ISSUE_STOCK_FIELD,
            {
                "input": {
                    "unitCampaignId": CAMPAIGN,
                    "profileId": _profile("Devon"),
                    "campaignId": _scout_campaign("Devon"),
                    "productId": PRODUCT,
                    "quantity": 1,
                    **_idem("d"),
                }
            },
        ),
        (
            RETURN_STOCK_FIELD,
            {
                "input": {
                    "unitCampaignId": CAMPAIGN,
                    "profileId": _profile("Devon"),
                    "campaignId": _scout_campaign("Devon"),
                    "items": [{"productId": PRODUCT, "quantity": 1}],
                    **_idem("e"),
                }
            },
        ),
    ],
    ids=[
        "recordInventoryReceipt",
        "adjustInventory",
        "adjustCouncilOnOrder",
        "inventoryPositions",
        "inventoryMovements",
        "scoutCustodyBalances",
        "issueStockToScout",
        "returnStockFromScout",
    ],
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
    assert_is_error(
        _call(
            ADJUST_INVENTORY_FIELD,
            "Riley",
            mutation={
                "unitCampaignId": CAMPAIGN,
                "productId": PRODUCT,
                "quantityDelta": -1,
                "reason": "wrong unit",
                **_idem("cross"),
            },
        ),
        "NOT_FOUND",
    )
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
    for index, moment in enumerate(
        ("2026-11-07T08:00:00+00:00", "2026-11-07T09:00:00+00:00", "2026-11-08T08:00:00+00:00")
    ):
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
    window = _ok(_movements(dateRange={"startAt": "2026-11-07T09:00:00+00:00", "endAt": "2026-11-07T23:59:59+00:00"}))[
        "items"
    ]
    assert [item["movementId"] for item in window] == ["mov-issue", "mov-1"]
    combined = _ok(
        _movements(productId=PRODUCT, movementType="RECEIPT", dateRange={"startAt": "2026-11-08T00:00:00+00:00"})
    )["items"]
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


# --- Scout custody: helpers (§2.3) -----------------------------------------------

# The Scout the Fall roster holds: Devon, ACTIVE, with the fixture profile and
# Campaign that row names. Emery is the REMOVED roster entry of the old campaign.
DEVON_PROFILE = _profile("Devon")
DEVON_CAMPAIGN = _scout_campaign("Devon")
EMERY_PROFILE = _profile("Emery")
EMERY_CAMPAIGN = _scout_campaign("Emery")
SIBLING_PRODUCT = f"{CATALOG_ID}#prod-2"
# A batch argument the helper can tell apart from "the caller sent null".
_UNSET = object()


def _issue(
    caller: str = "Avery",
    *,
    campaign: str = CAMPAIGN,
    profile_id: str = DEVON_PROFILE,
    scout_campaign: str = DEVON_CAMPAIGN,
    product_id: str = PRODUCT,
    quantity: Any = 3,
    key: str = "issue-1",
    occurred_at: Optional[str] = None,
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "profileId": profile_id,
        "campaignId": scout_campaign,
        "productId": product_id,
        "quantity": quantity,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(ISSUE_STOCK_FIELD, caller, mutation=mutation)


def _return(
    caller: str = "Avery",
    *,
    campaign: str = CAMPAIGN,
    profile_id: str = DEVON_PROFILE,
    scout_campaign: str = DEVON_CAMPAIGN,
    items: Any = _UNSET,
    key: str = "return-1",
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "profileId": profile_id,
        "campaignId": scout_campaign,
        "items": [{"productId": PRODUCT, "quantity": 2}] if items is _UNSET else items,
        **_idem(key),
    }
    return _call(RETURN_STOCK_FIELD, caller, mutation=mutation)


def _custody_reads(**arguments: Any) -> Any:
    return _call(SCOUT_CUSTODY_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN, **arguments})


def _my_custody(caller: str, *, campaign: str = CAMPAIGN, profile_id: str) -> Any:
    return _call(MY_SCOUT_CUSTODY_FIELD, caller, arguments={"unitCampaignId": campaign, "profileId": profile_id})


def _custody_rows(inventory_table: Any, campaign: str = CAMPAIGN) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table, campaign) if row.get("entityType") == "ScoutCustodyBalance"]


def _seed_custody(
    inventory_table: Any,
    *,
    campaign: str = CAMPAIGN,
    product_id: str = PRODUCT,
    profile_id: str = DEVON_PROFILE,
    scout_campaign: Optional[str] = None,
    with_scout_qty: int = 3,
) -> Dict[str, Any]:
    """A Scout already holding stock, written the way an issue would have written it."""
    item = inv.build_scout_custody_balance_item(
        unit_campaign_id=campaign,
        product_id=product_id,
        profile_id=profile_id,
        campaign_id=scout_campaign or _scout_campaign_for(profile_id),
        with_scout_qty=with_scout_qty,
        now_iso=MORNING,
    )
    inventory_table.put_item(Item=item)
    return item


def _scout_campaign_for(profile_id: str) -> str:
    """The Scout Campaign of a fixture profile, from the profile fixtures."""
    for spec in PROFILES.values():
        if spec["profileId"] == profile_id:
            return str(spec["campaignId"])
    raise AssertionError(f"{profile_id} is not a fixture profile")


def _seed_issue(world: Dict[str, Any], inventory_table: Any, **kwargs: Any) -> Dict[str, Any]:
    """Stock received and then issued, so a return test starts from a real custody row."""
    _seed_balance(inventory_table, physical=kwargs.pop("physical", 10), product_id=kwargs.get("product_id", PRODUCT))
    _ok(_issue(quantity=kwargs.pop("quantity", 4), key=kwargs.pop("key", "issue-1"), **kwargs))
    return _custody_rows(inventory_table)[0]


# --- INV-M-04: issueStockToScout (§2.3.1) ----------------------------------------


def test_inv_m_04_01_an_issue_moves_stock_from_the_shelf_to_the_scout_and_nothing_else(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, campaigns_table: Any
) -> None:
    """INV-M-04-01 / CUST-01: physical down, With Scout up, total unit-owned unchanged."""
    _seed_balance(inventory_table, physical=10)
    scout_campaigns_before = campaigns_table.scan()["Items"]

    result = _ok(_issue(quantity=3, occurred_at=MORNING))
    position, custody = result["inventoryPosition"], result["custodyBalance"]

    assert position["kernelPhysicalQty"] == 7
    assert position["withScoutQty"] == 3
    assert position["unassignedKernelQty"] == 7
    assert position["totalUnitOwnedUndeliveredQty"] == 10, "issuing moves stock, it does not create it"
    assert position["version"] == 2, "the seeded balance was version 1"

    assert custody["unitCampaignId"] == CAMPAIGN
    assert custody["productId"] == PRODUCT
    assert custody["profileId"] == DEVON_PROFILE
    assert custody["campaignId"] == DEVON_CAMPAIGN
    assert custody["withScoutQty"] == 3
    assert custody["version"] == 1
    assert custody["createdAt"] == MORNING

    rows = _custody_rows(inventory_table)
    assert len(rows) == 1 and rows[0]["withScoutQty"] == 3
    movements = _movement_rows(inventory_table)
    assert len(movements) == 1
    movement = movements[0]
    assert movement["movementType"] == "SCOUT_ISSUE"
    assert (movement["kernelPhysicalDelta"], movement["withScoutDelta"]) == (-3, 3)
    assert movement["profileId"] == DEVON_PROFILE
    assert movement["inventoryVersion"] == 2
    assert movement["actorAccountId"] == account_id("Avery")
    # AC-03: issuing is a delivery of stock, not a sale. Nothing lands on the money
    # tables, and the inventory partition holds only the three stock row kinds.
    assert {row["entityType"] for row in _rows(inventory_table)} == {
        "InventoryBalance",
        "ScoutCustodyBalance",
        "InventoryMovement",
    }
    assert orders_table.scan()["Items"] == []
    assert campaigns_table.scan()["Items"] == scout_campaigns_before, "an issue touches no Scout Campaign"


def test_inv_m_04_02_a_second_issue_raises_the_same_custody_row(world: Dict[str, Any], inventory_table: Any) -> None:
    """One (campaign, product, Scout) is one custody row (§5.9), never a row per issue."""
    _seed_balance(inventory_table, physical=10)
    _ok(_issue(quantity=3, key="issue-1"))
    custody = _ok(_issue(quantity=2, key="issue-2"))["custodyBalance"]

    assert (custody["withScoutQty"], custody["version"]) == (5, 2)
    assert len(_custody_rows(inventory_table)) == 1
    assert [row["kernelPhysicalDelta"] for row in _movement_rows(inventory_table)] == [-3, -2]
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 5


def test_inv_m_04_03_an_issue_beyond_the_unassigned_stock_is_refused(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-04 / CUST-01: only unassigned stock may go out with a Scout.

    We Owe reservations and OPEN event allocations both hold Kernels the campaign has
    already promised, so an issue may not reach them: the event would arrive short with
    nothing in the audit trail saying why.
    """
    _seed_balance(inventory_table, physical=10, reserved=4)
    inventory_table.put_item(
        Item=inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at="2026-11-07T08:00:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            allocated_qty=3,
            status=inv.ALLOCATION_OPEN,
            now_iso=MORNING,
        )
    )

    assert_is_error(_issue(quantity=4, key="issue-1"), "INVALID_INPUT")
    # Down to the unassigned three exactly is legal, and the event keeps its allocation.
    result = _ok(_issue(quantity=3, key="issue-2"))
    assert result["custodyBalance"]["withScoutQty"] == 3
    assert result["inventoryPosition"]["assignedOpenQty"] == 3
    assert result["inventoryPosition"]["unassignedKernelQty"] == 0
    assert [row["withScoutDelta"] for row in _movement_rows(inventory_table)] == [3]


def test_inv_m_04_04_stock_is_not_issued_to_a_removed_scout(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-04 / AC-47: leaving the roster ends what a Scout may be handed, not what they hold."""
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=OTHER_CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=8, now_iso=MORNING
        )
    )

    assert_is_error(
        _issue(campaign=OTHER_CAMPAIGN, profile_id=EMERY_PROFILE, scout_campaign=EMERY_CAMPAIGN, key="issue-1"),
        "CONFLICT",
    )
    assert _custody_rows(inventory_table, OTHER_CAMPAIGN) == []
    assert _movement_rows(inventory_table, OTHER_CAMPAIGN) == []
    assert _balances(inventory_table, OTHER_CAMPAIGN)[0]["kernelPhysicalQty"] == 8


def test_inv_m_04_05_a_scout_who_never_joined_has_no_identity_to_issue_to(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """A roster row is the eligibility gate: no row is nothing to act on, not a conflict."""
    _seed_balance(inventory_table, physical=10)

    assert_is_error(
        _issue(profile_id=_profile("Blake"), scout_campaign=_scout_campaign("Blake"), key="issue-1"), "NOT_FOUND"
    )
    assert _custody_rows(inventory_table) == [] and _movement_rows(inventory_table) == []


def test_inv_m_04_06_an_identity_that_is_not_the_rosters_is_refused_before_the_write(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-04 "exact Campaign/Profile identity": one Scout is one profile plus its Campaign.

    Naming Devon's profile with another Scout Campaign is not Devon, and an existing
    custody row keeps the Campaign it was created with, so neither a roster mismatch nor
    a custody mismatch may silently re-point stock at a different Scout Campaign.
    """
    _seed_balance(inventory_table, physical=10)
    assert_is_error(_issue(scout_campaign=_scout_campaign("Avery"), key="issue-1"), "CONFLICT")
    assert _custody_rows(inventory_table) == []

    _ok(_issue(quantity=2, key="issue-2"))
    assert_is_error(_issue(scout_campaign=_scout_campaign("Avery"), quantity=1, key="issue-3"), "CONFLICT")
    assert _custody_rows(inventory_table)[0]["campaignId"] == DEVON_CAMPAIGN
    assert _custody_rows(inventory_table)[0]["withScoutQty"] == 2


def test_inv_m_04_07_the_race_for_the_last_kernel_writes_nothing(
    world: Dict[str, Any], inventory_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-M-04 (race): two issues of the last Kernel, one of them, and no half-write.

    The pre-check reads the balance, so both callers can pass it against the same read.
    What decides it is the version pin and the ``kernelPhysicalQty`` floor inside the
    transaction: the loser's whole plan, custody row and audit row included, cancels.
    """
    _seed_balance(inventory_table, physical=1, version=4)
    read = inv.inventory_position_rows(CAMPAIGN, PRODUCT)
    stale = dict(read["balance"][0], version=3, kernelPhysicalQty=1)
    monkeypatch.setattr(
        inv,
        "inventory_position_rows",
        lambda *_a, **_k: {"balance": [stale], "allocations": read["allocations"], "custody": read["custody"]},
    )

    assert_is_error(_issue(quantity=1, key="issue-1"), "CONFLICT")

    balance = _balances(inventory_table)[0]
    assert (balance["version"], balance["kernelPhysicalQty"]) == (4, 1)
    assert _custody_rows(inventory_table) == [], "a lost race may not leave custody behind"
    assert _movement_rows(inventory_table) == [], "a lost race may not leave an audit row behind"


def test_inv_m_04_08_a_retry_of_an_issue_applies_once(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-04 retry: the marker answers with the original result and moves nothing again."""
    _seed_balance(inventory_table, physical=10)
    first = _ok(_issue(quantity=3, key="issue-1"))
    again = _ok(_issue(quantity=3, key="issue-1"))

    assert again == first
    assert len(_custody_rows(inventory_table)) == 1
    assert _custody_rows(inventory_table)[0]["version"] == 1
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 7
    assert len(_movement_rows(inventory_table)) == 1


# --- INV-M-05: returnStockFromScout (§2.3.2) -------------------------------------


def test_inv_m_05_01_a_two_product_return_lands_as_one_atomic_result(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-05-01: two X and three Y come back together, both balances updated once."""
    _seed_balance(inventory_table, physical=6)
    _seed_balance(inventory_table, physical=6, product_id=SIBLING_PRODUCT)
    _ok(_issue(quantity=2, key="issue-x"))
    _ok(_issue(quantity=3, product_id=SIBLING_PRODUCT, key="issue-y"))

    result = _ok(_return(items=[{"productId": PRODUCT, "quantity": 2}, {"productId": SIBLING_PRODUCT, "quantity": 3}]))

    assert [p["productId"] for p in result["inventoryPositions"]] == [PRODUCT, SIBLING_PRODUCT]
    assert [p["kernelPhysicalQty"] for p in result["inventoryPositions"]] == [6, 6]
    assert [p["withScoutQty"] for p in result["inventoryPositions"]] == [0, 0]
    assert [c["withScoutQty"] for c in result["custodyBalances"]] == [0, 0]
    assert [c["version"] for c in result["custodyBalances"]] == [2, 2]

    assert sorted(row["kernelPhysicalQty"] for row in _balances(inventory_table)) == [6, 6]
    assert sorted(row["withScoutQty"] for row in _custody_rows(inventory_table)) == [0, 0]
    returns = [row for row in _movement_rows(inventory_table) if row["movementType"] == "SCOUT_RETURN"]
    assert [(row["productId"], row["kernelPhysicalDelta"], row["withScoutDelta"]) for row in returns] == [
        (PRODUCT, 2, -2),
        (SIBLING_PRODUCT, 3, -3),
    ]
    assert all(row["profileId"] == DEVON_PROFILE for row in returns)


def test_inv_m_05_02_an_over_return_refuses_the_whole_batch(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-05-02: one impossible line cancels the batch; nothing is partly returned."""
    _seed_balance(inventory_table, physical=6)
    _seed_balance(inventory_table, physical=6, product_id=SIBLING_PRODUCT)
    _ok(_issue(quantity=2, key="issue-x"))
    _ok(_issue(quantity=3, product_id=SIBLING_PRODUCT, key="issue-y"))
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    refused = assert_is_error(
        _return(
            items=[{"productId": PRODUCT, "quantity": 2}, {"productId": SIBLING_PRODUCT, "quantity": 4}], key="return-1"
        ),
        "INVALID_INPUT",
    )
    assert "3" in refused["message"]

    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before, "a refused batch writes nothing"


def test_inv_m_05_03_a_plan_beyond_the_write_budget_fails_before_writing(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-05-03: 90 actions commit, 91 are refused before a single write.

    The budget is counted while the plan is staged, so the oversized batch never reaches
    DynamoDB: no balance, custody row, or movement of any of its products has moved.
    """
    products = [f"{CATALOG_ID}#prod-{index}" for index in range(30)]
    for product in products:
        _seed_balance(inventory_table, physical=5, product_id=product)
        _seed_custody(inventory_table, product_id=product, with_scout_qty=2)
    fits = products[:29]
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    result = _ok(_return(items=[{"productId": product, "quantity": 1} for product in fits], key="return-1"))
    assert len(result["inventoryPositions"]) == len(fits)

    assert_is_error(
        _return(items=[{"productId": product, "quantity": 1} for product in products], key="return-2"), "CONFLICT"
    )
    untouched = [row for row in _rows(inventory_table) if row["sk"].startswith(f"PRODUCT#{products[-1]}")]
    assert {row["sk"]: dict(row) for row in untouched} == {
        row["sk"]: dict(row) for row in before.values() if row["sk"].startswith(f"PRODUCT#{products[-1]}")
    }
    assert not any(
        row["movementType"] == "SCOUT_RETURN" and row["productId"] == products[-1]
        for row in _movement_rows(inventory_table)
    )


def test_inv_m_05_04_an_empty_or_repeated_batch_is_refused(world: Dict[str, Any], inventory_table: Any) -> None:
    """A return is a batch of positive quantities over distinct products, or it is refused."""
    _seed_issue(world, inventory_table, physical=10, quantity=4)
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    for items in (None, [], "prod-1", ["prod-1"], [{"productId": PRODUCT}], [{"quantity": 2}]):
        assert_is_error(_return(items=items, key=f"return-{len(str(items))}"), "INVALID_INPUT")
    assert_is_error(_return(items=[{"productId": PRODUCT, "quantity": 0}], key="return-zero"), "INVALID_INPUT")
    assert_is_error(_return(items=[{"productId": PRODUCT, "quantity": -1}], key="return-neg"), "INVALID_INPUT")
    assert_is_error(
        _return(items=[{"productId": PRODUCT, "quantity": 1}, {"productId": PRODUCT, "quantity": 1}], key="return-dup"),
        "INVALID_INPUT",
    )
    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before


def test_inv_m_05_05_stock_comes_back_from_a_scout_who_left_the_roster(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """AC-47 / CUST-06: a REMOVED Scout's custody still has a path back to the Kernel.

    The custody row carries the identity for a return, not the roster: refusing this one
    would strand the stock with no way to count it in again.
    """
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=OTHER_CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=2, now_iso=MORNING
        )
    )
    _seed_custody(inventory_table, campaign=OTHER_CAMPAIGN, profile_id=EMERY_PROFILE, with_scout_qty=3)

    result = _ok(
        _return(
            campaign=OTHER_CAMPAIGN,
            profile_id=EMERY_PROFILE,
            scout_campaign=EMERY_CAMPAIGN,
            items=[{"productId": PRODUCT, "quantity": 3}],
        )
    )

    assert result["inventoryPositions"][0]["kernelPhysicalQty"] == 5
    assert result["custodyBalances"][0]["withScoutQty"] == 0
    assert _custody_rows(inventory_table, OTHER_CAMPAIGN)[0]["version"] == 2


def test_inv_m_05_06_a_return_never_invents_stock_and_never_deletes_the_row(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """CUST-06: the Kernels move between two balances; the custody row keeps its history."""
    _seed_issue(world, inventory_table, physical=10, quantity=4)
    total_before = _ok(_positions())["items"][0]["totalUnitOwnedUndeliveredQty"]

    result = _ok(_return(items=[{"productId": PRODUCT, "quantity": 4}]))

    assert result["inventoryPositions"][0]["totalUnitOwnedUndeliveredQty"] == total_before
    assert len(_custody_rows(inventory_table)) == 1
    assert _custody_rows(inventory_table)[0]["withScoutQty"] == 0, "a returned row is zeroed, not deleted"
    assert_is_error(_return(items=[{"productId": PRODUCT, "quantity": 1}], key="return-2"), "INVALID_INPUT")


def test_inv_m_05_07_a_retry_of_a_return_applies_once(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-05 retry: the committed batch answers identically and moves nothing again."""
    _seed_issue(world, inventory_table, physical=10, quantity=4)
    first = _ok(_return(items=[{"productId": PRODUCT, "quantity": 4}]))
    again = _ok(_return(items=[{"productId": PRODUCT, "quantity": 4}]))

    assert again == first
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 10
    assert _custody_rows(inventory_table)[0]["version"] == 2
    assert len([row for row in _movement_rows(inventory_table) if row["movementType"] == "SCOUT_RETURN"]) == 1


# --- INV-Q-04: scoutCustodyBalances (§2.3.3) -------------------------------------


def _seed_three_custody(inventory_table: Any) -> None:
    """Two Scouts, two products, so an aggregate and a filter can be told apart."""
    for profile_id, product_id, qty in (
        (DEVON_PROFILE, PRODUCT, 4),
        (DEVON_PROFILE, SIBLING_PRODUCT, 1),
        (_profile("Blake"), PRODUCT, 7),
    ):
        _seed_custody(inventory_table, product_id=product_id, profile_id=profile_id, with_scout_qty=qty)


def test_inv_q_04_01_an_admin_sees_per_scout_rows_and_the_total_together(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-Q-04-01 / CUST-02: the board shows With Scout per Scout and in aggregate."""
    _seed_three_custody(inventory_table)

    page = _ok(_custody_reads())
    assert [(item["profileId"], item["productId"], item["withScoutQty"]) for item in page["items"]] == [
        (_profile("Blake"), PRODUCT, 7),
        (DEVON_PROFILE, PRODUCT, 4),
        (DEVON_PROFILE, SIBLING_PRODUCT, 1),
    ]
    assert page["totalWithScoutQty"] == 12

    by_scout = _ok(_custody_reads(profileId=DEVON_PROFILE))
    assert [item["productId"] for item in by_scout["items"]] == [PRODUCT, SIBLING_PRODUCT]
    assert by_scout["totalWithScoutQty"] == 5

    by_product = _ok(_custody_reads(productId=PRODUCT))
    assert [item["profileId"] for item in by_product["items"]] == [_profile("Blake"), DEVON_PROFILE]
    assert by_product["totalWithScoutQty"] == 11

    both = _ok(_custody_reads(profileId=_profile("Blake"), productId=PRODUCT))
    assert [item["withScoutQty"] for item in both["items"]] == [7]
    assert both["totalWithScoutQty"] == 7
    assert _ok(_custody_reads(profileId=_profile("Avery")))["items"] == []


def test_inv_q_04_02_the_total_covers_the_filtered_set_not_the_page(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """PAGE-01 with CUST-02: paging changes the items, never the number the Kernel acts on."""
    _seed_three_custody(inventory_table)

    first = _ok(_custody_reads(page={"limit": 2}))
    assert len(first["items"]) == 2 and first["pageInfo"]["hasNextPage"] is True
    assert first["totalWithScoutQty"] == 12

    rest = _ok(_custody_reads(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert len(rest["items"]) == 1 and rest["pageInfo"]["hasNextPage"] is False
    assert rest["totalWithScoutQty"] == 12
    ids = [item["productId"] + item["profileId"] for item in first["items"] + rest["items"]]
    assert len(set(ids)) == 3

    assert_is_error(_custody_reads(page={"limit": 101}), "INVALID_INPUT")
    assert_is_error(
        _custody_reads(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}, profileId=DEVON_PROFILE),
        "INVALID_INPUT",
    )


def test_inv_q_04_03_the_custody_board_is_unit_admin_only(world: Dict[str, Any], inventory_table: Any) -> None:
    """AUTH-U on the aggregate read: a Scout, another Unit's admin, and no session are denied."""
    _seed_three_custody(inventory_table)

    assert_is_error(_call(SCOUT_CUSTODY_FIELD, None, arguments={"unitCampaignId": CAMPAIGN}), "UNAUTHORIZED")
    for caller in ("Devon", "Blake", "Riley", "Taylor"):
        assert_is_error(_call(SCOUT_CUSTODY_FIELD, caller, arguments={"unitCampaignId": CAMPAIGN}), "NOT_FOUND")
    # The old campaign of the same Unit is readable, and reads empty: tenancy is the
    # caller's Unit, not one campaign id.
    assert _ok(_custody_reads(unitCampaignId=OTHER_CAMPAIGN))["items"] == []
    assert_is_error(_custody_reads(unitCampaignId="uc-does-not-exist"), "NOT_FOUND")


def test_inv_q_04_04_a_custody_row_carries_no_actor_reason_or_movement_field(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The custody shape is stock, not audit: who issued it lives on the movement trail."""
    _seed_three_custody(inventory_table)

    item = _ok(_custody_reads())["items"][0]
    assert set(item) == {
        "unitCampaignId",
        "productId",
        "profileId",
        "campaignId",
        "withScoutQty",
        "version",
        "createdAt",
        "updatedAt",
    }


# --- INV-Q-05: myScoutCustody (§2.3.3) -------------------------------------------


def test_inv_q_05_01_a_share_holder_reads_the_scout_they_may_see(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-Q-05-01: Riley reads Avery's custody on a READ share, Taylor Devon's on WRITE."""
    _seed_custody(inventory_table, profile_id=_profile("Avery"), with_scout_qty=2)
    _seed_custody(inventory_table, profile_id=_profile("Avery"), product_id=SIBLING_PRODUCT, with_scout_qty=1)
    _seed_custody(inventory_table, profile_id=DEVON_PROFILE, with_scout_qty=5)

    riley = _ok(_my_custody("Riley", profile_id=_profile("Avery")))
    assert [item["productId"] for item in riley] == [PRODUCT, SIBLING_PRODUCT]
    assert [item["withScoutQty"] for item in riley] == [2, 1]
    assert {item["profileId"] for item in riley} == {_profile("Avery")}
    assert all(item["unitCampaignId"] == CAMPAIGN for item in riley)

    taylor = _ok(_my_custody("Taylor", profile_id=DEVON_PROFILE))
    assert [item["withScoutQty"] for item in taylor] == [5]
    owner = _ok(_my_custody("Devon", profile_id=DEVON_PROFILE))
    assert owner == taylor


def test_inv_q_05_02_a_share_holder_cannot_read_another_scout(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-Q-05-01 / AUTH-P-04: Riley holds READ on Avery, which is not READ on Blake."""
    _seed_custody(inventory_table, profile_id=_profile("Avery"), with_scout_qty=2)
    _seed_custody(inventory_table, profile_id=_profile("Blake"), with_scout_qty=7)

    refused = assert_is_error(_my_custody("Riley", profile_id=_profile("Blake")), "FORBIDDEN")
    assert "READ" in refused["message"]
    assert _ok(_my_custody("Riley", profile_id=_profile("Avery")))[0]["withScoutQty"] == 2

    # A Scout reading their own custody is the owner door; a Scout with no share at all
    # is refused for someone else's, and an empty result is not a leak either way.
    assert _ok(_my_custody("Devon", profile_id=DEVON_PROFILE)) == []
    assert_is_error(_my_custody("Devon", profile_id=_profile("Blake")), "FORBIDDEN")


def test_inv_q_05_03_a_unit_admin_reads_only_their_own_campaigns_scouts(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-Q-05-02: the admin door is the campaign's Unit, and it does not travel."""
    _seed_custody(inventory_table, profile_id=_profile("Blake"), with_scout_qty=7)
    _seed_custody(inventory_table, campaign=OTHER_CAMPAIGN, profile_id=EMERY_PROFILE, with_scout_qty=3)

    assert [item["withScoutQty"] for item in _ok(_my_custody("Avery", profile_id=_profile("Blake")))] == [7]
    assert [
        item["withScoutQty"] for item in _ok(_my_custody("Avery", campaign=OTHER_CAMPAIGN, profile_id=EMERY_PROFILE))
    ] == [3]

    # Riley administers TROOP 7150, which is not this Pack's tenant, and holds no share
    # on Devon's profile: the admin grant does not open another Unit's custody.
    assert_is_error(_my_custody("Riley", profile_id=DEVON_PROFILE), "FORBIDDEN")
    assert_is_error(
        _call(MY_SCOUT_CUSTODY_FIELD, None, arguments={"unitCampaignId": CAMPAIGN, "profileId": DEVON_PROFILE}),
        "UNAUTHORIZED",
    )
    assert_is_error(_my_custody("Avery", campaign="uc-does-not-exist", profile_id=DEVON_PROFILE), "NOT_FOUND")


def test_inv_q_05_04_a_revoked_share_stops_the_read_the_day_it_is_revoked(
    world: Dict[str, Any], inventory_table: Any, shares_table: Any
) -> None:
    """INV-Q-05 revoked access: the share row is the access, so removing it closes the door."""
    _seed_custody(inventory_table, profile_id=_profile("Avery"), with_scout_qty=2)
    assert _ok(_my_custody("Riley", profile_id=_profile("Avery")))[0]["withScoutQty"] == 2

    share = next(row for row in world["shares"] if row["profileId"] == _profile("Avery"))
    shares_table.delete_item(Key={"profileId": share["profileId"], "targetAccountId": share["targetAccountId"]})

    assert_is_error(_my_custody("Riley", profile_id=_profile("Avery")), "FORBIDDEN")


def test_inv_q_05_05_a_participant_read_reconciles_to_the_stored_rows(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The read is the rows: same quantities, one Scout only, and no audit fields."""
    _seed_three_custody(inventory_table)
    _seed_custody(inventory_table, profile_id=_profile("Avery"), with_scout_qty=2)

    items = _ok(_my_custody("Riley", profile_id=_profile("Avery")))
    stored = [row for row in _custody_rows(inventory_table) if row["profileId"] == _profile("Avery")]

    assert [(item["productId"], item["withScoutQty"], item["version"]) for item in items] == [
        (str(row["productId"]), row["withScoutQty"], row["version"]) for row in stored
    ]
    assert sum(item["withScoutQty"] for item in items) == 2
    assert {item["profileId"] for item in items} == {_profile("Avery")}
    for item in items:
        assert set(item) == {
            "unitCampaignId",
            "productId",
            "profileId",
            "campaignId",
            "withScoutQty",
            "version",
            "createdAt",
            "updatedAt",
        }


# --- the identity and empty-custody edges, and a marker that lost its payload ----


def _marker_rows(inventory_table: Any) -> List[Dict[str, Any]]:
    """Idempotency markers are keyed by actor and operation, not by campaign."""
    return [row for row in inventory_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")]


def _strip_marker_payload(inventory_table: Any) -> None:
    """Drop the stored result of the committed return's marker.

    That is the shape of a crash between the commit and the payload back-fill (§8.9).
    The retry then has to be answered from the rows the return wrote, which is only
    possible because a return never deletes a custody row.
    """
    markers = [row for row in _marker_rows(inventory_table) if "returnStockFromScout" in str(row["pk"])]
    assert len(markers) == 1, markers
    get_dynamodb_client().update_item(
        TableName=inventory_table.table_name,
        Key={"pk": {"S": markers[0]["pk"]}, "sk": {"S": markers[0]["sk"]}},
        UpdateExpression="REMOVE resultPayload",
    )


def test_a_return_whose_marker_lost_its_payload_is_answered_from_the_rows(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """§8.9 with §2.3.2: the loader rebuilds the batch answer, and moves nothing again."""
    _seed_balance(inventory_table, physical=6)
    _seed_balance(inventory_table, physical=6, product_id=SIBLING_PRODUCT)
    _ok(_issue(quantity=2, key="issue-x"))
    _ok(_issue(quantity=3, product_id=SIBLING_PRODUCT, key="issue-y"))

    items = [{"productId": PRODUCT, "quantity": 2}, {"productId": SIBLING_PRODUCT, "quantity": 3}]
    first = _ok(_return(items=items, key="return-1"))
    _strip_marker_payload(inventory_table)

    again = _ok(_return(items=items, key="return-1"))
    assert [c["profileId"] for c in again["custodyBalances"]] == [c["profileId"] for c in first["custodyBalances"]]
    assert [p["productId"] for p in again["inventoryPositions"]] == [PRODUCT, SIBLING_PRODUCT]
    assert [p["kernelPhysicalQty"] for p in again["inventoryPositions"]] == [6, 6]
    assert [c["withScoutQty"] for c in again["custodyBalances"]] == [0, 0]
    # One SCOUT_RETURN movement per product of the committed batch, and no second batch.
    assert len([row for row in _movement_rows(inventory_table) if row["movementType"] == "SCOUT_RETURN"]) == 2
    assert [c["version"] for c in again["custodyBalances"]] == [2, 2]
    assert _balances(inventory_table)[0]["kernelPhysicalQty"] == 6, "the fallback may not re-run the write"


def test_stock_is_not_issued_onto_custody_held_under_another_scout_campaign(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """INV-M-04 identity check on the custody row, not only the roster.

    The roster says Devon belongs to Devon's Campaign, so the request is legal on its
    face; the custody row that already exists was created under another Scout's
    Campaign. Adding to it would silently move stock into a different Scout's sales
    identity, so the issue is refused and the row keeps the Campaign it was made with.
    """
    _seed_balance(inventory_table, physical=10)
    _seed_custody(inventory_table, scout_campaign=_scout_campaign("Avery"), with_scout_qty=2)
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    assert_is_error(_issue(quantity=1, key="issue-1"), "CONFLICT")
    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before


def test_a_product_the_scout_never_held_has_nothing_to_return(world: Dict[str, Any], inventory_table: Any) -> None:
    """INV-M-05: a return names stock the Scout actually holds, product by product."""
    _seed_issue(world, inventory_table, physical=10, quantity=4)
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    refused = assert_is_error(
        _return(
            items=[{"productId": PRODUCT, "quantity": 1}, {"productId": SIBLING_PRODUCT, "quantity": 1}], key="return-1"
        ),
        "INVALID_INPUT",
    )
    assert "holds none" in refused["message"]
    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before


def test_a_custody_row_under_another_scout_campaign_never_returns(world: Dict[str, Any], inventory_table: Any) -> None:
    """§2.3.2 identity: the return's Campaign is the custody row's own.

    Devon's roster is ACTIVE and the request names that Campaign, so what refuses this is
    the custody row itself: it was issued under another Scout's Campaign, and returning
    it under Devon's would credit Kernel stock for sales that other Scout's Campaign
    never made.
    """
    _seed_issue(world, inventory_table, physical=10, quantity=4)
    _seed_custody(inventory_table, scout_campaign=_scout_campaign("Avery"), with_scout_qty=1)
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    refused = assert_is_error(_return(items=[{"productId": PRODUCT, "quantity": 1}], key="return-1"), "CONFLICT")
    assert "different Scout Campaign" in refused["message"]
    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before


def test_a_return_naming_a_campaign_the_roster_disagrees_with_is_refused(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The roster is checked first, so a mismatched identity is refused even before custody."""
    _seed_custody(inventory_table, scout_campaign=_scout_campaign("Avery"), with_scout_qty=2)
    before = {row["sk"]: dict(row) for row in _rows(inventory_table)}

    assert_is_error(_return(scout_campaign=_scout_campaign("Avery"), key="return-1"), "CONFLICT")
    assert {row["sk"]: dict(row) for row in _rows(inventory_table)} == before


def test_two_scouts_holding_one_product_have_one_custody_row_each(world: Dict[str, Any], inventory_table: Any) -> None:
    """§5.9: custody is per (campaign, product, Scout), so one Scout's row is never another's.

    The issue reads the product's custody rows to find the one it may update; a Scout
    who holds none of them is a new row, not an addition to whoever holds some.
    """
    _seed_balance(inventory_table, physical=10)
    _seed_custody(
        inventory_table, profile_id=_profile("Blake"), scout_campaign=_scout_campaign("Blake"), with_scout_qty=3
    )

    result = _ok(_issue(quantity=2, key="issue-devon"))
    assert result["custodyBalance"]["profileId"] == DEVON_PROFILE
    assert result["custodyBalance"]["withScoutQty"] == 2
    assert result["inventoryPosition"]["withScoutQty"] == 5
    assert result["inventoryPosition"]["kernelPhysicalQty"] == 8

    rows = _custody_rows(inventory_table)
    assert [(row["profileId"], row["withScoutQty"]) for row in rows] == [
        (_profile("Blake"), 3),
        (DEVON_PROFILE, 2),
    ]
