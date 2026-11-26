"""Leaf 4.6.8 — the whole ``SS-SM-07`` lane reconciles: movements to obligations, sales to the pool.

Checklist §4.6.8 asks for "movement/obligation reconciliation" as an evidence line of its
own, after §4.6.2 proved the per-turn ledger. This module closes the loop the other way:
it runs the **complete** smoke lane — both refusals, three sales, the QR attachment, work
confirmation, the reservation and both fulfillment sources — and then reconciles every
stored row against every other row that has to agree with it:

- each movement names the trigger it belongs to and only the delta columns that trigger's
  movement type may carry (:func:`src.utils.inventory_models.movement_row_violations` is
  the production rule, run over the lane's whole ledger rather than one product's);
- each obligation reconciles arithmetically (``original - fulfilled - cancelled ==
  remaining``, ``reserved <= remaining``, ``uncovered == remaining - reserved``) **and**
  against its movement trail: the ``WE_OWE_RESERVE`` total equals what was set, the
  ``WE_OWE_FULFILL`` deltas equal the fulfilled history, and no ``WE_OWE_RELEASE`` exists
  because this lane's reservation ended in a fulfillment, not a correction;
- the sale rows reconcile to the pool the plan fixes — three sales totalling ``$120.00``
  with ``expectedCashCents`` exactly ``$25.00`` — and each sale's line subtotals sum to
  its own ``totalCents``;
- and the balances still equal the sum of their movements after everything
  (:func:`src.utils.show_sell_stage4_fixtures.movement_trail_violations`, with the
  ``assignedDelta`` column included, which only Stage 4's lane can demand).

A row that reconciles everywhere it is looked at twice (sale → obligation → movement →
balance) is what "zero unexplained" means at lane scale rather than per turn.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.utils import inventory_models as inv
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_stage4_fixtures import (
    DEFAULT_LANE,
    movement_trail_violations,
    product_rows,
    setup_ss_sm_07,
    stock_picture,
)


@pytest.fixture
def full_lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
    s3_bucket: Any,
) -> Dict[str, Any]:
    """The finished ``SS-SM-07`` fixture: every plan step run through its resolver."""
    world = setup_ss_sm_07(
        units_table,
        unit_campaigns_table,
        catalogs_table,
        inventory_table,
        show_and_sells_table,
        s3_client=s3_bucket,
    )
    world["inventory"] = inventory_table
    world["show_and_sells"] = show_and_sells_table
    return world


def _movements(full_lane: Dict[str, Any], product_id: str) -> Dict[str, Dict[str, int]]:
    """``movementType -> {delta column: total}`` for one product across the whole lane."""
    ledger: Dict[str, Dict[str, int]] = {}
    for row in product_rows(full_lane["inventory"], DEFAULT_LANE.sales_campaign, product_id):
        if row.get("entityType") != inv.MOVEMENT_ENTITY_TYPE:
            continue
        kind = str(row[inv.MOVEMENT_TYPE_ATTRIBUTE])
        bucket = ledger.setdefault(kind, {})
        for column in inv.MOVEMENT_DELTA_ATTRIBUTES:
            value = int(row.get(column, 0) or 0)
            if value:
                bucket[column] = bucket.get(column, 0) + value
    return ledger


# --- Movement rows against their triggers ------------------------------------------


def test_every_movement_row_in_the_finished_lane_passes_the_production_row_rules(
    full_lane: Dict[str, Any],
) -> None:
    """Production's own validator, run over every movement the lane wrote — none exempt."""
    checked = 0
    for product_id in (DEFAULT_LANE.chocolate, DEFAULT_LANE.butter):
        for row in product_rows(full_lane["inventory"], DEFAULT_LANE.sales_campaign, product_id):
            if row.get("entityType") != inv.MOVEMENT_ENTITY_TYPE:
                continue
            violations = inv.movement_row_violations(row)
            assert violations == [], f"movement {row.get(inv.MOVEMENT_ID_ATTRIBUTE)}: {violations}"
            checked += 1
    assert checked == 9, (
        "2 receipts + 2 assigns + the three sales + the reservation + the Kernel fulfillment — "
        "and nothing else: the count itself proves no ninth movement snuck in"
    )


def test_both_product_ledgers_sum_to_their_balances_with_zero_unexplained(
    full_lane: Dict[str, Any],
) -> None:
    """The §4.6.2 clause at lane scale: every delta column reconciles to the stored balance."""
    for product_id in (DEFAULT_LANE.chocolate, DEFAULT_LANE.butter):
        assert movement_trail_violations(full_lane["inventory"], DEFAULT_LANE.sales_campaign, product_id) == []


# --- Obligation against movements and fulfillment history ----------------------------


