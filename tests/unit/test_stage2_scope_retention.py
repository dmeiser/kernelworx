"""``ORD-API-02-04`` — the Campaign joins another Unit Campaign, the sale stays where it was sold.

The acceptance line is one sentence: *"After the Campaign joins another Unit Campaign, the old
Order, fulfillment, and Council demand retain the original scope."* Its fixture is ``API-FIX-05``
("arrange order origins in one Unit Campaign, move the Campaign's latest membership to another, and
verify old Orders retain their original scope"), and until now the only place that sentence
appeared in executable code was a comment in two JS resolver tests that never performed a rejoin.

This module performs the rejoin through the deployed resolvers — ``removeUnitCampaignMembership``
then ``joinUnitCampaign`` — and then asks the Stage 2 reads whose tenancy is a row's own origin what
they answer. Both Unit Campaigns here belong to **one Unit**, so no case turns on which admin is
asking: the only thing that could move a sale is scope.

What each test is really about:

* the join pair itself writes roster rows and no money- or stock-shaped row — the history is not
  carried over by being rewritten, which no assertion about reads can prove;
* the reads that scope themselves by the addressed campaign (``unitScoutCampaignOrders``,
  ``scoutCustodyBalances``, ``inventoryPositions``) keep answering the original campaign and stay
  empty on the new one;
* the fulfillment reads and writes scope themselves by the **Order's** immutable ``unitId``/
  ``unitCampaignId``, so the original campaign still owes the demand *and* is the one whose stock
  pays for it (``INV-M-06``, ``_require_fulfillment_scope``);
* a caller with no grant on that Unit is answered as if nothing exists, and changes nothing.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    FULFILL_LINE_FIELD,
    INVENTORY_POSITIONS_FIELD,
    JOIN_UNIT_CAMPAIGN_FIELD,
    ORDER_FULFILLMENTS_FIELD,
    REMOVE_MEMBERSHIP_FIELD,
    SCOUT_CUSTODY_FIELD,
    UNIT_SCOUT_ORDERS_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from src.utils import unit_campaign_models as ucm
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

#: The two Unit Campaigns on one Unit. The Scout Campaign is removed from ``FROM_CAMPAIGN`` and
#: joins ``TO_CAMPAIGN``; the fixture campaign starts inactive, so the world re-opens it the way
#: ``updateUnitCampaign`` does (§1.5.2 permits ``isActive`` on its own).
FROM_CAMPAIGN = PACK_3149_FALL
TO_CAMPAIGN = PACK_3149_OLD
TO_CAMPAIGN_JOIN_CODE = "JOINPK3149OLD001"

ADMIN = "Avery"
SCOUT = "Devon"
OUTSIDER = "Riley"
SCOUT_PROFILE = str(PROFILES[SCOUT]["profileId"])
SCOUT_CAMPAIGN = str(PROFILES[SCOUT]["campaignId"])
ORDER_ID = "ORDER#camp-devon-fixture#scope-1"
PRODUCT = FIXTURE_PRODUCT_ID
LINE = "line-scope-1"
SHELF_AT_T0 = 8
SOLD_QTY = 5
FIRST_FULFILLED_QTY = 3
CUSTODY_AT_T0 = 2
MORNING = "2026-11-07T08:00:00+00:00"


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """One resolver turn through the deployed entry point (errors arrive as payloads)."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _ok(payload: Any) -> Any:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    assert payload is not None, "the resolver answered null"
    return payload


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


# ---------------------------------------------------------------------------
# The four Stage 2 reads whose tenancy is a row's origin, and the one write that
# follows it. Each is a named call, so a test says what it asks rather than
# rebuilding a request each time.
# ---------------------------------------------------------------------------


def _orders(unit_campaign_id: str, *, caller: str = ADMIN) -> List[Dict[str, Any]]:
    """``unitScoutCampaignOrders`` for this Scout Campaign under one addressed Unit Campaign."""
    page = _ok(
        _call(
            UNIT_SCOUT_ORDERS_FIELD,
            caller,
            arguments={"unitCampaignId": unit_campaign_id, "campaignId": SCOUT_CAMPAIGN, "page": {"limit": 10}},
        )
    )
    return list(page["items"])


