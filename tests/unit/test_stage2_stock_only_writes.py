"""Leaf 2.8.2 — a stock-only adjustment moves stock, and nothing else, anywhere.

§2.8.2 asks for an integration test of the stock-only mutations that proves they create **no
Order, Show & Sell sale, payment, trade, fulfillment, obligation, or Scout-credit effect**. The
per-leaf tests (§2.2) assert this locally — that the campaign's inventory partition holds only
balance and movement rows, that ``orders`` is empty — which is true but narrow: it can only see
what a fixture happened to create, and "empty" is also what an untouched table looks like.

This module proves the claim twice over, in a way that fails for different reasons:

1. **The write set.** Every DynamoDB call the handler makes is recorded at the botocore layer —
   ``TransactWriteItems`` unpacked, so a write that hides inside a transaction is recorded as the
   writes it really is — and the only table any *write* may name is the inventory table. Reads may
   go wider: authorization reads the campaign, the catalog and the grant. The unit environment
   provisions no Show & Sell, sale, credit or We Owe table at all, so a mutation that booked money
   would fail loudly here as well as being caught by the recorder.
2. **The neighbours.** A world that already holds an Order, a fulfillment history row, the Scout
   Campaign's ``totalOrders``/``totalRevenue`` counters, the admin's saved payment methods, and the
   roster/grant rows is snapshotted whole and must come back byte-identical. A mutation that
   quietly added a row, or nudged a counter, changes the snapshot — which is the difference between
   asserting a table is empty and asserting it was not touched.

The audit trail is checked too: the movement rows a stock-only write appends carry only the three
stock-only movement types, move only stock deltas, and name no sale, Order, fulfillment, We Owe,
finalization, event or Scout, because such a link is exactly what ties stock to money (§5.8).
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

import botocore.client
import pytest

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    ISSUE_STOCK_FIELD,
    RECORD_RECEIPT_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from src.utils.dynamodb import tables
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    account_id,
    assert_is_error,
    order_line_item,
    seed_show_sell_fixtures,
    sold_order_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_CAMPAIGN = f"{PACK_3149_FALL}-other"
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
NOT_IN_CATALOG = f"{CATALOG_ID}#prod-404"
SCOUT = "Devon"
LINE = "line-neighbour-1"
FULFILLMENT_ID = "11111111-1111-4111-8111-111111111111"
ACTOR = "Avery"
MORNING = "2026-11-07T08:00:00+00:00"
AFTERNOON = "2026-11-07T13:00:00+00:00"

#: The only movement types §2.2 may append. Anything else on a stock-only trail is an effect
#: booked somewhere the card says this surface must not reach.
STOCK_ONLY_MOVEMENTS = {inv.RECEIPT, inv.STOCK_ADJUSTMENT, inv.COUNCIL_ON_ORDER_ADJUST}

#: Attributes that tie an inventory movement to money, an Order, or another agent (§5.8). A
#: receipt, adjustment and on-order change have no source to name: they are the Kernel's own shelf.
SOURCE_LINKS = (
    inv.SALE_ID_ATTRIBUTE,
    inv.ORDER_ID_ATTRIBUTE,
    inv.WE_OWE_ID_ATTRIBUTE,
    inv.FULFILLMENT_ID_ATTRIBUTE,
    inv.FINALIZATION_ID_ATTRIBUTE,
    inv.SHOW_AND_SELL_ID_ATTRIBUTE,
    inv.PROFILE_ID_ATTRIBUTE,
)

#: The DynamoDB actions that change a row. A read may reach any table authorization needs; a write may not.
WRITE_ACTIONS = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactWriteItems"}


class DynamoWriteRecorder:
    """Every DynamoDB call the handler makes, with the table each one names.

    Hooks ``BaseClient._make_api_call`` so resource-style and client-style calls are both captured,
    and unpacks ``TransactWriteItems`` so a write that hides inside a transaction is recorded as the
    writes it actually is. Seeding done before ``attach()`` is not recorded.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.writes: List[Tuple[str, str]] = []
        self.reads: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = getattr(botocore.client.BaseClient, "_make_api_call")
        recorder = self

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            if self.meta.service_model.service_name == "dynamodb":
                recorder._record(operation_name, params)
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)

    def reset(self) -> None:
        """Forget everything recorded so far, so the next call's write set stands alone."""
        self.writes.clear()
        self.reads.clear()

    def _record(self, operation_name: str, params: Any) -> None:
        if not isinstance(params, dict):
            return
        named: List[str] = []
        if isinstance(params.get("TableName"), str):
            named.append(str(params["TableName"]))
        if isinstance(params.get("RequestItems"), dict):
            named.extend(str(name) for name in params["RequestItems"])
        bucket = self.writes if operation_name in WRITE_ACTIONS else self.reads
        if operation_name == "TransactWriteItems":
            for item in params.get("TransactItems", []):
                for action in ("Put", "Update", "Delete", "ConditionCheck"):
                    inner = item.get(action)
                    if isinstance(inner, dict) and isinstance(inner.get("TableName"), str):
                        bucket.append((f"{operation_name}:{action}", str(inner["TableName"])))
            return
        for name in named:
            bucket.append((operation_name, name))

    def written_tables(self) -> List[str]:
        return sorted({name for _action, name in self.writes})


