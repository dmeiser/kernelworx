"""Leaf 4.6.2 — the sale and We Owe mechanics, walked one resolver turn at a time.

§4.6.2 asks for the six mechanics of §7.1 to be automated together: the exact
unavailable-disabled rejection, the enabled mixed sale, a partial reservation, a Kernel
fulfillment, an external fulfillment, and the CLOSED/FULFILLED arithmetic with **zero
unexplained movements**. ``test_show_and_sell_sales.py`` and ``test_show_and_sell_we_owe.py``
prove each mechanic against a minimal scenario of its own, and
``test_show_sell_stage4_fixtures.py`` proves the finished ``SS-SM-07`` lane adds up. What
neither does is the thing this module is for: the *sequence*, with the stock picture
re-read after every turn, so a quantity that moved one step too early or one step too late
is caught at the step where it happened.

The lane is the smoke plan's (``tests/unit/show_sell_stage4_fixtures.py``): 3 Chocolate and
1 Butter received, 2 Chocolate and 1 Butter assigned to ``Church on Elm``, and Quinn's
$75 mixed line — 1 Chocolate handed over, 2 Chocolate owed, one of them covered by the
single unassigned box. Every leg therefore moves a number that has a second place it must
agree with:

- the disabled refusal names the exact products and quantities it refuses, and the shelf,
  the allocation, the event version and the ledger are exactly as they were;
- the mixed sale moves the sale, the allocation and the obligation in one turn and reserves
  nothing — ``uncoveredQty`` is the whole obligation until someone moves stock;
- a partial reservation moves ``soldInPossessionQty`` and the shelf not at all, and its
  bound is unassigned stock, not remaining quantity;
- a Kernel fulfillment moves shelf and possession together and touches no sale, credit or
  revision row; a Council fulfillment moves the obligation only and writes no movement;
- the obligation reaches ``CLOSED``/``FULFILLED`` at zero remaining **and** zero reserved;
- and at the end the whole ledger is explained: every movement row is one of the lane's
  five triggers, each delta column adds up to the derived quantity, and nothing the lane
  never did appears in the trail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import pytest

from src.handlers.unit_operations import (
    FULFILL_WE_OWE_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import assert_is_error, unit_operation_event
from tests.unit.show_sell_stage4_fixtures import (
    ADMIN,
    BUTTER,
    CHOCOLATE,
    DEFAULT_LANE,
    SALES_CAMPAIGN,
    SalesLane,
    assign_stock,
    attempt_sale,
    create_church_on_elm,
    enable_we_owe,
    fulfill_we_owe,
    product_rows,
    record_stock,
    reserve_we_owe,
    sales_evidence,
    seed_sales_lane,
    stock_picture,
)

#: Each delta column of the ledger, and the balance or derived quantity it has to sum to.
#: Stated here rather than borrowed so this module's verdict is its own arithmetic.
_LEDGER_TARGETS: Dict[str, str] = {
    inv.KERNEL_PHYSICAL_DELTA: inv.KERNEL_PHYSICAL_QTY,
    inv.SOLD_POSSESSION_DELTA: inv.SOLD_IN_POSSESSION_QTY,
    inv.COUNCIL_ON_ORDER_DELTA: inv.COUNCIL_ON_ORDER_QTY,
}


@pytest.fixture
def lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """Stock received and assigned to a We-Owe-disabled ``Church on Elm``.

    Deliberately stopped one turn before We Owe is enabled: the first thing §4.6.2 checks
    is what a sale may ask for while the flag is still off, and a fixture that had already
    enabled it could not answer that.
    """
    seed_sales_lane(units_table, unit_campaigns_table, catalogs_table, lane=DEFAULT_LANE)
    event_id = create_church_on_elm(DEFAULT_LANE)
    record_stock(DEFAULT_LANE)
    assign_stock(event_id, DEFAULT_LANE)
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
        "eventId": event_id,
    }


# --- Readers --------------------------------------------------------------------


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload


def _turn(field: str, mutation: Dict[str, Any]) -> Any:
    """One resolver turn, answered raw so a refusal can be inspected instead of asserted away."""
    return handle_unit_operation(unit_operation_event(field, ADMIN, input=mutation), None)


def _reserve(we_owe_id: str, target: int) -> Any:
    """``setWeOweReservation`` without the success wrapper — the bound refusals need the answer."""
    version = int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])
    return _turn(
        SET_WE_OWE_RESERVATION_FIELD,
        {
            "weOweId": we_owe_id,
            "targetReservedQty": target,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": DEFAULT_LANE.key(f"we-owe-reserve-{target}")},
        },
    )


def _fulfill(we_owe_id: str, source: str, *, key: str, quantity: int) -> Any:
    """``fulfillWeOwe`` without the success wrapper."""
    version = int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])
    return _turn(
        FULFILL_WE_OWE_FIELD,
        {
            "weOweId": we_owe_id,
            "quantity": quantity,
            "source": source,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": DEFAULT_LANE.key(key)},
        },
    )


def _picture(world: Dict[str, Any], product_id: str, lane_id: SalesLane = DEFAULT_LANE) -> Dict[str, Any]:
    return stock_picture(world["inventory"], lane_id.sales_campaign, product_id)


def _obligation(world: Dict[str, Any], we_owe_id: str) -> Dict[str, Any]:
    return sm.we_owe_payload(sm.load_we_owe_by_id_or_not_found(we_owe_id))


def _obligations(world: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [sm.we_owe_payload(row) for row in ssm.event_we_owe_rows(str(world["eventId"]))]


def _quinn(world: Dict[str, Any]) -> str:
    """The lane's one obligation id, after Quinn's mixed line."""
    answer = _ok(
        attempt_sale(
            str(world["eventId"]),
            key="sale-quinn",
            buyer="Quinn WeOwe",
            lines=[{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 2}],
            method="OTHER",
            other_details="Apple Pay; Kernel reimbursed unit by Venmo",
        )
    )
    return _quinn_obligation_id(answer)


def _quinn_obligation_id(answer: Mapping[str, Any]) -> str:
    obligations = answer.get("obligations") or []
    assert len(obligations) == 1, f"one We Owe line owes one obligation: {answer!r}"
    return str(obligations[0][sm.WE_OWE_ID_ATTRIBUTE])


def _movements(world: Dict[str, Any], product_id: str, lane_id: SalesLane = DEFAULT_LANE) -> List[Dict[str, Any]]:
    rows = product_rows(world["inventory"], lane_id.sales_campaign, product_id)
    return [row for row in rows if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE]


def _kernel_movement_id(world: Dict[str, Any], history: List[Dict[str, Any]]) -> Any:
    """The movement id a Kernel fulfillment record names, read back from the ledger."""
    record = sm.we_owe_fulfillment_payload(history[0])
    movement_id = record[sm.FULFILLMENT_MOVEMENT_ATTRIBUTE]
    assert movement_id in {row[inv.MOVEMENT_ID_ATTRIBUTE] for row in _movements(world, CHOCOLATE)}
    return movement_id


def _ledger(world: Dict[str, Any], product_id: str) -> Dict[str, Dict[str, int]]:
    """``movementType -> {delta column: total}`` for one product, zero deltas dropped."""
    ledger: Dict[str, Dict[str, int]] = {}
    for row in _movements(world, product_id):
        kind = str(row[inv.MOVEMENT_TYPE_ATTRIBUTE])
        bucket = ledger.setdefault(kind, {})
        for column in inv.MOVEMENT_DELTA_ATTRIBUTES:
            value = int(row.get(column, 0) or 0)
            if value:
                bucket[column] = bucket.get(column, 0) + value
        if not bucket:
            bucket["(no delta)"] = 0
    return ledger


# --- The unavailable-disabled rejection ------------------------------------------


def test_an_owed_quantity_on_an_event_that_did_not_enable_we_owe_is_refused_exactly(
    lane: Dict[str, Any],
) -> None:
    """SALE-M-01-03: the refusal names the line it refuses and writes nothing anywhere else."""
    event_id = str(lane["eventId"])
    before = {product: _picture(lane, product) for product in (CHOCOLATE, BUTTER)}
    event_before = ssm.load_show_and_sell_or_not_found(event_id)

    refused = attempt_sale(
        event_id,
        key="butter-owed",
        buyer="Sam Split",
        lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 1}],
        method="OTHER",
        other_details="$10 cash + $10 Venmo",
    )
    error = assert_is_error(refused, "CONFLICT")
    assert "This event does not offer We Owe" in error["message"]
    assert error["message"].endswith(BUTTER), "the refusal names the line to change, not just the rule"
    assert CHOCOLATE not in error["message"], "a line that asks for nothing owed is not part of the refusal"

    assert _obligations(lane) == []
    assert sm.event_sale_rows(event_id) == []
    assert _picture(lane, BUTTER) == before[BUTTER]
    assert _picture(lane, CHOCOLATE) == before[CHOCOLATE]
    assert _ledger(lane, BUTTER) == {"RECEIPT": {"kernelPhysicalDelta": 1}, "EVENT_ASSIGN": {"assignedDelta": 1}}
    after = ssm.load_show_and_sell_or_not_found(event_id)
    assert after[ssm.VERSION_ATTRIBUTE] == event_before[ssm.VERSION_ATTRIBUTE]


def test_the_same_line_is_accepted_the_turn_we_owe_is_enabled(lane: Dict[str, Any]) -> None:
    """The refusal is about the event's flag, so flipping the flag is the whole fix."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)

    answer = _ok(
        attempt_sale(
            event_id,
            key="butter-owed",
            buyer="Sam Split",
            lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 1}],
            method="OTHER",
            other_details="$10 cash + $10 Venmo",
        )
    )
    obligation = _obligations(lane)[0]
    assert answer["sale"][sm.TOTAL_CENTS_ATTRIBUTE] == 4000, "the handed box and the owed box are both sold"
    assert (obligation["productId"], obligation["originalQty"], obligation["uncoveredQty"]) == (BUTTER, 1, 1)
    assert obligation["valueCentsSnapshot"] == 2000, "the obligation carries the price of the box it owes"
    butter = _picture(lane, BUTTER)
    assert butter["kernelPhysicalQty"] == 0, "the handed-over box left the shelf"
    assert butter["soldInPossessionQty"] == 0, "the owed box did not"
    assert butter["unassignedKernelQty"] == 0


