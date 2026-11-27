"""Leaf 4.6.3 — what a payment note may say, and what the cash drawer may count.

§4.6.3 asks for five things from the smoke plan's cash trail: the Other/split details stay
text, calculated expected Cash is ``$25``, a manual ``+$10`` yields ``$35``, the count is
``$34``, the discrepancy is ``-$1``, and an explanation is required. Those five sit on two
different stages of the delivery, and the split is not a choice this module makes:

- **Stage 4 owns spec §11.2 `CASH-01` and `CASH-02`.** Expected cash is calculated from the
  payment snapshot's ``methodCode`` and from nothing else, and "no cash-portion field is
  added to the sale". So the Other note is a string on one sale row, and no note about cash —
  however specific — moves the drawer. Every leg below that checks shipped behaviour checks
  exactly that.
- **`CASH-03` and `CASH-04` are Stage 5.** The adjustment with its reason, the actual count,
  the discrepancy and the explanation-before-approval rule are the ``CashReconciliation``
  record checklist §5.1.1 implements, and the Stage 4 SDL has no field to write any of them
  into: no ``cashAdjustmentCents``, no ``actualCashCents``, no ``discrepancyCents``, no
  explanation. What this module can honestly do for that half is pin the arithmetic the Stage
  5 validator will be held to — the same numbers the smoke plan states, carried by
  ``tests/unit/show_sell_stage4_fixtures.py`` so a Stage 5 test that disagrees with §4.6.3
  disagrees with the fixture — and name the field set that must be empty until then.

The lane is ``SS-SM-07`` (``tests/unit/show_sell_stage4_fixtures.py``): 3 Chocolate at $25 and
1 Butter at $20 received, 2 Chocolate and 1 Butter assigned to ``Church on Elm``, then Nora
Cash ($25, ``CASH``), Quinn WeOwe ($75, ``OTHER`` — "Apple Pay; Kernel reimbursed unit by
Venmo") and Sam Split ($20 Butter, ``OTHER`` — "$10 cash + $10 Venmo"). The pool is $120 and
the drawer is $25, and the difference between those two numbers is the whole point of the leaf.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CREATE_PAYMENT_METHOD_FIELD,
    CREATE_SALE_FIELD,
    SHOW_AND_SELL_SALES_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import assert_is_error, unit_operation_event
from tests.unit.show_sell_stage4_fixtures import (
    ACTUAL_CASH_CENTS,
    ADMIN,
    BUTTER,
    CASH_ADJUSTMENT_CENTS,
    CASH_ADJUSTMENT_REASON,
    CASH_EXPLANATION,
    CHOCOLATE,
    DEFAULT_LANE,
    SalesLane,
    assign_stock,
    attempt_sale,
    blocked_sales,
    create_church_on_elm,
    enable_we_owe,
    event_version,
    product_rows,
    record_stock,
    sales_evidence,
    seed_sales_lane,
    stock_picture,
)

#: The smoke plan's split note, verbatim: the cash half of it is the reason `CASH-02` exists.
SAM_SPLIT_NOTE = "$10 cash + $10 Venmo"

#: Quinn's note names two more methods and still contributes nothing.
QUINN_NOTE = "Apple Pay; Kernel reimbursed unit by Venmo"

#: What a sale row may look like to a reader who is not the payment model.
SNAPSHOT_FIELDS = {"methodCode", "displayName", "otherDetails"}


@pytest.fixture
def desk(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """The lane's three sales, after the plan's two refusals, with We Owe on.

    The refusals are part of the fixture because §4.6.3's number has to be reached through
    them: the plan's step 2 tries to sell 3 Chocolate to an event holding 2, and if that
    attempt left anything behind, the drawer would not be $25.
    """
    seed_sales_lane(units_table, unit_campaigns_table, catalogs_table, lane=DEFAULT_LANE)
    event_id = create_church_on_elm(DEFAULT_LANE)
    record_stock(DEFAULT_LANE)
    assign_stock(event_id, DEFAULT_LANE)
    blocked = blocked_sales(event_id, DEFAULT_LANE)
    enable_we_owe(event_id, DEFAULT_LANE)

    nora = _ok(
        attempt_sale(
            event_id,
            key="sale-nora",
            buyer="Nora Cash",
            lines=[{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 0}],
        )
    )
    quinn = _ok(
        attempt_sale(
            event_id,
            key="sale-quinn",
            buyer="Quinn WeOwe",
            lines=[{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 2}],
            method="OTHER",
            other_details=QUINN_NOTE,
        )
    )
    sam = _ok(
        attempt_sale(
            event_id,
            key="sale-sam",
            buyer="Sam Split",
            lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 0}],
            method="OTHER",
            other_details=SAM_SPLIT_NOTE,
        )
    )
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
        "eventId": event_id,
        "blocked": blocked,
        "sales": {"nora": nora, "quinn": quinn, "sam": sam},
    }


# --- Turns and readers -----------------------------------------------------------


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload


def _turn(field: str, mutation: Dict[str, Any]) -> Any:
    return handle_unit_operation(unit_operation_event(field, ADMIN, input=mutation), None)


def _sale_turn(mutation: Dict[str, Any]) -> Any:
    """One ``createShowAndSellSale`` attempt, answered raw so a refusal can be read."""
    return _turn(CREATE_SALE_FIELD, mutation)


def _sales_page(desk_state: Dict[str, Any], **arguments: Any) -> Dict[str, Any]:
    """The sale list as the desk screen reads it: the resolver's page, not a model call."""
    return _ok(
        handle_unit_operation(
            unit_operation_event(
                SHOW_AND_SELL_SALES_FIELD, ADMIN, arguments={"showAndSellId": desk_state["eventId"], **arguments}
            ),
            None,
        )
    )