@pytest.fixture
def dynamodb_calls(stock: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> DynamoWriteRecorder:
    """Attach the recorder after ``stock`` seeds the shelf, so only the mutation's calls are captured."""
    recorder = DynamoWriteRecorder(monkeypatch)
    recorder.attach()
    return recorder


@pytest.fixture
def stock(inventory_table: Any, world: Dict[str, Any]) -> Dict[str, Any]:
    """A shelf of ten Kernels, put there before the recorder attaches.

    Seeding through a fixture rather than the test body is what makes the write-set assertions mean
    something: the row they are measured against exists before the first recorded call, so every
    entry in ``dynamodb_calls.writes`` is the mutation's own work.
    """
    return _seed_balance(inventory_table, physical=10)


# ---------------------------------------------------------------------------
# The world, its neighbours, and the snapshots that prove they did not move.
# ---------------------------------------------------------------------------


def _call(field: str, mutation: Dict[str, Any], *, caller: Optional[str] = ACTOR) -> Any:
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation), None)


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _receipt(
    quantity: int,
    *,
    key: str,
    occurred_at: Optional[str] = None,
    product_id: str = PRODUCT,
    campaign: str = CAMPAIGN,
    caller: Optional[str] = ACTOR,
) -> Any:
    payload: Dict[str, Any] = {"unitCampaignId": campaign, "productId": product_id, "quantity": quantity, **_idem(key)}
    if occurred_at is not None:
        payload["occurredAt"] = occurred_at
    return _call(RECORD_RECEIPT_FIELD, payload, caller=caller)


def _adjust(
    delta: int,
    reason: str,
    *,
    key: str,
    occurred_at: Optional[str] = None,
    product_id: str = PRODUCT,
    campaign: str = CAMPAIGN,
    caller: Optional[str] = ACTOR,
) -> Any:
    payload: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": product_id,
        "quantityDelta": delta,
        "reason": reason,
        **_idem(key),
    }
    if occurred_at is not None:
        payload["occurredAt"] = occurred_at
    return _call(ADJUST_INVENTORY_FIELD, payload, caller=caller)


def _council(
    delta: int,
    *,
    key: str,
    reason: str = "Council promised a case",
    occurred_at: Optional[str] = None,
    campaign: str = CAMPAIGN,
) -> Any:
    payload: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": PRODUCT,
        "quantityDelta": delta,
        "reason": reason,
        **_idem(key),
    }
    if occurred_at is not None:
        payload["occurredAt"] = occurred_at
    return _call(ADJUST_COUNCIL_FIELD, payload)