# --- The enabled mixed sale ------------------------------------------------------


def test_the_mixed_sale_moves_sale_allocation_and_obligation_in_one_turn_and_reserves_nothing(
    lane: Dict[str, Any],
) -> None:
    """SALE-M-01-03, AC-19, AC-20: 1 handed over, 2 owed, and only the first is stock's problem."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)

    we_owe_id = _quinn(lane)
    obligation = _obligation(lane, we_owe_id)
    chocolate = _picture(lane, CHOCOLATE)

    assert (chocolate["kernelPhysicalQty"], chocolate["soldInPossessionQty"]) == (2, 0)
    assert (chocolate["assignedOpenQty"], chocolate["unassignedKernelQty"]) == (1, 1)
    assert (
        obligation["originalQty"],
        obligation["fulfilledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
        obligation["status"],
        obligation["closeReason"],
    ) == (2, 0, 0, 2, 2, sm.WE_OWE_STATUS_OPEN, None)
    assert obligation["buyerName"] == "Quinn WeOwe"
    assert (obligation["productId"], obligation["productNameSnapshot"]) == (
        CHOCOLATE,
        f"Chocolate Popcorn {DEFAULT_LANE.data_id}",
    )
    assert obligation["valueCentsSnapshot"] == 5000, "2 Chocolate at $25.00"

    assert _ledger(lane, CHOCOLATE) == {
        "RECEIPT": {"kernelPhysicalDelta": 3},
        "EVENT_ASSIGN": {"assignedDelta": 2},
        "EVENT_IMMEDIATE_SALE": {"kernelPhysicalDelta": -1, "assignedDelta": -1},
    }, "the owed quantity has no movement yet — reserving it is a separate decision"


def test_the_mixed_sale_answer_names_the_obligation_the_we_owe_desk_will_act_on(lane: Dict[str, Any]) -> None:
    """AC-20: the sale answer and the read list agree because they read the same row."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)

    answered = _obligations(lane)
    assert [row["weOweId"] for row in answered] == [we_owe_id]
    assert answered == [_obligation(lane, we_owe_id)]

    evidence = sales_evidence(lane["inventory"], lane["show_and_sells"], event_id, lane=DEFAULT_LANE)
    assert [row["weOweId"] for row in evidence["obligations"]] == [we_owe_id]
    assert evidence["expectedCashCents"] == 0, "an Other sale puts nothing in the drawer expectation"