def _fulfillments(order_id: str, *, caller: str = ADMIN) -> List[Dict[str, Any]]:
    """``orderFulfillments`` — the administrative projection, audit fields included."""
    page = _ok(_call(ORDER_FULFILLMENTS_FIELD, caller, arguments={"orderId": order_id, "page": {"limit": 20}}))
    return list(page["items"])


def _positions(unit_campaign_id: str, *, caller: str = ADMIN) -> List[Dict[str, Any]]:
    page = _ok(_call(INVENTORY_POSITIONS_FIELD, caller, arguments={"unitCampaignId": unit_campaign_id}))
    return list(page["items"])


def _custody(unit_campaign_id: str, *, caller: str = ADMIN) -> List[Dict[str, Any]]:
    page = _ok(_call(SCOUT_CUSTODY_FIELD, caller, arguments={"unitCampaignId": unit_campaign_id, "page": {"limit": 20}}))
    return list(page["items"])


def _fulfill(
    order_id: str,
    *,
    quantity: int,
    expected_version: int,
    key: str,
    caller: str = ADMIN,
) -> Dict[str, Any]:
    """``fulfillIndividualOrderLine`` from unassigned Kernel stock (``INV-M-06-01``)."""
    answer = _ok(
        _call(
            FULFILL_LINE_FIELD,
            caller,
            mutation={
                "orderId": order_id,
                "lineItemId": LINE,
                "quantity": quantity,
                "source": ful.SOURCE_KERNEL_STOCK,
                "expectedFulfillmentVersion": expected_version,
                **_idem(key),
            },
        )
    )
    assert isinstance(answer, dict)
    return answer


def _fulfilled_of(order: Dict[str, Any]) -> int:
    """The line's fulfilled quantity, read out of whatever Order projection answered."""
    line = next(item for item in order["lineItems"] if item.get("lineItemId") == LINE)
    return int(line.get(ful.FULFILLED_QUANTITY_ATTRIBUTE) or 0)


# ---------------------------------------------------------------------------
# Fingerprints: whole tables, so a quiet re-stamp cannot hide inside a read.
# ---------------------------------------------------------------------------