def _issue(quantity: int, *, key: str, scout: str = SCOUT) -> Any:
    return _call(
        ISSUE_STOCK_FIELD,
        {
            "unitCampaignId": CAMPAIGN,
            "campaignId": str(PROFILES[scout]["campaignId"]),
            "profileId": str(PROFILES[scout]["profileId"]),
            "productId": PRODUCT,
            "quantity": quantity,
            **_idem(key),
        },
    )


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
    """The Stage 1 personas, plus the stock and the sale history the mutations must not disturb."""
    seeded = seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _arrange_neighbours(orders_table, order_fulfillments_table)
    return seeded


def _arrange_neighbours(orders_table: Any, order_fulfillments_table: Any) -> None:
    """A sale, its fulfillment history, and the admin's saved payment methods.

    These are the surfaces §2.8.2 names — Order, sale, payment, trade, fulfillment, obligation,
    Scout credit — populated rather than absent, so a stock write that reached one of them is
    caught by a row that changed rather than by a table that was empty either way.
    """
    order = sold_order_item(
        SCOUT,
        suffix="neighbour-1",
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        lines=[order_line_item(product_id=PRODUCT, quantity=6, line_item_id=LINE)],
    )
    orders_table.put_item(Item=order)
    order_fulfillments_table.put_item(
        Item=ful.build_fulfillment_item(
            fulfillment_id=FULFILLMENT_ID,
            order_id=order["orderId"],
            campaign_id=order["campaignId"],
            profile_id=order["profileId"],
            unit_id=PACK_3149,
            unit_campaign_id=CAMPAIGN,
            line_item_id=LINE,
            product_id=PRODUCT,
            record_type=ful.RECORD_TYPE_FULFILL,
            quantity=2,
            source=ful.SOURCE_KERNEL_STOCK,
            actor_account_id=account_id(ACTOR),
            created_at=MORNING,
            inventory_movement_id="mov-neighbour-1",
        )
    )
    tables.accounts.put_item(
        Item={
            "accountId": account_id(ACTOR),
            "email": "avery@fixtures.kernelworx.test",
            "preferences": {
                "paymentMethods": [
                    {"id": "pm-cash", "name": "Cash", "type": "BUILTIN"},
                    {"id": "pm-venmo", "name": f"Venmo {CAMPAIGN}", "type": "CUSTOM", "qrCodeUrl": "s3://x/venmo.png"},
                ],
                "showAndSellWeOweDefault": False,
            },
        }
    )
    tables.campaigns.update_item(
        Key={"profileId": PROFILES[SCOUT]["profileId"], "campaignId": PROFILES[SCOUT]["campaignId"]},
        UpdateExpression="SET totalOrders = :orders, totalRevenue = :revenue",
        ExpressionAttributeValues={":orders": 7, ":revenue": "140.00"},
    )


def _rows(table: Any) -> List[Dict[str, Any]]:
    """Every row of one table, following ``LastEvaluatedKey`` to the end."""
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


def _fingerprint(table: Any) -> List[str]:
    """One table, whole, as stable sorted text."""
    return sorted(json.dumps(row, sort_keys=True, default=str) for row in _rows(table))


def _neighbour_snapshot() -> Dict[str, List[str]]:
    """Every table a stock-only mutation has no business touching, whole."""
    return {
        "accounts": _fingerprint(tables.accounts),
        "campaigns": _fingerprint(tables.campaigns),
        "catalogs": _fingerprint(tables.catalogs),
        "orders": _fingerprint(tables.orders),
        "order_fulfillments": _fingerprint(tables.order_fulfillments),
        "profiles": _fingerprint(tables.profiles),
        "shares": _fingerprint(tables.shares),
        "unit_campaigns": _fingerprint(tables.unit_campaigns),
        "units": _fingerprint(tables.units),
    }


def _stage_state(inventory_table: Any, orders_table: Any, order_fulfillments_table: Any) -> List[str]:
    """Every Stage 2 row, including the idempotency markers, as one sorted list."""
    rows: List[str] = []
    for table in (inventory_table, orders_table, order_fulfillments_table):
        rows.extend(_fingerprint(table))
    return sorted(rows)


def _typed(inventory_table: Any, entity_type: str) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table) if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == entity_type]


def _markers(inventory_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table) if str(row.get("sk", "")).startswith("IDEM#")]