# --- Partial reservation ---------------------------------------------------------


def test_a_partial_reservation_moves_possession_and_leaves_the_shelf_the_sale_and_the_history_alone(
    lane: Dict[str, Any],
) -> None:
    """OWE-M-01-01, OWE-04: 1 of the 2 owed Chocolate is held out of 1 unassigned box."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    before_sale_rows = [dict(row) for row in sm.event_sale_rows(event_id)]
    shelf = _picture(lane, CHOCOLATE)

    _ok(reserve_we_owe(we_owe_id, target=1))
    obligation = _obligation(lane, we_owe_id)
    chocolate = _picture(lane, CHOCOLATE)

    assert (chocolate["kernelPhysicalQty"], shelf["kernelPhysicalQty"]) == (2, 2), "the shelf did not move"
    assert chocolate["soldInPossessionQty"] == 1
    assert chocolate["unassignedKernelQty"] == 0, "the last unassigned box is now spoken for"
    assert (obligation["reservedQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (1, 2, 1)
    assert (obligation["fulfilledQty"], obligation["status"]) == (0, sm.WE_OWE_STATUS_OPEN)

    assert [dict(row) for row in sm.event_sale_rows(event_id)] == before_sale_rows
    assert _ledger(lane, CHOCOLATE)["WE_OWE_RESERVE"] == {"soldPossessionDelta": 1}


def test_a_reservation_above_unassigned_stock_is_refused_at_the_bound_it_names(lane: Dict[str, Any]) -> None:
    """OWE-M-01-02: the bound is unassigned stock, not remaining quantity — 1 box, so 1 unit."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    before = _picture(lane, CHOCOLATE)

    refused = assert_is_error(_reserve(we_owe_id, 2), "CONFLICT")
    assert "Only 1 unassigned kernels are available" in refused["message"], "the bound is stock, not the ask"
    assert _obligation(lane, we_owe_id)["reservedQty"] == 0
    assert _picture(lane, CHOCOLATE) == before
    assert "WE_OWE_RESERVE" not in _ledger(lane, CHOCOLATE)