def test_the_obligation_arithmetic_and_its_movement_trail_reconcile_item_by_item(
    full_lane: Dict[str, Any],
) -> None:
    """One obligation, three independent views: quantities, movements, fulfillment history."""
    obligation_id = str(full_lane["obligationId"])
    payload = sm.we_owe_payload(sm.load_we_owe_by_id_or_not_found(obligation_id))

    original, fulfilled, cancelled = (payload[k] for k in ("originalQty", "fulfilledQty", "cancelledQty"))
    reserved, remaining, uncovered = (payload[k] for k in ("reservedQty", "remainingQty", "uncoveredQty"))
    assert original - fulfilled - cancelled == remaining
    assert 0 <= reserved <= remaining
    assert uncovered == remaining - reserved
    assert (payload["status"], payload["closeReason"]) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_FULFILLED)

    obligation_movements = [
        mv
        for mv in product_rows(full_lane["inventory"], DEFAULT_LANE.sales_campaign, DEFAULT_LANE.chocolate)
        if mv.get("entityType") == inv.MOVEMENT_ENTITY_TYPE
        and str(mv.get(sm.WE_OWE_ID_ATTRIBUTE) or "") == obligation_id
    ]
    by_type: Dict[str, Dict[str, int]] = {}
    for mv in obligation_movements:
        bucket = by_type.setdefault(str(mv[inv.MOVEMENT_TYPE_ATTRIBUTE]), {})
        for column in inv.MOVEMENT_DELTA_ATTRIBUTES:
            value = int(mv.get(column, 0) or 0)
            if value:
                bucket[column] = bucket.get(column, 0) + value

    assert by_type["WE_OWE_RESERVE"] == {"soldPossessionDelta": 1}, "the one reservation the lane set"
    assert by_type["WE_OWE_FULFILL"] == {"kernelPhysicalDelta": -1, "soldPossessionDelta": -1}
    assert "WE_OWE_RELEASE" not in by_type, (
        "the reservation was consumed by the Kernel fulfillment, so no release row may exist"
    )

    history = [
        sm.we_owe_fulfillment_payload(row)
        for row in sm.we_owe_fulfillment_history(str(full_lane["eventId"]), obligation_id)
    ]
    assert sum(int(h["quantity"]) for h in history) == fulfilled == original
    kernel_records = [h for h in history if h["source"] == sm.WE_OWE_SOURCE_KERNEL]
    external_records = [h for h in history if h["source"] == sm.WE_OWE_SOURCE_EXTERNAL]
    assert len(kernel_records) == len(external_records) == 1
    kernel_movement_ids = {
        str(mv[inv.MOVEMENT_ID_ATTRIBUTE])
        for mv in obligation_movements
        if str(mv[inv.MOVEMENT_TYPE_ATTRIBUTE]) == inv.WE_OWE_FULFILL
    }
    assert kernel_records[0][sm.FULFILLMENT_MOVEMENT_ATTRIBUTE] in kernel_movement_ids
    assert external_records[0][sm.FULFILLMENT_MOVEMENT_ATTRIBUTE] is None


# --- Sales against the pool, the drawer expectation, and the shelf -------------------


def test_the_three_sales_reconcile_to_the_plan_pool_and_the_cash_expectation(
    full_lane: Dict[str, Any],
) -> None:
    """$120.00 of sales, $25.00 expected Cash, every line subtotal inside its own sale."""
    event_id = str(full_lane["eventId"])
    sale_rows = sm.event_sale_rows(event_id)
    assert len(sale_rows) == 3

    pool = 0
    for row in sale_rows:
        total = int(row[sm.TOTAL_CENTS_ATTRIBUTE])
        subtotals = sum(int(line[sm.SUBTOTAL_CENTS_ATTRIBUTE]) for line in row[sm.LINE_ITEMS_ATTRIBUTE])
        assert subtotals == total, f"sale {row[sm.SALE_ID_ATTRIBUTE]}: {subtotals} != {total}"
        pool += total
    assert pool == 12_000, "the plan's $120.00, summed from the rows rather than asserted beside them"

    expected_cash = sum(sm.sale_expected_cash_cents(row) for row in sale_rows)
    assert expected_cash == 2_500, "only Nora's Cash sale fills the drawer expectation"


def test_the_shelf_the_lane_ends_on_equals_what_the_movements_say_it_is(
    full_lane: Dict[str, Any],
) -> None:
    """3+1 received, 2+1 assigned, 3+1 sold, 1 Kernel box delivered: the balances fall out."""
    chocolate = stock_picture(full_lane["inventory"], DEFAULT_LANE.sales_campaign, DEFAULT_LANE.chocolate)
    butter = stock_picture(full_lane["inventory"], DEFAULT_LANE.sales_campaign, DEFAULT_LANE.butter)

    assert _movements(full_lane, DEFAULT_LANE.chocolate) == {
        "RECEIPT": {"kernelPhysicalDelta": 3},
        "EVENT_ASSIGN": {"assignedDelta": 2},
        "EVENT_IMMEDIATE_SALE": {"kernelPhysicalDelta": -2, "assignedDelta": -2},
        "WE_OWE_RESERVE": {"soldPossessionDelta": 1},
        "WE_OWE_FULFILL": {"kernelPhysicalDelta": -1, "soldPossessionDelta": -1},
    }
    assert _movements(full_lane, DEFAULT_LANE.butter) == {
        "RECEIPT": {"kernelPhysicalDelta": 1},
        "EVENT_ASSIGN": {"assignedDelta": 1},
        "EVENT_IMMEDIATE_SALE": {"kernelPhysicalDelta": -1, "assignedDelta": -1},
    }
    assert (chocolate["kernelPhysicalQty"], chocolate["soldInPossessionQty"]) == (0, 0)
    assert (butter["kernelPhysicalQty"], butter["soldInPossessionQty"]) == (0, 0)

    open_allocations = inv.campaign_allocation_rows(DEFAULT_LANE.sales_campaign)
    remaining = sum(int(row["remainingQty"]) for row in open_allocations)
    assert remaining == 0, (
        "2 Chocolate and 1 Butter were assigned and all three were sold or handed back: "
        "the allocation picture has nothing left to hold"
    )
    assert chocolate["assignedOpenQty"] == 0 and butter["assignedOpenQty"] == 0