def _order_row(orders_table: Any) -> Dict[str, Any]:
    rows = _rows(orders_table)
    assert len(rows) == 1, f"expected the one neighbour Order, got {rows!r}"
    return rows[0]


# ---------------------------------------------------------------------------
# The write set: stock-only means the inventory table, and only the inventory table.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run",
    [
        lambda: _receipt(4, key="only-receipt"),
        lambda: _adjust(2, "Trade with Troop 7150; money settled outside app", key="only-adjust-up"),
        lambda: _adjust(-1, "Gift to outgoing volunteer", key="only-adjust-down"),
        lambda: _council(3, key="only-council"),
    ],
    ids=["receipt", "adjust-up-trade", "adjust-down-gift", "council-on-order"],
)
def test_a_stock_only_mutation_writes_only_the_inventory_table(
    stock: Dict[str, Any],
    inventory_table: Any,
    dynamodb_calls: DynamoWriteRecorder,
    run: Callable[[], Any],
) -> None:
    """§2.8.2: the write set of each stock-only mutation is the inventory table, nothing else.

    The trade and the gift are the smoke plan's own reasons (SS-SM-03 steps 5 and 6) because a
    reason that says money settled outside the application is exactly the case a stray payment or
    credit write would corrupt.
    """
    before = _neighbour_snapshot()

    _ok(run())

    assert dynamodb_calls.written_tables() == [inventory_table.table_name], (
        f"a stock-only write reached another table: {dynamodb_calls.writes!r}"
    )
    assert _neighbour_snapshot() == before, "a stock-only write touched an Order, payment, or Scout Campaign row"


def test_an_idempotent_retry_adds_no_second_row(
    stock: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    dynamodb_calls: DynamoWriteRecorder,
) -> None:
    """The replay of a stock-only request writes nothing at all, in any table.

    A retry that booked its effect twice would show up as a second movement, a second marker, or a
    second row on a money table. It does not: the replay answers from the committed marker, so the
    state is byte-identical and the write set is empty.
    """
    _ok(_receipt(3, key="retry-receipt", occurred_at=MORNING))
    _ok(_adjust(-2, "Recount at the scout shed", key="retry-adjust", occurred_at=MORNING))
    _ok(_council(2, key="retry-council", occurred_at=MORNING))
    dynamodb_calls.reset()
    after_first = _stage_state(inventory_table, orders_table, order_fulfillments_table)

    for replay in (
        _receipt(3, key="retry-receipt", occurred_at=MORNING),
        _adjust(-2, "Recount at the scout shed", key="retry-adjust", occurred_at=MORNING),
        _council(2, key="retry-council", occurred_at=MORNING),
    ):
        _ok(replay)

    assert dynamodb_calls.writes == [], f"a replay wrote: {dynamodb_calls.writes!r}"
    assert _stage_state(inventory_table, orders_table, order_fulfillments_table) == after_first
    assert len(_markers(inventory_table)) == 3, "the replay left a second idempotency marker behind"


# ---------------------------------------------------------------------------
# The attempts §2.8.2 calls "other tests": actions that would change those records, rejected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run,code",
    [
        (lambda: _adjust(-11, "more than the shelf holds", key="ref-use"), "INVALID_INPUT"),
        (lambda: _receipt(4, key="ref-catalog", product_id=NOT_IN_CATALOG), "INVALID_INPUT"),
        (lambda: _council(-4, key="ref-council-floor"), "INVALID_INPUT"),
        (lambda: _receipt(4, key="ref-foreign", campaign=OTHER_CAMPAIGN), "NOT_FOUND"),
        (lambda: _receipt(4, key="ref-foreign-unit", caller="Riley"), "NOT_FOUND"),
        (lambda: _receipt(4, key="ref-no-session", caller=None), "UNAUTHORIZED"),
        (lambda: _issue(11, key="ref-custody-race"), "INVALID_INPUT"),
    ],
    ids=[
        "draw-below-zero",
        "product-not-in-catalog",
        "council-below-zero",
        "unknown-campaign",
        "another-unit-admin",
        "no-session",
        "issue-past-the-shelf",
    ],
)
def test_a_rejected_attempt_to_touch_money_or_stock_changes_nothing(
    stock: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    dynamodb_calls: DynamoWriteRecorder,
    run: Callable[[], Any],
    code: str,
) -> None:
    """A request that would move money, or stock it does not own, is refused and writes nothing.

    The last case is the one that reaches nearest to money: an issue of more Kernels than the shelf
    holds would create custody a sale could later bill, so it is refused before any row is staged.
    """
    before = _stage_state(inventory_table, orders_table, order_fulfillments_table)
    neighbours = _neighbour_snapshot()

    payload = run()
    assert_is_error(payload, code)

    assert dynamodb_calls.writes == [], f"a refused request wrote: {dynamodb_calls.writes!r}"
    assert _stage_state(inventory_table, orders_table, order_fulfillments_table) == before
    assert _neighbour_snapshot() == neighbours