def test_a_council_may_only_supply_what_no_box_covers(lane: Dict[str, Any]) -> None:
    """OWE-M-02-02: after the reservation, the lane's uncovered count is the external ceiling."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    _ok(reserve_we_owe(we_owe_id, target=1))
    shelf = _picture(lane, CHOCOLATE)

    refused = assert_is_error(
        _fulfill(we_owe_id, sm.WE_OWE_SOURCE_EXTERNAL, key="council-too-much", quantity=2), "CONFLICT"
    )
    assert "Only 1 of this obligation is uncovered" in refused["message"]
    assert "release the reservation on the covered portion" in refused["message"]

    obligation = _obligation(lane, we_owe_id)
    assert (obligation["fulfilledQty"], obligation["status"]) == (0, sm.WE_OWE_STATUS_OPEN)
    assert _picture(lane, CHOCOLATE) == shelf
    assert "WE_OWE_FULFILL" not in _ledger(lane, CHOCOLATE)


# --- Kernel and external fulfillment --------------------------------------------


def test_a_kernel_fulfillment_moves_shelf_and_possession_together_and_never_the_sale(
    lane: Dict[str, Any],
) -> None:
    """OWE-M-02-01: one box leaves the shelf and the possession in the same transaction."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    _ok(reserve_we_owe(we_owe_id, target=1))
    before_sale_rows = [dict(row) for row in sm.event_sale_rows(event_id)]
    sale_id = str(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.SALE_ID_ATTRIBUTE])

    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_KERNEL, key="kernel-fulfill"))
    obligation = _obligation(lane, we_owe_id)
    chocolate = _picture(lane, CHOCOLATE)

    assert (chocolate["kernelPhysicalQty"], chocolate["soldInPossessionQty"]) == (1, 0)
    assert (obligation["fulfilledQty"], obligation["reservedQty"], obligation["remainingQty"]) == (1, 0, 1)
    assert (obligation["uncoveredQty"], obligation["status"]) == (1, sm.WE_OWE_STATUS_OPEN)

    assert [dict(row) for row in sm.event_sale_rows(event_id)] == before_sale_rows
    assert sm.sale_revision_rows(event_id, sale_id) == [], "fulfilling is not correcting"
    assert _ledger(lane, CHOCOLATE)["WE_OWE_FULFILL"] == {
        "kernelPhysicalDelta": -1,
        "soldPossessionDelta": -1,
    }
    history = sm.we_owe_fulfillment_history(event_id, we_owe_id)
    assert [sm.we_owe_fulfillment_payload(row)["inventoryMovementId"] for row in history] == [
        _kernel_movement_id(lane, history)
    ]


