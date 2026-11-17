"""Leaf 2.4 — individual Order fulfillment, end to end through the handler.

Resolver-level tests for §2.4.3, §2.4.4 and §2.4.5 (``INV-M-06``, ``INV-M-07``,
``INV-Q-03``, ``AUTH-U``, ``PAGE-01``). Every case goes through
``handle_unit_operation`` against moto, so it exercises the real originating-Unit
authorization, the real idempotency marker, the real conditional ``TransactWriteItems``
over three tables, and the real payload the browser would receive — the layer where
"this line is fulfilled by two and the Kernel holds two fewer" is either true or not.

The tables a fulfillment must NOT touch are asserted as explicitly as the ones it must:
an external-Council fulfillment that also opened an inventory balance would put stock
movement in the count that nothing moved (AC-05), and a reversal that restored Kernel
stock for a Scout-custody fulfillment would move a Kernel nobody lent out (AC-06).

The fixture world is the Stage 1 personas plus the two tables §2.4 adds: the ``orders``
row being fulfilled and the append-only ``order_fulfillments`` partition written beside
it. Orders are keyed ``{campaignId, orderId}`` and the id carries the campaign, so the
fixture spells it the way ``src/utils/order_keys.py`` mints it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    FULFILL_LINE_FIELD,
    ORDER_FULFILLMENTS_FIELD,
    RECORD_RECEIPT_FIELD,
    REVERSE_FULFILLMENT_FIELD,
    handle_unit_operation,
)
from src.utils import order_fulfillment_models as ful
from src.utils.dynamodb import get_dynamodb_client
from tests.unit.show_sell_fixtures import (
    FIXTURE_PRODUCT_ID,
    PACK_3149,
    PACK_3149_FALL,
    PACK_3149_OLD,
    PROFILES,
    account_id,
    assert_is_error,
    order_line_item,
    seed_show_sell_fixtures,
    sold_order_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
ORIGIN_OTHER = PACK_3149_OLD
PRODUCT = FIXTURE_PRODUCT_ID
LINE = "line-fixture-1"
ORDER = sold_order_item("Devon", unit_id=PACK_3149, unit_campaign_id=CAMPAIGN)
ORDER_ID = str(ORDER["orderId"])
# An Order whose sale happened while the Scout campaign was linked to the spring Unit
# Campaign: §5.19 freezes that scope, so its stock comes from spring and not from the
# campaign the caller may be looking at today.
PAST_ORDER = sold_order_item("Emery", suffix="order-spring", unit_id=PACK_3149, unit_campaign_id=ORIGIN_OTHER)
PAST_ORDER_ID = str(PAST_ORDER["orderId"])
# An independent sale: no Unit scope, so no Unit Admin exists for it (§2.4 refuses it).
FREE_ORDER = sold_order_item("Riley", suffix="order-independent")
FREE_ORDER_ID = str(FREE_ORDER["orderId"])
DEVON_PROFILE = str(PROFILES["Devon"]["profileId"])


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


def _receipt(*, quantity: int = 10, campaign: str = CAMPAIGN, key: str = "receipt-1") -> Any:
    return _call(
        RECORD_RECEIPT_FIELD,
        "Avery",
        mutation={"unitCampaignId": campaign, "productId": PRODUCT, "quantity": quantity, **_idem(key)},
    )


def _fulfill(
    caller: Optional[str] = "Avery",
    *,
    order_id: str = ORDER_ID,
    line_item_id: Any = LINE,
    quantity: Any = 2,
    source: Any = "KERNEL_STOCK",
    version: Any = 0,
    key: str = "fulfill-1",
) -> Any:
    return _call(
        FULFILL_LINE_FIELD,
        caller,
        mutation={
            "orderId": order_id,
            "lineItemId": line_item_id,
            "quantity": quantity,
            "source": source,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def _reverse(
    caller: Optional[str] = "Avery",
    *,
    order_id: str = ORDER_ID,
    fulfillment_id: Any,
    version: Any = 1,
    key: str = "reverse-1",
) -> Any:
    return _call(
        REVERSE_FULFILLMENT_FIELD,
        caller,
        mutation={
            "orderId": order_id,
            "fulfillmentId": fulfillment_id,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def _audit(
    caller: Optional[str] = "Avery",
    *,
    order_id: Any = ORDER_ID,
    page: Optional[Dict[str, Any]] = None,
) -> Any:
    arguments: Dict[str, Any] = {"orderId": order_id}
    if page is not None:
        arguments["page"] = page
    return _call(ORDER_FULFILLMENTS_FIELD, caller, arguments=arguments)


def _stored_order(orders_table: Any, order_id: str = ORDER_ID) -> Dict[str, Any]:
    """The Order row as DynamoDB holds it, so an assertion is about the stored row."""
    campaign_id = str(ful.order_row_key(order_id)["campaignId"])
    item = orders_table.get_item(Key={"campaignId": campaign_id, "orderId": order_id}).get("Item")
    assert item, f"no Order row for {order_id}"
    return dict(item)


def _stored_line(orders_table: Any, order_id: str = ORDER_ID, line_item_id: str = LINE) -> Dict[str, Any]:
    """One stored line of an Order, found by its identity rather than by position."""
    for line in _stored_order(orders_table, order_id)["lineItems"]:
        if line.get("lineItemId") == line_item_id:
            return dict(line)
    raise AssertionError(f"no line {line_item_id} on {order_id}")


def _fulfillment_rows(fulfillments_table: Any, order_id: str = ORDER_ID) -> List[Dict[str, Any]]:
    """The Order's fulfillment history, markers excluded, in the order DynamoDB returns it.

    Filtered on ``entityType`` rather than on a key prefix: that attribute is what tells
    an idempotency marker from a fulfillment record on a table that carries both, and the
    assertion is worth pinning too.
    """
    rows = fulfillments_table.scan().get("Items", [])
    return [dict(row) for row in rows if row.get("entityType") == "OrderFulfillment" and row.get("pk") == order_id]


def _movement_rows(inventory_table: Any) -> List[Dict[str, Any]]:
    """Every inventory movement row this campaign has."""
    return [
        dict(row) for row in inventory_table.scan().get("Items", []) if row.get("entityType") == "InventoryMovement"
    ]


def _balance_row(inventory_table: Any, campaign: str = CAMPAIGN) -> Optional[Dict[str, Any]]:
    for row in inventory_table.scan().get("Items", []):
        if row.get("entityType") == "InventoryBalance" and row.get("unitCampaignId") == campaign:
            return dict(row)
    return None


def _custody_row(inventory_table: Any, *, profile_id: str = DEVON_PROFILE) -> Optional[Dict[str, Any]]:
    for row in inventory_table.scan().get("Items", []):
        if row.get("entityType") == "ScoutCustodyBalance" and row.get("profileId") == profile_id:
            return dict(row)
    return None


def _strip_marker_payload(fulfillments_table: Any, operation: str) -> None:
    """Drop the stored result of a committed mutation's marker.

    That is the shape of a crash between the commit and the payload back-fill (§8.9):
    the retry has to be answered from the rows the mutation wrote, which is why the
    result id rides the marker insert rather than only the back-fill.
    """
    markers = [
        row
        for row in fulfillments_table.scan()["Items"]
        if str(row["pk"]).startswith("IDEM#") and operation in str(row["pk"])
    ]
    assert len(markers) == 1, markers
    get_dynamodb_client().update_item(
        TableName=fulfillments_table.table_name,
        Key={"pk": {"S": markers[0]["pk"]}, "sk": {"S": markers[0]["sk"]}},
        UpdateExpression="REMOVE resultPayload",
    )


def _sale_fulfilled_line(
    orders_table: Any, order: Dict[str, Any], *, quantity: int, version: int, line_item_id: str = LINE
) -> None:
    """Store the line and version the sale path leaves behind with its fulfillment.

    A §2.4.2 sale that consumed Scout custody moves the line's ``fulfilledQuantity`` and
    the Order's ``fulfillmentVersion`` in the same transaction as the fulfillment row, so
    a test that reverses one has to start from that state. Planting only the fulfillment
    row would exercise a row shape no write path produces, and the reversal's own demand
    guard would refuse it for the wrong reason.
    """
    stored = _stored_order(orders_table, str(order["orderId"]))
    orders_table.update_item(
        Key={"campaignId": order["campaignId"], "orderId": order["orderId"]},
        UpdateExpression="SET lineItems = :lines, fulfillmentVersion = :version",
        ExpressionAttributeValues={
            ":lines": ful.apply_line_fulfillment(stored, line_item_id, quantity),
            ":version": version,
        },
    )


def _plant_fulfillment(
    fulfillments_table: Any,
    *,
    order: Dict[str, Any],
    fulfillment_id: str,
    source: str,
    quantity: int,
    line_item_id: str = LINE,
    product_id: str = PRODUCT,
    unit_campaign_id: Optional[str] = None,
    created_at: str = "2026-11-07T08:00:00+00:00",
    inventory_movement_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one fulfillment record directly, for the cases a fresh fulfill cannot make.

    A Scout-custody fulfillment is written by the sale path (§2.4.2), not by this
    mutation, so a §2.4.4 test that reverses one has to plant the row it is reversing —
    built by the same builder the write path uses, so the key grammar under test is the
    real one.
    """
    if source in ful.SOURCE_MOVES_STOCK and inventory_movement_id is None:
        # The builder refuses a stock fulfillment that names no movement, and it is
        # right to: the sale path that consumed Kernel or custody stock wrote one.
        inventory_movement_id = f"mov-planted-{fulfillment_id}"
    item = ful.build_fulfillment_item(
        fulfillment_id=fulfillment_id,
        order_id=order["orderId"],
        campaign_id=order["campaignId"],
        profile_id=order["profileId"],
        unit_id=order.get("unitId"),
        unit_campaign_id=unit_campaign_id if unit_campaign_id is not None else order.get("unitCampaignId"),
        line_item_id=line_item_id,
        product_id=product_id,
        record_type=ful.RECORD_TYPE_FULFILL,
        quantity=quantity,
        source=source,
        actor_account_id=account_id("Avery"),
        created_at=created_at,
        inventory_movement_id=inventory_movement_id,
    )
    fulfillments_table.put_item(Item=item)
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
    orders_table: Any,
    order_fulfillments_table: Any,
) -> Dict[str, Any]:
    """The persona world plus the three tables §2.4 reads and writes.

    ``shares`` comes along because the participant door of the Stage 2 reads is a Profile
    check, and the §2.4.5 audit has to be provable against a Scout who holds a share and
    still sees nothing of the audit (§10.2).
    """
    seeded = seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    orders_table.put_item(Item=ORDER)
    orders_table.put_item(Item=PAST_ORDER)
    orders_table.put_item(Item=FREE_ORDER)
    return seeded