def test_an_existing_sale_stays_unfulfilled_after_stock_only_writes(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Receipts, adjustments and on-order changes never book against an Order that exists."""
    _seed_balance(inventory_table, physical=10)
    order_before = _order_row(orders_table)
    assert int(order_before["fulfillmentVersion"]) == 0
    assert int(order_before["lineItems"][0]["fulfilledQuantity"]) == 0

    _ok(_receipt(2, key="sale-receipt", occurred_at=MORNING))
    _ok(_adjust(-2, "Trade with Troop 7150; money settled outside app", key="sale-trade", occurred_at=MORNING))
    _ok(_council(4, key="sale-council", occurred_at=MORNING))

    assert _order_row(orders_table) == order_before
    assert len(_rows(order_fulfillments_table)) == 1, "a stock-only write appended a fulfillment record"


# ---------------------------------------------------------------------------
# The audit trail: stock movement types, stock deltas, and no link to money or another agent.
# ---------------------------------------------------------------------------


def test_a_stock_only_trail_carries_no_sale_order_or_obligation_link(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """The trail stays about stock: only stock movement types, and no source link at all."""
    _seed_balance(inventory_table, physical=10)
    _ok(_receipt(2, key="trail-receipt", occurred_at=MORNING))
    _ok(_adjust(2, "Trade with Troop 7150; money settled outside app", key="trail-trade", occurred_at=AFTERNOON))
    _ok(_adjust(-1, "Gift to outgoing volunteer", key="trail-gift", occurred_at=AFTERNOON))
    _ok(_council(3, key="trail-council", occurred_at=AFTERNOON))

    movements = _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)
    assert len(movements) == 4
    assert {row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in movements} == STOCK_ONLY_MOVEMENTS
    for movement in movements:
        for link in SOURCE_LINKS:
            assert link not in movement, f"{movement[inv.MOVEMENT_TYPE_ATTRIBUTE]} carries {link}"
        assert inv.movement_row_violations(movement) == [], movement

    custody = _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)
    allocations = _typed(inventory_table, inv.ALLOCATION_ENTITY_TYPE)
    assert custody == [] and allocations == [], "a stock-only write opened a custody or allocation row"


@pytest.mark.parametrize(
    "run,expected",
    [
        (lambda: _receipt(4, key="delta-receipt"), {inv.KERNEL_PHYSICAL_DELTA: 4}),
        (lambda: _adjust(2, "Trade with Troop 7150", key="delta-up"), {inv.KERNEL_PHYSICAL_DELTA: 2}),
        (lambda: _adjust(-1, "Gift to outgoing volunteer", key="delta-down"), {inv.KERNEL_PHYSICAL_DELTA: -1}),
        (lambda: _council(3, key="delta-council"), {inv.COUNCIL_ON_ORDER_DELTA: 3}),
    ],
    ids=["receipt", "adjust-up", "adjust-down", "council-on-order"],
)
def test_stock_only_movements_move_only_stock_quantities(
    world: Dict[str, Any],
    inventory_table: Any,
    run: Callable[[], Any],
    expected: Dict[str, int],
) -> None:
    """No stock-only mutation moves a custody or event-allocation quantity.

    ``withScoutDelta`` and ``assignedDelta`` are the two that would name custody or a Show & Sell
    allocation the caller never asked for, so an exercised delta set that names either is a write
    into a balance this surface does not own.
    """
    _seed_balance(inventory_table, physical=10)
    _ok(run())

    movements = _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)
    assert len(movements) == 1
    movement = movements[0]
    exercised = {
        name: int(movement[name]) for name in sorted(inv.MOVEMENT_DELTA_ATTRIBUTES) if int(movement.get(name, 0) or 0)
    }
    assert exercised == expected
    kind = str(movement[inv.MOVEMENT_TYPE_ATTRIBUTE])
    assert set(exercised) <= inv.MOVEMENT_ALLOWED_DELTAS[kind], f"{kind} moved a delta it does not own"


def test_a_stock_only_mutation_leaves_a_scouts_custody_untouched(world: Dict[str, Any], inventory_table: Any) -> None:
    """A Scout who holds stock keeps holding exactly that stock through a stock-only write.

    "No Scout credit effect" is easy to assert when no Scout exists, so the custody row is created
    first and fingerprinted: the receipt, the adjustment, and the on-order change all run against a
    Scout who is holding two of the same product.
    """
    _seed_balance(inventory_table, physical=10)
    _ok(_issue(2, key="custody-issue"))
    custody_before = _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)
    assert len(custody_before) == 1
    assert int(custody_before[0][inv.WITH_SCOUT_QTY]) == 2

    _ok(_receipt(3, key="custody-receipt", occurred_at=MORNING))
    _ok(_adjust(-1, "Trade with Troop 7150; money settled outside app", key="custody-trade", occurred_at=MORNING))
    _ok(_council(2, key="custody-council", occurred_at=MORNING))

    assert _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE) == custody_before
    stock_movements = [
        row
        for row in _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)
        if row.get(inv.MOVEMENT_TYPE_ATTRIBUTE) in STOCK_ONLY_MOVEMENTS
    ]
    assert len(stock_movements) == 3
    for movement in stock_movements:
        assert int(movement.get(inv.WITH_SCOUT_DELTA, 0) or 0) == 0, (
            f"{movement[inv.MOVEMENT_TYPE_ATTRIBUTE]} moved custody"
        )
    assert (
        sum(int(row.get(inv.WITH_SCOUT_QTY, 0) or 0) for row in _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)) == 2
    )


def test_the_stock_only_trail_is_the_plan_s_two_four_three(world: Dict[str, Any], inventory_table: Any) -> None:
    """SS-SM-03 steps 4-6 in numbers: 2 received, a +2 trade, a -1 gift, and no money anywhere."""
    _seed_balance(inventory_table, physical=0)
    after_receipt = _ok(_receipt(2, key="plan-receipt", occurred_at=MORNING))
    after_trade = _ok(
        _adjust(2, "Trade with Troop 7150; money settled outside app", key="plan-trade", occurred_at=AFTERNOON)
    )
    after_gift = _ok(_adjust(-1, "Gift to outgoing volunteer", key="plan-gift", occurred_at=AFTERNOON))

    assert [
        after_receipt["kernelPhysicalQty"],
        after_trade["kernelPhysicalQty"],
        after_gift["kernelPhysicalQty"],
    ] == [2, 4, 3]
    balance = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]
    assert int(balance[inv.SOLD_IN_POSSESSION_QTY]) == 0
    assert inv.derived_inventory_quantities(balance, [], [])["totalUnitOwnedUndeliveredQty"] == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_balance(
    inventory_table: Any, *, physical: int, product_id: str = PRODUCT, campaign: str = CAMPAIGN
) -> Dict[str, Any]:
    item = inv.build_inventory_balance_item(
        unit_campaign_id=campaign,
        product_id=product_id,
        kernel_physical_qty=physical,
        sold_in_possession_qty=0,
        council_on_order_qty=0,
        now_iso=MORNING,
    )
    inventory_table.put_item(Item=item)
    return item


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload
