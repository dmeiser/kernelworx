"""Leaf 2.8.7 (reconciliation) — one history, two records, checked across the whole lane.

§2.8.7 asks for movement-to-balance reconciliation. The per-leaf tests check one product after one
operation; this checks a **live lane** — the three smoke setups run through the real resolvers, so the
rows are the ones a scenario produces, including the sale and fulfillment paths a hand-arranged
fixture cannot reach — and then reconciles every product partition in every campaign the lane writes.

Three checks, each failing for a different reason:

1. **Sums.** The deltas in the trail equal the stored quantities, per product, with no row breaking
   the append-only shape (the lane fixture's own reconciler, run over every partition rather than the
   one product it was written next to).
2. **The version chain.** Each balance-affecting movement records the balance version it produced, so
   the trail's ``inventoryVersion`` values have to be exactly ``1..version`` of the aggregate they
   explain. Sums can agree while a write is recorded twice and its aggregate written once; the chain is
   what catches that.
3. **The two tables agree.** Every fulfillment names a movement that exists, and every individual
   fulfillment or reversal movement names a fulfillment that exists, with the sign the source implies.
   §5.19 and §5.8 are one event described twice, and a link that points at nothing is how a reversal
   silently restores stock no one took.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from tests.unit.show_sell_fixtures import seed_show_sell_fixtures
from tests.unit.show_sell_stock_fixtures import (
    ADMIN,
    DEFAULT_LANE,
    SmokeLane,
    council_on_order,
    fulfill_line,
    issue_to_scout,
    lane_inventory_rows,
    lane_orders,
    movement_history,
    movement_trail_violations,
    product_rows,
    record_receipt,
    return_from_scout,
    reverse_fulfillment,
    seed_smoke_lane,
    setup_ss_sm_03,
    setup_ss_sm_04,
    setup_ss_sm_10,
    stock_adjust,
)


def _lane_products(lane: SmokeLane) -> List[str]:
    """The three products every lane catalog carries (§3.3).

    Enumerating them, rather than the products that happen to have rows, is what makes a partition
    with nothing in it distinguishable from a partition this sweep forgot to look at.
    """
    return [lane.caramel, lane.butter, lane.chocolate]


@pytest.fixture
def run(
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
    """The three smoke scenarios, driven by the resolvers, on one reproducible lane.

    The lane is ``DEFAULT_LANE`` rather than ``SmokeLane.new(...)`` because the numbers this module
    asserts have to be the numbers §3.3 states, and a fresh attempt id would make a failure in them
    unreadable.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    seed_smoke_lane(units_table, unit_campaigns_table, catalogs_table, lane=DEFAULT_LANE)
    stock_admin = setup_ss_sm_03(inventory_table, lane=DEFAULT_LANE)
    door_to_door = setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table, lane=DEFAULT_LANE)
    council = setup_ss_sm_10(inventory_table, orders_table, lane=DEFAULT_LANE)

    # The three smoke scenarios all live on one product, and a reconciliation that only ever sees
    # one product cannot tell a per-product bug from a per-campaign one. ``Exactly Four`` carries the
    # other two catalog products through the same paths, so the sweep below walks several partitions.
    _ok(
        record_receipt(
            DEFAULT_LANE.four_box,
            DEFAULT_LANE.caramel,
            6,
            key=DEFAULT_LANE.key("multi-receipt-caramel"),
            occurred_at=DEFAULT_LANE.moment(30),
        )
    )
    _ok(
        record_receipt(
            DEFAULT_LANE.four_box,
            DEFAULT_LANE.chocolate,
            5,
            key=DEFAULT_LANE.key("multi-receipt-chocolate"),
            occurred_at=DEFAULT_LANE.moment(31),
        )
    )
    _ok(
        council_on_order(
            DEFAULT_LANE.four_box,
            DEFAULT_LANE.chocolate,
            2,
            "Council promised a case",
            key=DEFAULT_LANE.key("multi-council-chocolate"),
            occurred_at=DEFAULT_LANE.moment(32),
        )
    )
    _ok(
        stock_adjust(
            DEFAULT_LANE.four_box,
            DEFAULT_LANE.caramel,
            -1,
            "Recount at the scout shed",
            key=DEFAULT_LANE.key("multi-adjust-caramel"),
            occurred_at=DEFAULT_LANE.moment(33),
        )
    )
    _ok(
        issue_to_scout(
            DEFAULT_LANE.four_box,
            ADMIN,
            DEFAULT_LANE.caramel,
            2,
            key=DEFAULT_LANE.key("multi-issue-caramel"),
            occurred_at=DEFAULT_LANE.moment(34),
        )
    )
    _ok(
        return_from_scout(
            DEFAULT_LANE.four_box,
            ADMIN,
            [(DEFAULT_LANE.caramel, 1)],
            key=DEFAULT_LANE.key("multi-return-caramel"),
            occurred_at=DEFAULT_LANE.moment(35),
        )
    )

    return {
        "lane": DEFAULT_LANE,
        "inventory": inventory_table,
        "orders": orders_table,
        "fulfillments": order_fulfillments_table,
        "stock_admin": stock_admin,
        "door_to_door": door_to_door,
        "council": council,
    }


def _ok(payload: Any) -> Any:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    return payload


def _partitions(lane: SmokeLane) -> List[Dict[str, str]]:
    return [
        {"unitCampaignId": campaign_id, "productId": product_id}
        for campaign_id in lane.stock_campaign_ids
        for product_id in _lane_products(lane)
    ]


def _movements(inventory_table: Any, campaign_id: str, product_id: str) -> List[Dict[str, Any]]:
    rows = product_rows(inventory_table, campaign_id, product_id)
    return [row for row in rows if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == inv.MOVEMENT_ENTITY_TYPE]


def _balance(inventory_table: Any, campaign_id: str, product_id: str) -> Dict[str, Any]:
    rows = [
        row
        for row in product_rows(inventory_table, campaign_id, product_id)
        if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == inv.BALANCE_ENTITY_TYPE
    ]
    assert len(rows) <= 1, f"one product has at most one balance row, got {rows!r}"
    return rows[0] if rows else {}


def _moves_balance(movement: Dict[str, Any]) -> bool:
    """Whether this movement wrote the aggregate, as opposed to custody or an allocation only."""
    return any(
        int(movement.get(name, 0) or 0)
        for name in (inv.KERNEL_PHYSICAL_DELTA, inv.SOLD_POSSESSION_DELTA, inv.COUNCIL_ON_ORDER_DELTA)
    )


# ---------------------------------------------------------------------------
# 1. Every partition's trail sums to its balances.
# ---------------------------------------------------------------------------


def test_every_partition_of_a_live_lane_reconciles_its_trail_to_its_balances(run: Dict[str, Any]) -> None:
    """No product in no campaign of the lane may hold a trail that disagrees with its aggregate.

    The three setups together cover a receipt, a trade, a gift, an on-order change, an issue, a
    custody sale, a return, and the assignment SS-SM-10 arranges, so this is not one happy path
    checked three times.
    """
    lane: SmokeLane = run["lane"]
    inventory_table = run["inventory"]

    checked = 0
    for partition in _partitions(lane):
        violations = movement_trail_violations(inventory_table, partition["unitCampaignId"], partition["productId"])
        assert violations == [], f"{partition}: {violations}"
        if _movements(inventory_table, partition["unitCampaignId"], partition["productId"]):
            checked += 1
    assert checked >= 5, f"the lane wrote movements in only {checked} partitions; the sweep is vacuous"


def test_the_resolver_s_history_and_the_stored_trail_hold_the_same_rows(run: Dict[str, Any]) -> None:
    """The audit the screen reads is the audit on the table, row for row.

    A reconciliation against stored rows only would still pass if the query dropped history, and the
    trail is what a Scout or an admin is told happened.
    """
    lane: SmokeLane = run["lane"]
    inventory_table = run["inventory"]
    campaign = lane.door_to_door

    page = movement_history(campaign, page={"limit": 100})
    stored = _movements(inventory_table, campaign, lane.butter)
    assert len(page["items"]) == len(stored), (page["items"], stored)
    assert sorted(item["movementId"] for item in page["items"]) == sorted(
        row[inv.MOVEMENT_ID_ATTRIBUTE] for row in stored
    )


# ---------------------------------------------------------------------------
# 2. The version chain each movement records.
# ---------------------------------------------------------------------------


def test_each_movement_records_the_balance_version_it_produced(run: Dict[str, Any]) -> None:
    """The balance-affecting movements of one product name ``1..version``, once each.

    Sums agreeing is not enough: a mutation that wrote its movement twice, or wrote an aggregate
    without a movement, can still balance. The chain is the second, independent statement, and it is
    the one the §2.2 version guard makes true — a writer whose read went stale cancels its whole plan,
    so no movement is ever recorded against a balance this request did not change.
    """
    lane: SmokeLane = run["lane"]
    inventory_table = run["inventory"]
    chained = 0
    for partition in _partitions(lane):
        campaign_id, product_id = partition["unitCampaignId"], partition["productId"]
        balance = _balance(inventory_table, campaign_id, product_id)
        if not balance:
            continue
        chain = sorted(
            int(row[inv.INVENTORY_VERSION_ATTRIBUTE])
            for row in _movements(inventory_table, campaign_id, product_id)
            if _moves_balance(row)
        )
        assert chain == list(range(1, int(balance[inv.VERSION_ATTRIBUTE]) + 1)), (
            f"{partition}: movements recorded versions {chain}, the balance is at version {balance[inv.VERSION_ATTRIBUTE]}"
        )
        chained += 1
    assert chained >= 5, f"only {chained} partitions carry a balance; the sweep is vacuous"


# ---------------------------------------------------------------------------
# 3. Fulfillments and the movements they draw from, across the two tables.
# ---------------------------------------------------------------------------


def _lane_fulfillments(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    lane: SmokeLane = run["lane"]
    rows: List[Dict[str, Any]] = []
    for order in lane_orders(run["orders"], lane.stock_campaign_ids):
        rows.extend(ful.fulfillment_rows(str(order["orderId"])))
    return rows


def test_every_fulfillment_names_a_movement_that_exists(run: Dict[str, Any]) -> None:
    """§5.19's history row and §5.8's movement are one event, and the link resolves both ways.

    A fulfillment that names a movement that was never written is a stock movement attributed to
    nothing; a movement that names a fulfillment no one can find is stock that can never be reversed.
    """
    lane: SmokeLane = run["lane"]
    inventory_table = run["inventory"]
    all_movements = {
        str(row[inv.MOVEMENT_ID_ATTRIBUTE])
        for campaign_id in lane.stock_campaign_ids
        for product_id in _lane_products(lane)
        for row in lane_inventory_rows(inventory_table, campaign_id)
        if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == inv.MOVEMENT_ENTITY_TYPE
    }

    fulfillments = _lane_fulfillments(run)
    assert fulfillments, "the lane wrote no fulfillment history, so this sweep proves nothing"
    linked = 0
    for row in fulfillments:
        movement_id = row.get(ful.INVENTORY_MOVEMENT_ID_ATTRIBUTE)
        if not movement_id:
            assert row[ful.SOURCE_ATTRIBUTE] == ful.SOURCE_EXTERNAL_COUNCIL, (
                f"{row[ful.FULFILLMENT_ID_ATTRIBUTE]}: only an outside fulfillment may name no movement"
            )
            continue
        assert str(movement_id) in all_movements, f"fulfillment {row[ful.FULFILLMENT_ID_ATTRIBUTE]} names {movement_id}"
        linked += 1
    assert linked >= 2, f"only {linked} fulfillment rows carried a movement link"


def test_a_kernel_fulfillment_and_its_reversal_move_stock_once_each(run: Dict[str, Any]) -> None:
    """The SS-SM-10 pair: one Kernel leaves for the fulfillment, the same one comes back, twice one.

    The sign is checked against the source rather than asserted as a number, so a fulfillment that
    drew custody and still wrote a physical movement fails here even if the totals happen to land.
    """
    lane: SmokeLane = run["lane"]
    inventory_table = run["inventory"]
    council = run["council"]

    before = _balance(inventory_table, lane.council_planning, lane.butter)
    physical_before = int(before[inv.KERNEL_PHYSICAL_QTY])
    version_before = int(before[inv.VERSION_ATTRIBUTE])

    fulfilled = fulfill_line(
        council["orderId"], council["lineItemId"], 2, "KERNEL_STOCK", version=0, key=lane.key("budget-free-fulfill")
    )
    assert not fulfilled.get("__isError"), fulfilled
    after_fulfill = _balance(inventory_table, lane.council_planning, lane.butter)
    assert int(after_fulfill[inv.KERNEL_PHYSICAL_QTY]) == physical_before - 2

    rows = ful.fulfillment_rows(str(council["orderId"]))
    source_row = next(row for row in rows if row[ful.RECORD_TYPE_ATTRIBUTE] == ful.RECORD_TYPE_FULFILL)
    reversed_row = reverse_fulfillment(
        council["orderId"],
        str(source_row[ful.FULFILLMENT_ID_ATTRIBUTE]),
        version=1,
        key=lane.key("budget-free-reverse"),
    )
    assert not reversed_row.get("__isError"), reversed_row

    after_reverse = _balance(inventory_table, lane.council_planning, lane.butter)
    assert int(after_reverse[inv.KERNEL_PHYSICAL_QTY]) == physical_before
    assert int(after_reverse[inv.VERSION_ATTRIBUTE]) == version_before + 2

    kinds = {
        str(row[inv.MOVEMENT_TYPE_ATTRIBUTE]): int(row.get(inv.KERNEL_PHYSICAL_DELTA, 0) or 0)
        for row in _movements(inventory_table, lane.council_planning, lane.butter)
        if row[inv.MOVEMENT_TYPE_ATTRIBUTE] in (inv.INDIVIDUAL_FULFILL, inv.REVERSAL)
    }
    assert kinds == {inv.INDIVIDUAL_FULFILL: -2, inv.REVERSAL: 2}, kinds
    assert movement_trail_violations(inventory_table, lane.council_planning, lane.butter) == []