def test_an_external_fulfillment_moves_the_obligation_only_and_writes_no_movement(
    lane: Dict[str, Any],
) -> None:
    """OWE-M-02-02, OWE-07: the Council's box never was the Kernel's stock, so nothing moves."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    _ok(reserve_we_owe(we_owe_id, target=1))
    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_KERNEL, key="kernel-fulfill"))
    shelf = _picture(lane, CHOCOLATE)
    movements_before = [row[inv.MOVEMENT_ID_ATTRIBUTE] for row in _movements(lane, CHOCOLATE)]

    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_EXTERNAL, key="council-fulfill"))
    obligation = _obligation(lane, we_owe_id)

    assert (obligation["fulfilledQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (2, 0, 0)
    assert _picture(lane, CHOCOLATE) == shelf, "no shelf, no possession, no allocation"
    assert [row[inv.MOVEMENT_ID_ATTRIBUTE] for row in _movements(lane, CHOCOLATE)] == movements_before

    history = [sm.we_owe_fulfillment_payload(row) for row in sm.we_owe_fulfillment_history(event_id, we_owe_id)]
    assert [(row["quantity"], row["source"]) for row in history] == [(1, "KERNEL_STOCK"), (1, "EXTERNAL_COUNCIL")]
    assert history[1][sm.FULFILLMENT_MOVEMENT_ATTRIBUTE] is None, "an external record has no movement to name"


# --- CLOSED / FULFILLED arithmetic and the ledger --------------------------------


def test_the_obligation_closes_at_zero_remaining_and_zero_reserved_with_the_fulfilled_reason(
    lane: Dict[str, Any],
) -> None:
    """OWE-M-02-03: the two zeros and the reason, from the row rather than the answer."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    _ok(reserve_we_owe(we_owe_id, target=1))
    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_KERNEL, key="kernel-fulfill"))

    assert _obligation(lane, we_owe_id)[sm.STATUS_ATTRIBUTE] == sm.WE_OWE_STATUS_OPEN
    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_EXTERNAL, key="council-fulfill"))

    row = sm.load_we_owe_by_id_or_not_found(we_owe_id)
    obligation = sm.we_owe_payload(row)
    assert (
        obligation["originalQty"],
        obligation["fulfilledQty"],
        obligation["cancelledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
    ) == (2, 2, 0, 0, 0, 0)
    assert (obligation["status"], obligation["closeReason"]) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_FULFILLED)
    assert obligation["closedAt"] is not None and obligation["version"] == 4

    still_open = [
        payload["weOweId"]
        for payload in _obligations(lane)
        if payload["status"] == sm.WE_OWE_STATUS_CLOSED and payload["closeReason"] != sm.WE_OWE_CLOSE_FULFILLED
    ]
    assert still_open == []