def _drawer(desk_state: Dict[str, Any]) -> int:
    """The drawer the sale screen is built from: the sum of what the server answered per sale."""
    return sum(int(item["expectedCashCents"]) for item in _sales_page(desk_state)["items"])


def _stored_rows(desk_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sm.event_sale_rows(str(desk_state["eventId"]))


def _cash_named(names: Any) -> List[str]:
    """Every ``cash``-shaped name among these attributes or payload keys."""
    return sorted(name for name in names if "cash" in str(name).lower())


def _movements(desk_state: Dict[str, Any], product_id: str) -> List[Dict[str, Any]]:
    rows = product_rows(desk_state["inventory"], DEFAULT_LANE.sales_campaign, product_id)
    return [row for row in rows if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE]


def _by_buyer(desk_state: Dict[str, Any], buyer: str) -> Dict[str, Any]:
    matches = [
        sm.sale_payload(row) for row in _stored_rows(desk_state) if str(row.get(sm.BUYER_NAME_ATTRIBUTE) or "") == buyer
    ]
    assert len(matches) == 1, f"{buyer} owes exactly one sale: {[m['buyerName'] for m in matches]}"
    return matches[0]


# --- CASH-02: the split is one sale and one note ----------------------------------


def test_a_split_payment_is_one_sale_row_whose_note_is_the_only_record_of_the_split(desk: Dict[str, Any]) -> None:
    """AC-20, AC-31: "$10 cash + $10 Venmo" writes one sale, not two tenders and not a cash field."""
    sam = _by_buyer(desk, "Sam Split")
    assert sam["paymentMethodSnapshot"] == {
        "methodCode": "OTHER",
        "displayName": "Other",
        "otherDetails": SAM_SPLIT_NOTE,
    }, "the note is stored verbatim, and it is the only place the split exists"
    assert sam["totalCents"] == 2_000 and sam["expectedCashCents"] == 0
    assert len(sam["lineItems"]) == 1, "a split payment never splits the line either"
    line = sam["lineItems"][0]
    assert (line["productId"], line["immediateQty"], line["weOweQty"], line["subtotalCents"]) == (
        BUTTER,
        1,
        0,
        2_000,
    )

    stored = next(row for row in _stored_rows(desk) if row[sm.SALE_ID_ATTRIBUTE] == sam["saleId"])
    assert _cash_named(stored) == [], "CASH-02: no cash-portion field is added to the sale — not even a zero"
    assert set(stored[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]) == SNAPSHOT_FIELDS

    # The stock consequence is an ordinary sale of one Butter: the split note adds no movement
    # of its own to the receipt-and-assignment trail, and it moves exactly one box.
    butter = _movements(desk, BUTTER)
    assert [str(row[inv.MOVEMENT_TYPE_ATTRIBUTE]) for row in butter] == [
        "RECEIPT",
        "EVENT_ASSIGN",
        inv.EVENT_IMMEDIATE_SALE,
    ]
    immediate = [row for row in butter if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_IMMEDIATE_SALE]
    assert len(immediate) == 1 and int(immediate[0][inv.KERNEL_PHYSICAL_DELTA]) == -1
    assert stock_picture(desk["inventory"], DEFAULT_LANE.sales_campaign, BUTTER)["kernelPhysicalQty"] == 0


def test_the_desk_cannot_send_a_cash_portion_for_a_split(desk: Dict[str, Any]) -> None:
    """CASH-02: the note is the channel, so a cash half cannot be recorded anywhere else."""
    refused_note = assert_is_error(
        _sale_turn(
            {
                "showAndSellId": desk["eventId"],
                "saleAt": DEFAULT_LANE.moment(30),
                "lineItems": [{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 0}],
                "paymentMethodCode": "CASH",
                "otherDetails": "$10 of it cash, the rest in a pocket",
                "version": {"expectedVersion": event_version(str(desk["eventId"]))},
                "idempotency": {"idempotencyKey": DEFAULT_LANE.key("sale-cash-note")},
            }
        ),
        "INVALID_INPUT",
    )
    assert "otherDetails" in refused_note["message"], refused_note["message"]

    blank_note = assert_is_error(
        attempt_sale(
            desk["eventId"],
            key="sale-blank-note",
            buyer="Tess Tender",
            lines=[{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 0}],
            method="OTHER",
            other_details="   ",
        ),
        "INVALID_INPUT",
    )
    assert "otherDetails" in blank_note["message"], blank_note["message"]

    assert len(_stored_rows(desk)) == 3, "neither attempt wrote a row"
    assert _drawer(desk) == 2_500, "and neither moved the drawer"


# --- CASH-01: the drawer reads the method code and nothing else -------------------


def test_expected_cash_is_25_of_the_120_pool_the_lane_made(desk: Dict[str, Any]) -> None:
    """AC-31: calculated expected Cash is ``$25`` out of a $120 pool, and each sale says so itself."""
    page = _sales_page(desk)
    per_sale = sorted(
        (
            str(item["buyerName"]),
            str(item["paymentMethodSnapshot"]["methodCode"]),
            int(item["totalCents"]),
            int(item["expectedCashCents"]),
        )
        for item in page["items"]
    )
    assert per_sale == [
        ("Nora Cash", "CASH", 2_500, 2_500),
        ("Quinn WeOwe", "OTHER", 7_500, 0),
        ("Sam Split", "OTHER", 2_000, 0),
    ]
    assert _drawer(desk) == 2_500 == 25 * 100, "the plan's $25, reached by adding what the server answered"

    # ``showAndSellSales`` answers no total: the addition is the screen's, over these rows.
    assert _cash_named(page.keys()) == [], page.keys()
    assert _cash_named(page["items"][0].keys()) == ["expectedCashCents"]

    evidence = sales_evidence(desk["inventory"], desk["show_and_sells"], str(desk["eventId"]))
    assert evidence["poolCents"] == 12_000 and evidence["expectedCashCents"] == 2_500
    assert evidence["movementViolations"] == []


def test_notes_about_money_and_a_name_that_says_cash_neither_put_money_in_the_drawer(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> None:
    """AC-31, CASH-01: ``methodCode = CASH`` is the only thing the drawer can see.

    A lane of its own, because this leg needs a custom method a Unit has named with the word
    Cash in it — which the reserved-name rule allows as long as it is not *called* Cash — and
    a shelf that still holds something to sell.
    """
    lane = SalesLane.new("SS-SM-07", lane_id="L02")
    seed_sales_lane(units_table, unit_campaigns_table, catalogs_table, lane=lane)
    event_id = create_church_on_elm(lane)
    record_stock(lane)
    assign_stock(event_id, lane)

    created = _ok(
        _turn(
            CREATE_PAYMENT_METHOD_FIELD,
            {
                "unitId": lane.pack,
                "displayName": "Cash at the door",
                "idempotency": {"idempotencyKey": lane.key("payment-method-cash-door")},
            },
        )
    )
    named_cash = _ok(
        attempt_sale(
            event_id,
            lane=lane,
            key="sale-named-cash",
            buyer="Ned Named",
            lines=[{"productId": lane.butter, "immediateQty": 1, "weOweQty": 0}],
            method=f"CUSTOM:{created['paymentMethodId']}",
        )
    )
    real_cash = _ok(
        attempt_sale(
            event_id,
            lane=lane,
            key="sale-real-cash",
            buyer="Nora Cash",
            lines=[{"productId": lane.chocolate, "immediateQty": 1, "weOweQty": 0}],
        )
    )

    assert named_cash["sale"]["paymentMethodSnapshot"]["displayName"] == "Cash at the door"
    assert named_cash["sale"]["expectedCashCents"] == 0, "the Unit's wording is not a tender type"
    assert real_cash["sale"]["expectedCashCents"] == 2_500

    desk_state = {"inventory": inventory_table, "show_and_sells": show_and_sells_table, "eventId": event_id}
    assert _drawer(desk_state) == 2_500


def test_a_sale_that_was_refused_contributes_nothing_to_the_drawer(desk: Dict[str, Any]) -> None:
    """The plan's step 2 refusal, re-run against the entered lane: $25 stays $25."""
    before = stock_picture(desk["inventory"], DEFAULT_LANE.sales_campaign, CHOCOLATE)
    movements_before = len(_movements(desk, CHOCOLATE))

    refused = assert_is_error(
        attempt_sale(
            desk["eventId"],
            key="sale-too-many",
            buyer="Nina Over",
            lines=[{"productId": CHOCOLATE, "immediateQty": 3, "weOweQty": 0}],
        ),
        "CONFLICT",
    )
    assert "3 asked for, but this event holds" in refused["message"], refused["message"]

    assert len(_stored_rows(desk)) == 3
    assert _drawer(desk) == 2_500
    assert stock_picture(desk["inventory"], DEFAULT_LANE.sales_campaign, CHOCOLATE) == before
    assert len(_movements(desk, CHOCOLATE)) == movements_before


# --- CASH-03 / CASH-04: the reconciliation Stage 4 cannot write yet ---------------


def test_the_adjustment_the_actual_count_and_the_explanation_arrive_with_finalization(
    desk: Dict[str, Any],
) -> None:
    """The smoke plan's cash trail, pinned for §5.1.1, and the empty field set that proves it is not here.

    Nothing in Stage 4 records an adjustment, a counted drawer, a discrepancy or an
    explanation, so this leg asserts the two things that are true right now: the arithmetic
    chain §11.2 requires and that ``CASH-04``'s explanation is a required string, and that no
    Stage 4 sale or event surface carries a field for them. The checklist line that closes it
    is §5.1.1 ("Implement … ``CashReconciliation``"), which is where the ``+$10`` gets its reason,
    ``$34`` gets counted and ``-$1`` gets its explanation.
    """
    calculated = _drawer(desk)
    adjusted = calculated + CASH_ADJUSTMENT_CENTS
    discrepancy = ACTUAL_CASH_CENTS - adjusted

    assert calculated == 2_500, "$25"
    assert CASH_ADJUSTMENT_CENTS == 1_000 and CASH_ADJUSTMENT_REASON == "Cash portion of Sam Split Other payment"
    assert adjusted == 3_500, "$35"
    assert ACTUAL_CASH_CENTS == 3_400, "$34"
    assert discrepancy == -100, "-$1, and CASH-03 defines it as actual minus adjusted expected"
    assert CASH_EXPLANATION.strip(), "CASH-04: a nonzero discrepancy is finalizable only with an explanation"

    for row in _stored_rows(desk):
        assert _cash_named(row) == [], row
        assert _cash_named(sm.sale_payload(row)) == ["expectedCashCents"]
    event = ssm.event_admin_payload(ssm.load_show_and_sell_or_not_found(str(desk["eventId"])))
    assert _cash_named(event) == []
    assert event["status"] == "ENDED", "the lane stops before finalization, which is what opens reconciliation"