def _rows(table: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    token: Optional[Dict[str, Any]] = None
    while True:
        kwargs: Dict[str, Any] = {}
        if token is not None:
            kwargs["ExclusiveStartKey"] = token
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            return items


def _sale_state(orders_table: Any, fulfillments_table: Any, inventory_table: Any) -> List[str]:
    """Every Order, fulfillment and inventory row — idempotency markers included, one sorted list.

    Whole-table rather than one row on purpose: a join that quietly re-stamped a sale's
    ``unitCampaignId``, or added a movement to carry it across, changes this list even when every
    read still looks right.
    """
    rows: List[str] = []
    for table in (orders_table, fulfillments_table, inventory_table):
        rows.extend(json.dumps(row, sort_keys=True, default=str) for row in _rows(table))
    return sorted(rows)


def _demand(orders_table: Any, unit_campaign_ids: List[str]) -> Dict[str, int]:
    """One product's Council demand — ordered, fulfilled, unfulfilled — across named origins."""
    ordered = fulfilled = 0
    for order in _rows(orders_table):
        if str(order.get(ful.UNIT_CAMPAIGN_ID_ATTRIBUTE) or "") not in unit_campaign_ids:
            continue
        for line in order.get(ful.LINE_ITEMS_ATTRIBUTE, []):
            if str(line.get(ful.PRODUCT_ID_ATTRIBUTE)) != PRODUCT:
                continue
            ordered += int(line["quantity"])
            fulfilled += int(line.get(ful.FULFILLED_QUANTITY_ATTRIBUTE) or 0)
    return {"orderedQty": ordered, "fulfilledQty": fulfilled, "unfulfilledQty": ordered - fulfilled}


# ---------------------------------------------------------------------------
# The move, performed by the resolvers that own it.
# ---------------------------------------------------------------------------


def _reopen(unit_campaigns_table: Any, unit_campaign_id: str) -> None:
    """Make the fixture campaign joinable — the state ``updateUnitCampaign`` puts it in."""
    unit_campaigns_table.update_item(
        Key=ucm.unit_campaign_metadata_key(unit_campaign_id),
        UpdateExpression="SET #active = :yes",
        ExpressionAttributeNames={"#active": "isActive"},
        ExpressionAttributeValues={":yes": True},
    )


def _rejoin() -> Dict[str, Any]:
    """Out of one Unit Campaign, into another, both by API (``API-FIX-05``)."""
    removed = _ok(
        _call(
            REMOVE_MEMBERSHIP_FIELD,
            ADMIN,
            mutation={
                "unitCampaignId": FROM_CAMPAIGN,
                "campaignId": SCOUT_CAMPAIGN,
                "expectedMembershipVersion": 1,
                "expectedGuardVersion": 1,
                **_idem("scope-rejoin-remove"),
            },
        )
    )
    joined = _ok(
        _call(
            JOIN_UNIT_CAMPAIGN_FIELD,
            SCOUT,
            mutation={"joinCode": TO_CAMPAIGN_JOIN_CODE, "campaignId": SCOUT_CAMPAIGN, **_idem("scope-rejoin-join")},
        )
    )
    assert removed["status"] == "REMOVED" and joined["status"] == "ACTIVE"
    return {"removed": removed, "joined": joined}


# ---------------------------------------------------------------------------
# The arranged world: a shelf in one Unit Campaign, a sale taken there, and a
# fulfillment of that sale drawn from that shelf.
# ---------------------------------------------------------------------------


@pytest.fixture
def lane(
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
    """A sale whose whole world lives in ``FROM_CAMPAIGN``.

    The Order arrives the way the ``createOrder`` pipeline stores it, with the scope captured at
    sale time. The fulfillment arrives through the deployed fulfillment resolver, so its scope is
    written by production code rather than stamped here — which is what makes the post-move
    assertion about it worth reading.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _reopen(unit_campaigns_table, TO_CAMPAIGN)
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=FROM_CAMPAIGN,
            product_id=PRODUCT,
            kernel_physical_qty=SHELF_AT_T0,
            sold_in_possession_qty=0,
            council_on_order_qty=0,
            now_iso=MORNING,
        )
    )
    inventory_table.put_item(
        Item=inv.build_scout_custody_balance_item(
            unit_campaign_id=FROM_CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT_PROFILE,
            campaign_id=SCOUT_CAMPAIGN,
            with_scout_qty=CUSTODY_AT_T0,
            now_iso=MORNING,
        )
    )
    orders_table.put_item(
        Item=sold_order_item(
            SCOUT,
            suffix="scope-1",
            unit_id=PACK_3149,
            unit_campaign_id=FROM_CAMPAIGN,
            lines=[order_line_item(product_id=PRODUCT, quantity=SOLD_QTY, line_item_id=LINE, fulfilled_quantity=0)],
        )
    )
    first = _fulfill(ORDER_ID, quantity=FIRST_FULFILLED_QTY, expected_version=0, key="scope-fulfill-first")
    return {
        "order_id": ORDER_ID,
        "first_fulfillment_id": str(first["fulfillment"]["fulfillmentId"]),
        "orders_table": orders_table,
        "fulfillments_table": order_fulfillments_table,
        "inventory_table": inventory_table,
        "unit_campaigns_table": unit_campaigns_table,
    }


# ---------------------------------------------------------------------------
# The control, then the move, then the four reads.
# ---------------------------------------------------------------------------


def test_the_sale_answers_its_own_campaign_before_the_move(lane: Dict[str, Any]) -> None:
    """The control: every read below is answered *before* the join, so a silence afterwards is the join's."""
    orders = _orders(FROM_CAMPAIGN)
    assert [order["orderId"] for order in orders] == [lane["order_id"]]
    assert _fulfilled_of(orders[0]) == FIRST_FULFILLED_QTY
    assert orders[0]["unitCampaignId"] == FROM_CAMPAIGN and orders[0]["unitId"] == PACK_3149
    assert _demand(lane["orders_table"], [FROM_CAMPAIGN]) == {
        "orderedQty": SOLD_QTY,
        "fulfilledQty": FIRST_FULFILLED_QTY,
        "unfulfilledQty": SOLD_QTY - FIRST_FULFILLED_QTY,
    }

    history = _fulfillments(lane["order_id"])
    assert [record["recordType"] for record in history] == [ful.RECORD_TYPE_FULFILL]
    assert history[0]["unitCampaignId"] == FROM_CAMPAIGN and history[0]["unitId"] == PACK_3149
    assert history[0]["inventoryMovementId"], "a Kernel-stock fulfillment names the movement it wrote"

    assert _positions(FROM_CAMPAIGN)[0]["kernelPhysicalQty"] == SHELF_AT_T0 - FIRST_FULFILLED_QTY
    assert _custody(FROM_CAMPAIGN)[0]["withScoutQty"] == CUSTODY_AT_T0
    assert _orders(TO_CAMPAIGN) == []
    assert _positions(TO_CAMPAIGN) == []
    assert _custody(TO_CAMPAIGN) == []


def test_the_move_writes_the_roster_and_no_sale(lane: Dict[str, Any]) -> None:
    """Removal plus rejoin move the membership, the guard, and the Campaign's latest link — nothing else.

    This is the half that assertions about reads cannot prove: that the move did not carry the
    history over by rewriting it (``API-FIX-05``, ``ROSTER-04``).
    """
    before = _sale_state(lane["orders_table"], lane["fulfillments_table"], lane["inventory_table"])

    _rejoin()

    assert _sale_state(lane["orders_table"], lane["fulfillments_table"], lane["inventory_table"]) == before, (
        "a roster move rewrote a sale, a fulfillment, or a balance"
    )
    scout_campaign = ucm.read_scout_campaign(SCOUT_CAMPAIGN)
    assert scout_campaign is not None
    assert scout_campaign["unitCampaignId"] == TO_CAMPAIGN, "the Campaign's latest link did not move"
    guard = ucm.read_membership_guard(SCOUT_CAMPAIGN)
    assert ucm.guard_active_unit_campaign_id(guard) == TO_CAMPAIGN
    assert ucm.read_membership(FROM_CAMPAIGN, SCOUT_PROFILE)["status"] == "REMOVED"
    assert ucm.read_membership(TO_CAMPAIGN, SCOUT_PROFILE)["status"] == "ACTIVE"


def test_the_old_campaign_still_owes_the_sale_after_the_move(lane: Dict[str, Any]) -> None:
    """Order, fulfillment, and Council demand all keep answering for ``FROM_CAMPAIGN``.

    Tenancy on these reads is the row's own immutable origin, never the scope the Campaign holds
    today — which is why the campaign it joined answers empty instead of inheriting a sale it
    never made.
    """
    _rejoin()

    orders = _orders(FROM_CAMPAIGN)
    assert [order["orderId"] for order in orders] == [lane["order_id"]], "the sale did not follow the membership"
    assert orders[0]["unitCampaignId"] == FROM_CAMPAIGN and orders[0]["unitId"] == PACK_3149
    assert _orders(TO_CAMPAIGN) == []

    assert _demand(lane["orders_table"], [FROM_CAMPAIGN]) == {
        "orderedQty": SOLD_QTY,
        "fulfilledQty": FIRST_FULFILLED_QTY,
        "unfulfilledQty": SOLD_QTY - FIRST_FULFILLED_QTY,
    }, "the demand the old campaign owes did not move"
    assert _demand(lane["orders_table"], [TO_CAMPAIGN]) == {
        "orderedQty": 0,
        "fulfilledQty": 0,
        "unfulfilledQty": 0,
    }, "the campaign it joined does not inherit demand"

    history = _fulfillments(lane["order_id"])
    assert [record["unitCampaignId"] for record in history] == [FROM_CAMPAIGN]
    assert history[0]["fulfillmentId"] == lane["first_fulfillment_id"]


def test_the_old_campaign_is_still_the_one_whose_stock_pays(lane: Dict[str, Any]) -> None:
    """A fulfillment of the old sale, placed after the move, draws on the old campaign's shelf.

    ``INV-M-06`` never asks which campaign the Scout belongs to now: it takes the balance beside the
    Order's own ``unitCampaignId``. A sale that followed the membership would be paid for out of
    stock that was never received for it, and the original shelf would keep a decrement it owes
    nothing for.
    """
    _rejoin()

    second = _fulfill(lane["order_id"], quantity=1, expected_version=1, key="scope-fulfill-second")

    assert _fulfilled_of(second["order"]) == FIRST_FULFILLED_QTY + 1
    assert _positions(FROM_CAMPAIGN)[0]["kernelPhysicalQty"] == SHELF_AT_T0 - FIRST_FULFILLED_QTY - 1
    assert _positions(TO_CAMPAIGN) == [], "the move created no shelf for a sale it does not own"

    new_record = next(
        record for record in _fulfillments(lane["order_id"]) if record["fulfillmentId"] == second["fulfillment"]["fulfillmentId"]
    )
    assert new_record["unitCampaignId"] == FROM_CAMPAIGN, "a new fulfillment names the sale's origin, not today's scope"
    assert new_record["source"] == ful.SOURCE_KERNEL_STOCK
    assert second["inventoryPosition"]["kernelPhysicalQty"] == SHELF_AT_T0 - FIRST_FULFILLED_QTY - 1
    assert _demand(lane["orders_table"], [FROM_CAMPAIGN])["unfulfilledQty"] == SOLD_QTY - FIRST_FULFILLED_QTY - 1


def test_custody_and_balances_do_not_travel_with_the_membership(lane: Dict[str, Any]) -> None:
    """``ROSTER-04``: joining another Unit Campaign moves no custody, no stock, and no history."""
    _rejoin()

    assert [(row["profileId"], row["withScoutQty"]) for row in _custody(FROM_CAMPAIGN)] == [(SCOUT_PROFILE, CUSTODY_AT_T0)]
    assert _custody(TO_CAMPAIGN) == []
    assert _positions(TO_CAMPAIGN) == []

    movements = [row for row in _rows(lane["inventory_table"]) if row.get("entityType") == "InventoryMovement"]
    assert movements, "the fulfillment wrote a movement in the campaign that made the sale"
    assert {str(row["unitCampaignId"]) for row in movements} == {FROM_CAMPAIGN}


def test_a_caller_outside_the_unit_is_refused_and_changes_nothing(lane: Dict[str, Any]) -> None:
    """The move does not widen a door: afterwards, an unrelated admin is still answered nothing.

    Both reads carry the arguments the real admin succeeds with, so the refusal has the caller as
    its only cause — and the whole-lane fingerprint proves the refusal staged no write.
    """
    _rejoin()
    before = _sale_state(lane["orders_table"], lane["fulfillments_table"], lane["inventory_table"])

    assert_is_error(
        _call(
            UNIT_SCOUT_ORDERS_FIELD,
            OUTSIDER,
            arguments={"unitCampaignId": FROM_CAMPAIGN, "campaignId": SCOUT_CAMPAIGN, "page": {"limit": 10}},
        ),
        "NOT_FOUND",
    )
    assert_is_error(_call(ORDER_FULFILLMENTS_FIELD, OUTSIDER, arguments={"orderId": lane["order_id"]}), "NOT_FOUND")

    assert _sale_state(lane["orders_table"], lane["fulfillments_table"], lane["inventory_table"]) == before
    assert account_id(OUTSIDER) != account_id(ADMIN)