# --- INV-M-06: fulfillIndividualOrderLine (§2.4.3) --------------------------------


def test_inv_m_06_01_a_kernel_stock_fulfillment_moves_line_stock_record_and_marker(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-01: part of an unfulfilled line from unassigned Kernel stock, each change once."""
    _ok(_receipt(quantity=10))

    result = _ok(_fulfill(quantity=2))

    assert result["order"]["orderId"] == ORDER_ID
    assert result["order"]["fulfillmentVersion"] == 1
    assert result["order"]["lineItems"][0]["fulfilledQuantity"] == 2
    assert result["order"]["lineItems"][0]["lineItemId"] == LINE
    assert result["order"]["unitId"] == PACK_3149
    assert result["order"]["unitCampaignId"] == CAMPAIGN
    assert "fulfillments" not in result["order"], "the participant field is its own resolver's answer"
    assert result["inventoryPosition"]["kernelPhysicalQty"] == 8
    assert result["inventoryPosition"]["version"] == 2

    record = result["fulfillment"]
    assert record["recordType"] == "FULFILL"
    assert record["source"] == "KERNEL_STOCK"
    assert record["quantity"] == 2
    assert record["orderId"] == ORDER_ID
    assert record["lineItemId"] == LINE
    assert record["productId"] == PRODUCT
    assert record["profileId"] == DEVON_PROFILE
    assert record["unitId"] == PACK_3149
    assert record["unitCampaignId"] == CAMPAIGN
    assert record["actorAccountId"] == account_id("Avery")
    assert record["reversalOfFulfillmentId"] is None

    stored = _stored_order(orders_table)
    assert int(stored["fulfillmentVersion"]) == 1
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 2
    assert stored["updatedAt"] != ORDER["updatedAt"], "a fulfilled line leaves the Order's updatedAt stale"
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 8

    rows = _fulfillment_rows(order_fulfillments_table)
    assert len(rows) == 1
    assert rows[0]["sk"] == ful.fulfillment_sort_key(rows[0]["createdAt"], rows[0]["fulfillmentId"])

    movements = _movement_rows(inventory_table)
    assert len(movements) == 2, "a fulfillment appends exactly one movement beside the receipt"
    movement = [row for row in movements if row["movementType"] == "INDIVIDUAL_FULFILL"][0]
    assert movement["kernelPhysicalDelta"] == -2
    assert movement["orderId"] == ORDER_ID
    assert movement["fulfillmentId"] == record["fulfillmentId"]
    assert movement["inventoryVersion"] == 2
    assert record["inventoryMovementId"] == movement["movementId"]


def test_inv_m_06_02_two_partial_fulfillments_of_one_line_cannot_double_spend_it(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-01, continued: the second attempt is pinned to the version the first wrote."""
    _ok(_receipt(quantity=10))
    first = _ok(_fulfill(quantity=3, key="fulfill-a"))
    assert first["order"]["fulfillmentVersion"] == 1

    second = _ok(_fulfill(quantity=1, version=first["order"]["fulfillmentVersion"], key="fulfill-b"))
    assert second["order"]["fulfillmentVersion"] == 2
    assert int(_stored_line(orders_table, ORDER_ID)["fulfilledQuantity"]) == 4
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 6
    assert len(_fulfillment_rows(order_fulfillments_table)) == 2


def test_inv_m_06_03_external_council_fulfillment_never_opens_an_inventory_row(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-02: demand is met from outside the Unit, and the stock count is untouched."""
    result = _ok(_fulfill(quantity=4, source="EXTERNAL_COUNCIL"))

    assert result["order"]["fulfillmentVersion"] == 1
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 4
    assert "inventoryPosition" not in result, "no Kernel position changed, so none is answered"
    assert _balance_row(inventory_table) is None
    assert _movement_rows(inventory_table) == []

    record = result["fulfillment"]
    assert record["source"] == "EXTERNAL_COUNCIL"
    assert record["inventoryMovementId"] is None
    rows = _fulfillment_rows(order_fulfillments_table)
    assert len(rows) == 1
    # §5.19: the version moves even though no inventory version did.
    assert int(_stored_order(orders_table)["fulfillmentVersion"]) == 1


def test_inv_m_06_04_excess_quantity_is_refused_before_anything_is_written(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-03: more than the line owes is INVALID_INPUT, with no marker and no partial fill."""
    _ok(_receipt(quantity=10))
    refused = assert_is_error(_fulfill(quantity=5), "INVALID_INPUT")

    assert "unfulfilled" in refused["message"]
    assert _fulfillment_rows(order_fulfillments_table) == []
    assert [row for row in _movement_rows(inventory_table) if row["movementType"] == "INDIVIDUAL_FULFILL"] == []
    assert int(_stored_order(orders_table)["fulfillmentVersion"]) == 0
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 10


def test_inv_m_06_05_an_unknown_line_and_a_bad_quantity_are_the_callers_to_fix(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """INV-M-06-03: the request-level refusals name what the caller has to change."""
    assert_is_error(_fulfill(line_item_id="line-nobody-minted"), "INVALID_INPUT")
    assert_is_error(_fulfill(quantity=0), "INVALID_INPUT")
    assert_is_error(_fulfill(quantity=-1), "INVALID_INPUT")
    assert_is_error(_fulfill(quantity="two"), "INVALID_INPUT")
    assert_is_error(_fulfill(source="NOT_A_SOURCE"), "INVALID_INPUT")
    assert_is_error(_fulfill(version=None), "INVALID_INPUT")
    assert_is_error(_fulfill(version=-1), "INVALID_INPUT")
    assert_is_error(_fulfill(version="zero"), "INVALID_INPUT")
    assert_is_error(_fulfill(version=True), "INVALID_INPUT")
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_m_06_06_scout_custody_is_not_a_choice_this_mutation_gets_to_make(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-03, wrong source scope: the custody a sale already consumed is not re-consumed here."""
    refused = assert_is_error(_fulfill(source="SCOUT_CUSTODY"), "INVALID_INPUT")

    assert "SCOUT_CUSTODY" in refused["message"]
    assert _fulfillment_rows(order_fulfillments_table) == []
    assert _movement_rows(inventory_table) == []


def test_inv_m_06_07_a_stale_version_conflicts_instead_of_over_fulfilling(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-03, stale race: two screens read version 0, and only one fulfillment lands."""
    _ok(_receipt(quantity=10))
    _ok(_fulfill(quantity=1, key="screen-one"))

    # Still legal on quantity — three of four lines remain unfulfilled — so only the
    # version this screen never saw can refuse it.
    refused = assert_is_error(_fulfill(quantity=2, version=0, key="screen-two"), "CONFLICT")

    assert refused["errorCode"] == "CONFLICT"
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 1
    assert len(_fulfillment_rows(order_fulfillments_table)) == 1
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 9


def test_inv_m_06_08_a_retry_with_the_same_key_replays_and_writes_nothing_twice(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """IDEM on §2.4.3: the caller gets its original answer, not a second fulfillment."""
    _ok(_receipt(quantity=10))
    first = _ok(_fulfill(quantity=2, key="retry-me"))

    again = _ok(_fulfill(quantity=2, key="retry-me"))

    assert again == first
    assert len(_fulfillment_rows(order_fulfillments_table)) == 1
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 2
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 8

    changed = assert_is_error(_fulfill(quantity=3, key="retry-me"), "INVALID_INPUT")
    assert "idempotencyKey" in changed["message"] or "fingerprint" in changed["message"]


def test_inv_m_06_09_kernel_stock_is_limited_to_the_stock_no_event_has_claimed(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-03, source scope: CUST-01's ceiling applies to a fulfillment as it does to an issue."""
    _ok(_receipt(quantity=10))
    _ok(
        _call(
            "issueStockToScout",
            "Avery",
            mutation={
                "unitCampaignId": CAMPAIGN,
                "campaignId": str(PROFILES["Devon"]["campaignId"]),
                "profileId": DEVON_PROFILE,
                "productId": PRODUCT,
                "quantity": 7,
                **_idem("issue-before-fulfill"),
            },
        )
    )

    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 3
    refused = assert_is_error(_fulfill(quantity=4), "INVALID_INPUT")

    assert "unassigned" in refused["message"]
    assert _fulfillment_rows(order_fulfillments_table) == []
    _ok(_fulfill(quantity=3, key="fulfill-the-rest"))


def test_inv_m_06_10_kernel_stock_without_a_balance_row_is_refused_external_stock_is_not(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-02: a product nothing has received has no Kernel stock, and external supply still works."""
    assert_is_error(_fulfill(quantity=1, source="KERNEL_STOCK"), "INVALID_INPUT")
    _ok(_fulfill(quantity=1, source="EXTERNAL_COUNCIL", key="external-no-balance"))
    assert _balance_row(inventory_table) is None


def test_inv_m_06_11_the_stock_comes_from_the_campaign_the_order_originate_in(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-06-03, wrong source scope: the balance drawn is the Order's own, not the caller's."""
    _ok(_receipt(quantity=10, campaign=CAMPAIGN, key="receipt-fall"))
    _ok(_receipt(quantity=6, campaign=ORIGIN_OTHER, key="receipt-spring"))

    result = _ok(_fulfill(order_id=PAST_ORDER_ID, quantity=4))

    assert result["inventoryPosition"]["unitCampaignId"] == ORIGIN_OTHER
    assert _balance_row(inventory_table, campaign=ORIGIN_OTHER)["kernelPhysicalQty"] == 2
    assert _balance_row(inventory_table, campaign=CAMPAIGN)["kernelPhysicalQty"] == 10
    rows = _fulfillment_rows(order_fulfillments_table, PAST_ORDER_ID)
    assert rows[0]["unitCampaignId"] == ORIGIN_OTHER


def test_inv_m_06_12_an_independent_order_has_no_unit_admin_to_ask(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """AUTH-U on §2.4.3: the Order exists and Avery admins two Units, and neither is this Order's."""
    refused = assert_is_error(_fulfill(order_id=FREE_ORDER_ID), "FORBIDDEN")

    assert "no originating Unit" in refused["message"]
    assert _fulfillment_rows(order_fulfillments_table, FREE_ORDER_ID) == []


def test_inv_m_06_13_a_scout_and_a_foreign_admin_are_both_refused(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """AUTH-U: tenancy is the Order's own unitId, never a Unit the caller claims."""
    # Devon owns this Order's profile and is not an admin of the Unit that sold the
    # stock. The refusal reads exactly like a Unit that was never there: a denial is not
    # allowed to confirm that a Unit exists (§1.1), so every caller without a grant on the
    # Order's originating Unit gets this same answer.
    assert_is_error(_fulfill(caller="Devon"), "NOT_FOUND")
    # Riley admins TROOP 7150 only.
    assert_is_error(_fulfill(caller="Riley"), "NOT_FOUND")
    # Blake created PACK 3149 and was removed as admin of it.
    assert_is_error(_fulfill(caller="Blake"), "NOT_FOUND")
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_m_06_14_an_unparsable_order_id_and_a_missing_order_are_told_apart(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """AUTH-U/NOT_FOUND: a legacy id addresses nothing here, and a real-looking miss is a miss."""
    refused = assert_is_error(_fulfill(order_id="ORDER#only-a-uuid"), "INVALID_INPUT")
    assert "campaign" in refused["message"]
    assert_is_error(_fulfill(order_id="ORDER#camp-devon-fixture#no-such-order"), "NOT_FOUND")
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_m_06_15_a_line_that_carries_no_product_cannot_be_fulfilled(
    world: Dict[str, Any], orders_table: Any, order_fulfillments_table: Any
) -> None:
    """A corrupt line is refused, not answered with a movement against a product named ``None``."""
    broken = order_line_item()
    del broken["productId"]
    orders_table.update_item(
        Key={"campaignId": ORDER["campaignId"], "orderId": ORDER_ID},
        UpdateExpression="SET lineItems = :lines",
        ExpressionAttributeValues={":lines": [broken]},
    )
    _ok(_receipt(quantity=10))

    assert_is_error(_fulfill(quantity=1), "INVALID_INPUT")
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_m_06_16_a_kernel_fulfillment_needs_the_originating_campaign(
    world: Dict[str, Any], orders_table: Any, order_fulfillments_table: Any
) -> None:
    """A row with a Unit but no Unit Campaign has no balance to draw, and says so."""
    orders_table.update_item(
        Key={"campaignId": ORDER["campaignId"], "orderId": ORDER_ID},
        UpdateExpression="REMOVE unitCampaignId",
    )

    assert_is_error(_fulfill(quantity=1), "INVALID_INPUT")
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_m_06_17_a_replayed_answer_is_rebuilt_from_the_rows_it_wrote(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """§8.9 on §2.4.3: a lost payload is answered from the committed rows, or honestly fails."""
    _ok(_receipt(quantity=10))
    _ok(_fulfill(quantity=2, key="vanishing"))
    _strip_marker_payload(order_fulfillments_table, FULFILL_LINE_FIELD)
    record = _fulfillment_rows(order_fulfillments_table)[0]
    record_id = str(record["fulfillmentId"])

    # The marker says this request committed and its payload is gone, so the answer is
    # rebuilt from the rows — and nothing is written a second time.
    again = _ok(_fulfill(quantity=2, key="vanishing"))
    assert again["fulfillment"]["fulfillmentId"] == record_id
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 2
    assert len(_fulfillment_rows(order_fulfillments_table)) == 1
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 8

    # A marker whose row cannot be read back is not a caller error: the handler cannot say
    # what its own write produced, which is INTERNAL_ERROR and never an actionable NOT_FOUND.
    order_fulfillments_table.delete_item(Key={"pk": ORDER_ID, "sk": record["sk"]})
    assert_is_error(_fulfill(quantity=2, key="vanishing"), "INTERNAL_ERROR")
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 2


# --- INV-M-07: reverseIndividualOrderFulfillment (§2.4.4) -------------------------


def _fulfillment_id_of(fulfillments_table: Any, order_id: str = ORDER_ID) -> str:
    """The one FULFILL record this Order has, for a reversal that has to name it."""
    rows = [row for row in _fulfillment_rows(fulfillments_table, order_id) if row["recordType"] == "FULFILL"]
    assert len(rows) == 1, rows
    return str(rows[0]["fulfillmentId"])


def test_inv_m_07_01_reversing_a_kernel_fulfillment_restores_stock_and_demand_once(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-01: the Kernel holds what it held, the line owes what it owed, and one record says why."""
    _ok(_receipt(quantity=10))
    fulfilled = _ok(_fulfill(quantity=3))
    fulfillment_id = str(fulfilled["fulfillment"]["fulfillmentId"])

    result = _ok(_reverse(fulfillment_id=fulfillment_id, version=1))

    assert result["order"]["fulfillmentVersion"] == 2
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 0
    assert result["inventoryPosition"]["kernelPhysicalQty"] == 10
    assert result["reversal"]["recordType"] == "REVERSAL"
    assert result["reversal"]["source"] == "KERNEL_STOCK"
    assert result["reversal"]["quantity"] == 3
    assert result["reversal"]["reversalOfFulfillmentId"] == fulfillment_id
    assert result["reversal"]["lineItemId"] == LINE
    assert result["reversal"]["productId"] == PRODUCT

    rows = _fulfillment_rows(order_fulfillments_table)
    assert len(rows) == 2
    reversal = [row for row in rows if row["recordType"] == "REVERSAL"][0]
    assert reversal["sk"] == ful.reversal_sort_key(fulfillment_id)

    movements = [row for row in _movement_rows(inventory_table) if row["movementType"] == "REVERSAL"]
    assert len(movements) == 1
    assert movements[0]["kernelPhysicalDelta"] == 3
    assert movements[0]["fulfillmentId"] == fulfillment_id
    assert movements[0]["orderId"] == ORDER_ID
    assert movements[0]["inventoryVersion"] == 3
    assert reversal["inventoryMovementId"] == movements[0]["movementId"]


def test_inv_m_07_02_reversing_an_external_fulfillment_restores_demand_only(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-01: nothing Unit-owned moved for an external fulfillment, so nothing comes back."""
    fulfilled = _ok(_fulfill(quantity=4, source="EXTERNAL_COUNCIL"))

    result = _ok(_reverse(fulfillment_id=str(fulfilled["fulfillment"]["fulfillmentId"]), version=1))

    assert result["order"]["fulfillmentVersion"] == 2
    assert int(_stored_line(orders_table)["fulfilledQuantity"]) == 0
    assert "inventoryPosition" not in result
    assert _balance_row(inventory_table) is None
    assert _movement_rows(inventory_table) == []
    stored_reversal = _fulfillment_rows(order_fulfillments_table)[1]
    assert "inventoryMovementId" not in stored_reversal, "an external reversal claims no stock moved"
    assert ful.fulfillment_payload(stored_reversal)["inventoryMovementId"] is None


def test_inv_m_07_03_reversing_a_custody_fulfillment_returns_custody_not_kernel_stock(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-01: a Scout-custody fulfillment goes back to the Scout's trunk, not to the Kernel."""
    _ok(_receipt(quantity=10))
    _ok(
        _call(
            "issueStockToScout",
            "Avery",
            mutation={
                "unitCampaignId": CAMPAIGN,
                "campaignId": str(PROFILES["Devon"]["campaignId"]),
                "profileId": DEVON_PROFILE,
                "productId": PRODUCT,
                "quantity": 5,
                **_idem("issue-for-custody-reversal"),
            },
        )
    )
    kernel_after_issue = _balance_row(inventory_table)["kernelPhysicalQty"]
    _plant_fulfillment(
        order_fulfillments_table,
        order=ORDER,
        fulfillment_id="ful-custody-1",
        source="SCOUT_CUSTODY",
        quantity=2,
    )
    _sale_fulfilled_line(orders_table, ORDER, quantity=2, version=1)
    result = _ok(_reverse(fulfillment_id="ful-custody-1", version=1))

    assert result["order"]["fulfillmentVersion"] == 2
    assert int(result["order"]["lineItems"][0]["fulfilledQuantity"]) == 0
    assert "inventoryPosition" not in result, "the Kernel's position did not change"
    assert _custody_row(inventory_table)["withScoutQty"] == 7
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == kernel_after_issue
    movements = [row for row in _movement_rows(inventory_table) if row["movementType"] == "REVERSAL"]
    assert len(movements) == 1
    assert movements[0]["withScoutDelta"] == 2
    assert movements[0]["kernelPhysicalDelta"] == 0
    assert movements[0]["profileId"] == DEVON_PROFILE
    assert movements[0]["fulfillmentId"] == "ful-custody-1"


def test_inv_m_07_04_a_second_reversal_of_one_fulfillment_conflicts(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-02: the deterministic REVERSAL key is the rule, so no stock is created twice."""
    _ok(_receipt(quantity=10))
    fulfillment_id = str(_ok(_fulfill(quantity=3))["fulfillment"]["fulfillmentId"])
    _ok(_reverse(fulfillment_id=fulfillment_id, version=1, key="reverse-first"))

    refused = assert_is_error(_reverse(fulfillment_id=fulfillment_id, version=2, key="reverse-again"), "CONFLICT")

    assert refused["errorCode"] == "CONFLICT"
    reversals = [row for row in _fulfillment_rows(order_fulfillments_table) if row["recordType"] == "REVERSAL"]
    assert len(reversals) == 1
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 10
    assert len([row for row in _movement_rows(inventory_table) if row["movementType"] == "REVERSAL"]) == 1


def test_inv_m_07_05_a_reversal_record_cannot_itself_be_reversed(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """INV-M-07-02: the history is append-only, and the correction of a reversal is a new fulfillment."""
    _ok(_receipt(quantity=10))
    fulfillment_id = str(_ok(_fulfill(quantity=3))["fulfillment"]["fulfillmentId"])
    reversal_id = str(
        _ok(_reverse(fulfillment_id=fulfillment_id, version=1, key="reverse-once"))["reversal"]["fulfillmentId"]
    )

    refused = assert_is_error(
        _reverse(fulfillment_id=reversal_id, version=2, key="reverse-the-reversal"), "INVALID_INPUT"
    )

    assert "REVERSAL" in refused["message"]
    assert len(_fulfillment_rows(order_fulfillments_table)) == 2


def test_inv_m_07_06_an_id_from_another_order_is_not_found_here(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-03, wrong parent: the lookup is scoped to the Order's own partition."""
    _ok(_receipt(quantity=10, key="receipt-miss"))
    fulfillment_id = str(_ok(_fulfill(quantity=2, key="fulfill-miss"))["fulfillment"]["fulfillmentId"])

    assert_is_error(_reverse(order_id=PAST_ORDER_ID, fulfillment_id=fulfillment_id), "NOT_FOUND")
    assert_is_error(_reverse(fulfillment_id="ful-never-written"), "NOT_FOUND")

    assert len(_fulfillment_rows(order_fulfillments_table)) == 1
    assert _balance_row(inventory_table)["kernelPhysicalQty"] == 8


def test_inv_m_07_07_a_stale_version_conflicts_and_a_retry_replays(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-03 with IDEM and AUTH-U: the version guard serializes a reversal against a fulfillment."""
    _ok(_receipt(quantity=10))
    fulfillment_id = str(_ok(_fulfill(quantity=3))["fulfillment"]["fulfillmentId"])

    assert_is_error(_reverse(fulfillment_id=fulfillment_id, version=0, key="stale-reverse"), "CONFLICT")
    first = _ok(_reverse(fulfillment_id=fulfillment_id, version=1, key="good-reverse"))
    again = _ok(_reverse(fulfillment_id=fulfillment_id, version=1, key="good-reverse"))
    assert again == first

    assert_is_error(_reverse(caller="Riley", fulfillment_id=fulfillment_id, key="foreign-reverse"), "NOT_FOUND")
    assert int(_fulfillment_rows(order_fulfillments_table)[1]["quantity"]) == 3


def test_inv_m_07_08_a_line_that_no_longer_holds_the_quantity_conflicts(
    world: Dict[str, Any], orders_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-M-07-02: the row that permits the reversal moved underneath the request."""
    _plant_fulfillment(
        order_fulfillments_table,
        order=ORDER,
        fulfillment_id="ful-planted-3",
        source="EXTERNAL_COUNCIL",
        quantity=3,
    )

    refused = assert_is_error(_reverse(fulfillment_id="ful-planted-3"), "CONFLICT")

    assert "fulfilledQuantity" in refused["message"]
    assert len(_fulfillment_rows(order_fulfillments_table)) == 1


def test_inv_m_07_09_a_custody_reversal_without_an_originating_campaign_is_refused(
    world: Dict[str, Any], orders_table: Any, order_fulfillments_table: Any
) -> None:
    """A record that names no Unit Campaign has no custody to restore into."""
    _plant_fulfillment(
        order_fulfillments_table,
        # The record itself names no Unit Campaign: this is the row shape a stock
        # fulfillment could only ever reach if the sale had captured a Unit but no
        # Unit Campaign, and there is no custody balance to restore into.
        order={key: value for key, value in ORDER.items() if key != "unitCampaignId"},
        fulfillment_id="ful-no-scope",
        source="SCOUT_CUSTODY",
        quantity=1,
    )
    _sale_fulfilled_line(orders_table, ORDER, quantity=1, version=1)

    assert_is_error(_reverse(fulfillment_id="ful-no-scope", version=1), "INVALID_INPUT")
    assert len(_fulfillment_rows(order_fulfillments_table)) == 1


# --- INV-Q-03: orderFulfillments (§2.4.5) ----------------------------------------


def test_inv_q_03_01_the_admin_sees_source_actor_movement_and_reversal(
    world: Dict[str, Any], inventory_table: Any, order_fulfillments_table: Any
) -> None:
    """INV-Q-03-01: the full audit for an Order originating in the caller's Unit."""
    _ok(_receipt(quantity=10))
    fulfillment_id = str(_ok(_fulfill(quantity=4, key="audit-fulfill"))["fulfillment"]["fulfillmentId"])
    reversal = _ok(_reverse(fulfillment_id=fulfillment_id, version=1, key="audit-reverse"))

    page = _ok(_audit())

    assert page["pageInfo"]["hasNextPage"] is False
    assert page["pageInfo"]["endCursor"] is None
    items = page["items"]
    assert [item["recordType"] for item in items] == ["FULFILL", "REVERSAL"]
    assert items[0]["fulfillmentId"] == fulfillment_id
    assert items[1]["fulfillmentId"] == reversal["reversal"]["fulfillmentId"]
    assert all(item["actorAccountId"] == account_id("Avery") for item in items)
    assert all(item["inventoryMovementId"] for item in items), "both records moved Kernel stock"
    assert items[1]["reversalOfFulfillmentId"] == fulfillment_id
    assert all(item["source"] == "KERNEL_STOCK" for item in items)
    assert items[0]["createdAt"] <= items[1]["createdAt"]


def test_inv_q_03_02_a_history_is_ordered_by_when_it_happened(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """The sort-key spellings are storage detail; an audit screen reads what happened first."""
    _plant_fulfillment(
        order_fulfillments_table,
        order=ORDER,
        fulfillment_id="ful-later",
        source="EXTERNAL_COUNCIL",
        quantity=1,
        created_at="2026-11-09T08:00:00+00:00",
    )
    _plant_fulfillment(
        order_fulfillments_table,
        order=ORDER,
        fulfillment_id="ful-earlier",
        source="EXTERNAL_COUNCIL",
        quantity=1,
        created_at="2026-11-05T08:00:00+00:00",
    )
    order_fulfillments_table.put_item(
        Item=dict(
            ful.build_fulfillment_item(
                fulfillment_id="rev-of-earlier",
                order_id=ORDER_ID,
                campaign_id=ORDER["campaignId"],
                profile_id=ORDER["profileId"],
                unit_id=PACK_3149,
                unit_campaign_id=CAMPAIGN,
                line_item_id=LINE,
                product_id=PRODUCT,
                record_type=ful.RECORD_TYPE_REVERSAL,
                quantity=1,
                source="EXTERNAL_COUNCIL",
                actor_account_id=account_id("Avery"),
                created_at="2026-11-06T08:00:00+00:00",
                reversal_of_fulfillment_id="ful-earlier",
            )
        )
    )

    items = _ok(_audit())["items"]

    assert [item["fulfillmentId"] for item in items] == ["ful-earlier", "rev-of-earlier", "ful-later"]


def test_inv_q_03_03_only_an_admin_of_the_originating_unit_reads_the_audit(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """INV-Q-03-02 with AUTH-U: a Scout, a foreign admin, and an independent Order all get nothing."""
    _plant_fulfillment(
        order_fulfillments_table, order=ORDER, fulfillment_id="ful-audit", source="EXTERNAL_COUNCIL", quantity=1
    )

    assert_is_error(_audit(caller="Devon"), "NOT_FOUND")
    assert_is_error(_audit(caller="Riley"), "NOT_FOUND")
    assert_is_error(_audit(caller=None), "UNAUTHORIZED")
    assert_is_error(_audit(order_id=FREE_ORDER_ID), "FORBIDDEN")
    assert_is_error(_audit(order_id="ORDER#bare-uuid"), "INVALID_INPUT")


def test_inv_q_03_04_pages_walk_one_orders_history_and_no_other(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """PAGE-01: a cursor is a positional claim inside one Order's history."""
    for index in range(3):
        _plant_fulfillment(
            order_fulfillments_table,
            order=ORDER,
            fulfillment_id=f"ful-page-{index}",
            source="EXTERNAL_COUNCIL",
            quantity=1,
            created_at=f"2026-11-0{index + 4}T08:00:00+00:00",
        )
    _plant_fulfillment(
        order_fulfillments_table,
        order=PAST_ORDER,
        fulfillment_id="ful-other-order",
        source="EXTERNAL_COUNCIL",
        quantity=1,
    )

    first = _ok(_audit(page={"limit": 2}))
    assert [item["fulfillmentId"] for item in first["items"]] == ["ful-page-0", "ful-page-1"]
    assert first["pageInfo"]["hasNextPage"] is True

    second = _ok(_audit(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert [item["fulfillmentId"] for item in second["items"]] == ["ful-page-2"]
    assert second["pageInfo"]["hasNextPage"] is False

    assert_is_error(
        _audit(order_id=PAST_ORDER_ID, page={"limit": 1, "cursor": first["pageInfo"]["endCursor"]}), "INVALID_INPUT"
    )


def test_inv_q_03_05_the_participant_projection_never_carries_the_audit_fields(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """§10.2 separation: the two answers differ by exactly the administrative fields."""
    _plant_fulfillment(
        order_fulfillments_table, order=ORDER, fulfillment_id="ful-split", source="KERNEL_STOCK", quantity=1
    )
    row = _fulfillment_rows(order_fulfillments_table)[0]

    admin_view = ful.fulfillment_payload(row)
    participant_view = ful.participant_fulfillment_payload(row)

    assert {"actorAccountId", "inventoryMovementId"} <= set(admin_view)
    assert set(admin_view) - set(participant_view) == set(ful.ADMIN_ONLY_FULFILLMENT_FIELDS)
    assert "actorAccountId" not in participant_view and "inventoryMovementId" not in participant_view
    assert participant_view["quantity"] == 1 and participant_view["source"] == "KERNEL_STOCK"

    items = _ok(_audit())["items"]
    assert "actorAccountId" in items[0], "the admin query keeps what the participant field drops"


def test_inv_q_03_06_an_order_with_no_history_answers_an_empty_page(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """A fulfilled-never Order is an empty audit, not a NOT_FOUND: the Order was found."""
    page = _ok(_audit())

    assert page["items"] == []
    assert page["pageInfo"] == {"endCursor": None, "hasNextPage": False}
    assert _fulfillment_rows(order_fulfillments_table) == []


def test_inv_q_03_07_an_argument_that_is_not_a_page_object_is_refused(
    world: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """The shared page contract is validated, not guessed at."""
    assert_is_error(_audit(page="first"), "INVALID_INPUT")
    assert_is_error(_call(ORDER_FULFILLMENTS_FIELD, "Avery", arguments={}), "INVALID_INPUT")