def test_every_movement_the_lane_wrote_is_explained_by_a_trigger_and_adds_up_to_the_balance(
    lane: Dict[str, Any],
) -> None:
    """§4.6.2's zero-unexplained-movements clause, read off the whole campaign ledger."""
    event_id = str(lane["eventId"])
    enable_we_owe(event_id)
    we_owe_id = _quinn(lane)
    sale_id = str(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.SALE_ID_ATTRIBUTE])
    _ok(reserve_we_owe(we_owe_id, target=1))
    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_KERNEL, key="kernel-fulfill"))
    _ok(fulfill_we_owe(we_owe_id, sm.WE_OWE_SOURCE_EXTERNAL, key="council-fulfill"))

    fulfillment_ids = {
        str(sm.we_owe_fulfillment_payload(row)[sm.FULFILLMENT_ID_ATTRIBUTE])
        for row in sm.we_owe_fulfillment_history(event_id, we_owe_id)
    }

    # Every movement the lane did, and nothing else: a movement with no trigger, a second
    # movement for one decision, or a delta the movement type cannot carry is unexplained.
    triggers = {
        "RECEIPT": {},
        "EVENT_ASSIGN": {ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id},
        "EVENT_IMMEDIATE_SALE": {ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id, sm.SALE_ID_ATTRIBUTE: sale_id},
        "WE_OWE_RESERVE": {sm.WE_OWE_ID_ATTRIBUTE: we_owe_id},
        "WE_OWE_FULFILL": {sm.WE_OWE_ID_ATTRIBUTE: we_owe_id},
    }
    unexplained: List[str] = []
    rows = [row for product_id in (CHOCOLATE, BUTTER) for row in _movements(lane, product_id)]
    for row in rows:
        kind = str(row[inv.MOVEMENT_TYPE_ATTRIBUTE])
        if kind not in triggers:
            unexplained.append(f"{kind} has no trigger in this lane")
            continue
        for attribute, expected in triggers[kind].items():
            if str(row.get(attribute) or "") != expected:
                unexplained.append(f"{kind} names {row.get(attribute)!r} for {attribute}, expected {expected!r}")
        allowed = inv.MOVEMENT_ALLOWED_DELTAS[kind]
        for column in inv.MOVEMENT_DELTA_ATTRIBUTES:
            if int(row.get(column, 0) or 0) and column not in allowed:
                unexplained.append(f"{kind} may not move {column}")
        for link in inv.MOVEMENT_REQUIRED_LINKS[kind]:
            if row.get(link) is None:
                unexplained.append(f"{kind} does not name its {link}")
        if kind == "WE_OWE_FULFILL" and str(row.get(sm.FULFILLMENT_ID_ATTRIBUTE)) not in fulfillment_ids:
            unexplained.append("a WE_OWE_FULFILL movement names no fulfillment of this obligation")

    assert unexplained == []
    assert len(rows) == 7, [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in rows]
    assert _ledger(lane, CHOCOLATE) == {
        "RECEIPT": {"kernelPhysicalDelta": 3},
        "EVENT_ASSIGN": {"assignedDelta": 2},
        "EVENT_IMMEDIATE_SALE": {"kernelPhysicalDelta": -1, "assignedDelta": -1},
        "WE_OWE_RESERVE": {"soldPossessionDelta": 1},
        "WE_OWE_FULFILL": {"kernelPhysicalDelta": -1, "soldPossessionDelta": -1},
    }
    assert _ledger(lane, BUTTER) == {
        "RECEIPT": {"kernelPhysicalDelta": 1},
        "EVENT_ASSIGN": {"assignedDelta": 1},
    }

    for product_id in (CHOCOLATE, BUTTER):
        rows_by_product = _movements(lane, product_id)
        balance = next(
            row
            for row in product_rows(lane["inventory"], SALES_CAMPAIGN, product_id)
            if row.get("entityType") == inv.BALANCE_ENTITY_TYPE
        )
        for delta, quantity in _LEDGER_TARGETS.items():
            moved = sum(int(row.get(delta, 0) or 0) for row in rows_by_product)
            assert moved == int(balance.get(quantity, 0) or 0), f"{product_id}: sum({delta}) = {moved}"

    evidence = sales_evidence(lane["inventory"], lane["show_and_sells"], event_id, lane=DEFAULT_LANE)
    assert evidence["movementViolations"] == []
    assert evidence["poolCents"] == 7500
    assert evidence["allocationRemainingQty"] == 2, "1 Chocolate and 1 Butter are still on the table"
