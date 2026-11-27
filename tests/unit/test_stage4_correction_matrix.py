"""Leaf 4.6.5 — correction deltas, We Owe protection, and the revision chain, re-read after every turn.

§4.6.5 asks for four things proven together on one sale: the pre-finalization correction
applies **only the deltas** (§8.6.1 step 2), a correction can never take back a quantity
the buyer already holds (``fulfilledQty <= correctedLineQty <= originalQty``), an added
owed quantity arrives as its **own supplemental obligation** rather than a rewritten
line, and a correction releases **only the excess reservation** — never the whole
reservation, never none of it. On top of that the full previous revision survives every
correction, so the chain from revision 1 to the live row can be walked back with no gap
and no field lost.

``test_show_and_sell_sales.py`` proves each rule against a minimal scenario of its own.
What this module adds is the smoke lane's numbers with the stock picture, the ledger and
the obligation re-read after each turn, so a delta applied to the wrong column, a release
that let go of the whole reservation, or a supplemental line that quietly folded into the
original obligation is caught at the turn where it happened:

- the corrected line moves ``soldQty``/Kernel physical by exactly the difference, and the
  line the correction left alone spends no movement and no balance version (§8.6.1's
  "do not reverse and reapply unaffected lines");
- a fulfilled We Owe line refuses a reduction below ``fulfilledQty`` naming the fulfilled
  count, and refuses an upward rewrite naming the ceiling, each time writing nothing;
- releasing excess reservation writes one ``WE_OWE_RELEASE`` of exactly
  ``previousReserved - min(previousReserved, targetRemaining)`` and leaves the rest held;
- the supplemental obligation is created in the same operation as the target writes, with
  its own id, its own line identity, and the original obligation's ``originalQty`` and
  version untouched;
- and after two corrections the archived revisions are numbered 1 and 2, each carrying the
  whole line/total/payment/buyer content the sale held at that moment;
- and ``voidShowAndSellSale`` on the same lane reverses the whole sale — mirrored ledger pair,
  obligation cancelled, allocation reopened — with the pre-void revision archived intact.

**Why no reopened leg here.** §4.6.5's "reopened correction deltas" half needs
``reopenShowAndSell``, which is checklist §5.3.1 — Wave 6, proven at §5.5.3 by card WORK-178.
Every state
this module drives is pre-first-finalization, so every correction is live and no write
reports ``draftOnly``; the deferred leg is documented rather than faked by hand-painting a
``REOPENED`` row, which would evidence a state no Stage 4 mutation can produce.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CORRECT_SALE_FIELD,
    RECORD_RECEIPT_FIELD,
    VOID_SALE_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import account_id, assert_is_error, unit_operation_event
from tests.unit.show_sell_stage4_fixtures import (
    ADMIN,
    BUTTER,
    CHOCOLATE,
    DEFAULT_LANE,
    assign_stock,
    attempt_sale,
    create_church_on_elm,
    enable_we_owe,
    event_version,
    fulfill_we_owe,
    product_rows,
    record_stock,
    reserve_we_owe,
    seed_sales_lane,
    stock_picture,
)


@pytest.fixture
def lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """``Church on Elm`` with We Owe on and Quinn's 1-immediate + 2-owed Chocolate sale entered.

    The lane stops at Quinn: every §4.6.5 leg corrects *that* sale, and a fixture that
    had already reserved or fulfilled would pre-decide which protection the first turn
    could even see. ``eventId``/``saleId``/``weOweId``/``lineItemId`` come back from the
    sale's own answer so a test addresses rows the resolver actually minted.
    """
    seed_sales_lane(units_table, unit_campaigns_table, catalogs_table, lane=DEFAULT_LANE)
    event_id = create_church_on_elm(DEFAULT_LANE)
    record_stock(DEFAULT_LANE)
    assign_stock(event_id, DEFAULT_LANE)
    enable_we_owe(event_id)
    quinn = _ok(
        attempt_sale(
            event_id,
            key="sale-quinn",
            buyer="Quinn WeOwe",
            lines=[{"productId": CHOCOLATE, "immediateQty": 1, "weOweQty": 2}],
            method="OTHER",
            other_details="Apple Pay; Kernel reimbursed unit by Venmo",
        )
    )
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
        "eventId": event_id,
        "saleId": str(quinn["sale"][sm.SALE_ID_ATTRIBUTE]),
        "weOweId": str(quinn["obligations"][0][sm.WE_OWE_ID_ATTRIBUTE]),
        "lineItemId": str(quinn["obligations"][0]["lineItemId"]),
    }


# --- Turns and readers ------------------------------------------------------------


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload


def _turn(mutation: Dict[str, Any]) -> Any:
    """One ``correctShowAndSellSale`` turn, answered raw so refusals can be inspected."""
    return handle_unit_operation(unit_operation_event(CORRECT_SALE_FIELD, ADMIN, input=mutation), None)


def _correct(
    world: Dict[str, Any],
    *,
    key: str,
    revision: int,
    lines: List[Dict[str, Any]],
    reason: str = "two boxes came back",
    **extras: Any,
) -> Dict[str, Any]:
    """A successful correction at the event and sale versions the desk currently holds."""
    payload: Dict[str, Any] = {
        "showAndSellId": str(world["eventId"]),
        "saleId": str(world["saleId"]),
        "reason": reason,
        "lineItems": lines,
        "version": {"expectedVersion": event_version(str(world["eventId"]))},
        "saleVersion": {"expectedVersion": revision},
        "idempotency": {"idempotencyKey": DEFAULT_LANE.key(key)},
    }
    payload.update(extras)
    return _ok(_turn(payload))


def _refused_correction(
    world: Dict[str, Any], *, key: str, revision: int, lines: List[Dict[str, Any]]
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "showAndSellId": str(world["eventId"]),
        "saleId": str(world["saleId"]),
        "reason": "wrong on the pad",
        "lineItems": lines,
        "version": {"expectedVersion": event_version(str(world["eventId"]))},
        "saleVersion": {"expectedVersion": revision},
        "idempotency": {"idempotencyKey": DEFAULT_LANE.key(key)},
    }
    return assert_is_error(_turn(payload), "CONFLICT")


def _receive_more(world: Dict[str, Any], product_id: str, quantity: int, key: str) -> None:
    """A second ``recordInventoryReceipt`` turn — reservation headroom the base lane does not have."""
    _ok(
        handle_unit_operation(
            unit_operation_event(
                RECORD_RECEIPT_FIELD,
                ADMIN,
                input={
                    "unitCampaignId": DEFAULT_LANE.sales_campaign,
                    "productId": product_id,
                    "quantity": quantity,
                    "idempotency": {"idempotencyKey": DEFAULT_LANE.key(key)},
                },
            ),
            None,
        )
    )


def _quinn_lines(immediate: int, owed: int) -> List[Dict[str, Any]]:
    return [
        {
            "lineItemId": None,  # replaced by the caller's fixture id in _correct_quinn
            "productId": CHOCOLATE,
            "immediateQty": immediate,
            "weOweQty": owed,
        }
    ]


def _correct_quinn(
    world: Dict[str, Any], *, key: str, revision: int, immediate: int, owed: int, **extras: Any
) -> Dict[str, Any]:
    lines = _quinn_lines(immediate, owed)
    lines[0]["lineItemId"] = str(world["lineItemId"])
    return _correct(world, key=key, revision=revision, lines=lines, **extras)


def _sale_row(world: Dict[str, Any]) -> Dict[str, Any]:
    return sm.load_sale_or_not_found(str(world["eventId"]), str(world["saleId"]))


def _obligation(world: Dict[str, Any]) -> Dict[str, Any]:
    return sm.we_owe_payload(sm.load_we_owe_by_id_or_not_found(str(world["weOweId"])))


def _obligations(world: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [sm.we_owe_payload(row) for row in ssm.event_we_owe_rows(str(world["eventId"]))]


def _revision_rows(world: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sm.sale_revision_rows(str(world["eventId"]), str(world["saleId"]))


def _picture(world: Dict[str, Any], product_id: str) -> Dict[str, Any]:
    return stock_picture(world["inventory"], DEFAULT_LANE.sales_campaign, product_id)


def _ledger(world: Dict[str, Any], product_id: str) -> Dict[str, Dict[str, int]]:
    """``movementType -> {delta column: total}`` for one product, zero deltas dropped."""
    ledger: Dict[str, Dict[str, int]] = {}
    for row in product_rows(world["inventory"], DEFAULT_LANE.sales_campaign, product_id):
        if row.get("entityType") != inv.MOVEMENT_ENTITY_TYPE:
            continue
        kind = str(row[inv.MOVEMENT_TYPE_ATTRIBUTE])
        bucket = ledger.setdefault(kind, {})
        for column in inv.MOVEMENT_DELTA_ATTRIBUTES:
            value = int(row.get(column, 0) or 0)
            if value:
                bucket[column] = bucket.get(column, 0) + value
        if not bucket:
            bucket["(no delta)"] = 0
    return ledger


# --- Pre-finalization deltas -------------------------------------------------------


def test_a_correction_moves_only_the_immediate_delta_and_archives_the_whole_previous_revision(
    lane: Dict[str, Any],
) -> None:
    """SALE-M-02-01, §8.6.1: 1+2 becomes 2+1, one box more leaves the shelf, nothing else does."""
    before = _picture(lane, CHOCOLATE)
    obligation_before = _obligation(lane)
    event_before = ssm.load_show_and_sell_or_not_found(str(lane["eventId"]))

    answer = _correct_quinn(lane, key="correct-quinn", revision=1, immediate=2, owed=1)

    chocolate = _picture(lane, CHOCOLATE)
    assert (chocolate["kernelPhysicalQty"], before["kernelPhysicalQty"]) == (1, 2), "one more box left the shelf"
    assert chocolate["soldInPossessionQty"] == before["soldInPossessionQty"], "the sale moved, not the reservation"
    assert chocolate["assignedOpenQty"] == 0, "the corrected second box came out of the same allocation"

    assert _ledger(lane, CHOCOLATE)["EVENT_IMMEDIATE_SALE"] == {
        "kernelPhysicalDelta": -2,
        "assignedDelta": -2,
    }, "the ledger sums to the corrected total, not to a reversal plus a reapplication"

    obligation = _obligation(lane)
    assert (
        obligation["originalQty"],
        obligation["fulfilledQty"],
        obligation["cancelledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
        obligation["status"],
    ) == (2, 0, 1, 0, 1, 1, sm.WE_OWE_STATUS_OPEN)
    assert obligation["version"] == obligation_before["version"] + 1

    sale = sm.sale_payload(_sale_row(lane))
    assert sale[sm.REVISION_ATTRIBUTE] == 2
    assert [(line["immediateQty"], line["weOweQty"]) for line in sale["lineItems"]] == [(2, 1)]
    assert sale["lineItems"][0]["lineItemId"] == lane["lineItemId"], "the corrected line keeps its identity"
    assert (sale["lineItems"][0]["productNameSnapshot"], sale["lineItems"][0]["unitPriceCentsSnapshot"]) == (
        f"Chocolate Popcorn {DEFAULT_LANE.data_id}",
        2500,
    ), "the correction repriced nothing"

    archived = [_revision_rows(lane)[0]]
    assert len(archived) == 1
    revision = sm.sale_revision_payload(archived[0])
    assert revision[sm.REVISION_ATTRIBUTE] == 1
    assert [(line["immediateQty"], line["weOweQty"]) for line in revision["lineItems"]] == [(1, 2)]
    assert revision["lineItems"] == answer["priorRevision"]["lineItems"]
    assert revision[sm.TOTAL_CENTS_ATTRIBUTE] == answer["priorRevision"]["totalCents"] == 7500
    assert revision["buyerName"] == "Quinn WeOwe"
    assert revision[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]["methodCode"] == "OTHER"
    assert revision[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]["otherDetails"] == "Apple Pay; Kernel reimbursed unit by Venmo"
    assert revision[sm.STATUS_ATTRIBUTE] == "ACTIVE"
    assert revision["correctedByAccountId"] == account_id(ADMIN)
    assert revision["reason"] == "two boxes came back"

    event_after = ssm.load_show_and_sell_or_not_found(str(lane["eventId"]))
    assert event_after[ssm.VERSION_ATTRIBUTE] == event_before[ssm.VERSION_ATTRIBUTE] + 1
    assert answer["eventVersion"] == int(event_after[ssm.VERSION_ATTRIBUTE])
    assert answer["draftOnly"] is False, "pre-finalization corrections are live, not draft"
    assert (
        sm.sale_revision_rows(str(lane["eventId"]), str(lane["saleId"]))[0]["entityType"] == "ShowAndSellSaleRevision"
    )


def test_a_line_the_correction_leaves_alone_spends_no_movement_and_no_balance_version(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1 step 2: an unaffected line does not get reversed and reapplied."""
    event_id = str(lane["eventId"])
    nora = _ok(
        attempt_sale(
            event_id,
            key="sale-nora-butter",
            buyer="Nora Cash",
            lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 0}],
        )
    )
    butter_before = _picture(lane, BUTTER)
    butter_ledger_before = _ledger(lane, BUTTER)
    assert butter_before["balanceVersion"] >= 1

    _correct_quinn(lane, key="correct-quinn", revision=1, immediate=2, owed=1)

    assert _picture(lane, BUTTER) == butter_before, "Butter was not in the correction at all"
    assert _ledger(lane, BUTTER) == butter_ledger_before
    assert sm.sale_payload(_sale_row(lane))["lineItems"][0]["productId"] == CHOCOLATE
    nora_row = sm.load_sale_or_not_found(event_id, str(nora["sale"][sm.SALE_ID_ATTRIBUTE]))
    assert nora_row[sm.REVISION_ATTRIBUTE] == 1, "correcting Quinn never reaches Nora's row"


def test_an_omitted_line_voids_its_quantity_and_closes_its_obligation_cancelled(
    lane: Dict[str, Any],
) -> None:
    """SALE-M-03-01's line-level void: omitting the line is 0, and the box goes back."""
    before = _picture(lane, CHOCOLATE)

    answer = _correct(
        lane,
        key="correct-omit",
        revision=1,
        lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 0}],
        reason="Quinn walked away from the Chocolate",
    )

    chocolate = _picture(lane, CHOCOLATE)
    assert (chocolate["kernelPhysicalQty"], before["kernelPhysicalQty"]) == (3, 2), "the handed box came back"
    assert (chocolate["soldInPossessionQty"], before["soldInPossessionQty"]) == (0, 0)
    assert _ledger(lane, CHOCOLATE)["EVENT_IMMEDIATE_SALE"] == {"kernelPhysicalDelta": 0, "assignedDelta": 0}, (
        "the original sale and the reversal sum to nothing — the box is back on the shelf"
    )

    obligation = _obligation(lane)
    assert (
        obligation["cancelledQty"],
        obligation["remainingQty"],
        obligation["reservedQty"],
        obligation["status"],
        obligation["closeReason"],
    ) == (2, 0, 0, sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_CANCELLED)

    butter = _picture(lane, BUTTER)
    assert butter["kernelPhysicalQty"] == 0, "the supplemental Butter box went out in the same turn"

    sale = sm.sale_payload(_sale_row(lane))
    assert [(line["productId"], line["immediateQty"], line["weOweQty"]) for line in sale["lineItems"]] == [
        (BUTTER, 1, 0)
    ]
    assert sale[sm.TOTAL_CENTS_ATTRIBUTE] == 2000
    assert answer["priorRevision"] is not None
    assert answer["priorRevision"]["totalCents"] == 7500


# --- Fulfilled-We Owe protection ----------------------------------------------------


def test_a_correction_cannot_take_back_a_quantity_the_buyer_already_holds(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1's ``fulfilledQty <= correctedLineQty``: 1 fulfilled fences the whole line."""
    _ok(reserve_we_owe(str(lane["weOweId"]), target=1))
    _ok(fulfill_we_owe(str(lane["weOweId"]), sm.WE_OWE_SOURCE_KERNEL, key="kernel-fulfill"))
    obligation_before = _obligation(lane)
    shelf_before = _picture(lane, CHOCOLATE)
    movements_before = _ledger(lane, CHOCOLATE)

    refused = _refused_correction(lane, key="correct-below-fulfilled", revision=1, lines=_quinn_with_id(lane, 1, 0))
    assert "already has 1 fulfilled" in refused["message"]
    assert _obligation(lane) == obligation_before
    assert _picture(lane, CHOCOLATE) == shelf_before
    assert _ledger(lane, CHOCOLATE) == movements_before
    assert _revision_rows(lane) == [], "a refused correction archives nothing"
    assert _sale_row(lane)[sm.REVISION_ATTRIBUTE] == 1


def _quinn_with_id(world: Dict[str, Any], immediate: int, owed: int) -> List[Dict[str, Any]]:
    lines = _quinn_lines(immediate, owed)
    lines[0]["lineItemId"] = str(world["lineItemId"])
    return lines


def test_an_existing_line_cannot_be_corrected_upward_past_what_it_was_entered_with(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1's other fence: an increase is a supplemental line, said in the refusal."""
    refused = assert_is_error(
        _turn(
            {
                "showAndSellId": str(lane["eventId"]),
                "saleId": str(lane["saleId"]),
                "reason": "Quinn wants another box",
                "lineItems": _quinn_with_id(lane, 1, 3),
                "version": {"expectedVersion": event_version(str(lane["eventId"]))},
                "saleVersion": {"expectedVersion": 1},
                "idempotency": {"idempotencyKey": DEFAULT_LANE.key("correct-upward")},
            }
        ),
        "INVALID_INPUT",
    )
    assert "cannot exceed the 2 it was entered with" in refused["message"]
    assert "add a new line for more" in refused["message"]
    assert _obligation(lane)["originalQty"] == 2
    assert _revision_rows(lane) == []


# --- Release of only the excess reservation -----------------------------------------


def test_a_corrected_quantity_releases_only_the_reservation_it_no_longer_needs(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1 step 3: reserved 2, corrected to owe 1, so exactly 1 goes back and 1 stays held."""
    _receive_more(lane, CHOCOLATE, 2, "receipt-chocolate-more")
    _ok(reserve_we_owe(str(lane["weOweId"]), target=2))
    held = _picture(lane, CHOCOLATE)
    assert (held["soldInPossessionQty"], held["unassignedKernelQty"]) == (2, 1)

    _correct_quinn(lane, key="correct-shrink-owe", revision=1, immediate=1, owed=1)

    obligation = _obligation(lane)
    assert (
        obligation["originalQty"],
        obligation["cancelledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
        obligation["status"],
    ) == (2, 1, 1, 1, 0, sm.WE_OWE_STATUS_OPEN), "min(previousReserved, targetRemaining) — not zero"

    chocolate = _picture(lane, CHOCOLATE)
    assert chocolate["soldInPossessionQty"] == 1, "exactly one held box went back to the shelf side"
    assert chocolate["kernelPhysicalQty"] == held["kernelPhysicalQty"], "the shelf itself never moved"
    assert _ledger(lane, CHOCOLATE)["WE_OWE_RELEASE"] == {"soldPossessionDelta": -1}
    assert _ledger(lane, CHOCOLATE)["WE_OWE_RESERVE"] == {"soldPossessionDelta": 2}


def test_a_reservation_survives_only_while_its_corrected_remaining_is_above_zero(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1's last line: zero corrected remaining means no reservation may survive."""
    _receive_more(lane, CHOCOLATE, 2, "receipt-chocolate-more")
    _ok(reserve_we_owe(str(lane["weOweId"]), target=2))

    _correct_quinn(lane, key="correct-owe-zero", revision=1, immediate=1, owed=0)

    obligation = _obligation(lane)
    assert (obligation["reservedQty"], obligation["remainingQty"], obligation["status"], obligation["closeReason"]) == (
        0,
        0,
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_CANCELLED,
    )
    assert _ledger(lane, CHOCOLATE)["WE_OWE_RELEASE"] == {"soldPossessionDelta": -2}


# --- Supplemental obligations --------------------------------------------------------


def test_added_owed_quantity_arrives_as_its_own_obligation_not_a_rewritten_line(
    lane: Dict[str, Any],
) -> None:
    """§8.6.1 step 3, SALE-M-02-03: a supplemental Butter line gets its own obligation."""
    obligation_before = _obligation(lane)

    answer = _correct(
        lane,
        key="correct-supplemental",
        revision=1,
        lines=[
            *_quinn_with_id(lane, 1, 2),
            {"productId": BUTTER, "immediateQty": 0, "weOweQty": 1},
        ],
        reason="Quinn also owes a Butter",
    )

    sale = sm.sale_payload(_sale_row(lane))
    assert sale[sm.REVISION_ATTRIBUTE] == 2
    assert [(line["productId"], line["immediateQty"], line["weOweQty"]) for line in sale["lineItems"]] == [
        (CHOCOLATE, 1, 2),
        (BUTTER, 0, 1),
    ]
    supplemental_line_id = sale["lineItems"][1]["lineItemId"]
    assert supplemental_line_id != lane["lineItemId"], "the new line is minted, not recycled"
    assert sale[sm.TOTAL_CENTS_ATTRIBUTE] == 9500, "7500 Chocolate + 2000 Butter, snapshot prices"

    obligations = {row["lineItemId"]: row for row in _obligations(lane)}
    assert len(obligations) == 2
    supplemental = obligations[supplemental_line_id]
    assert (
        supplemental["originalQty"],
        supplemental["remainingQty"],
        supplemental["uncoveredQty"],
        supplemental["status"],
        supplemental["buyerName"],
        supplemental["valueCentsSnapshot"],
    ) == (1, 1, 1, sm.WE_OWE_STATUS_OPEN, "Quinn WeOwe", 2000)
    assert supplemental[sm.SALE_ID_ATTRIBUTE] == lane["saleId"]
    assert {row["weOweId"] for row in answer["obligations"]} == {row["weOweId"] for row in _obligations(lane)}

    assert _obligation(lane) == obligation_before, (
        "the original obligation is not rewritten upward — its row did not even take a write"
    )
    assert _ledger(lane, BUTTER) == {
        "RECEIPT": {"kernelPhysicalDelta": 1},
        "EVENT_ASSIGN": {"assignedDelta": 1},
    }, "an owed Butter box moves no stock"


# --- The complete prior-revision chain ----------------------------------------------


def test_two_corrections_leave_a_chain_of_whole_previous_revisions(
    lane: Dict[str, Any],
) -> None:
    """§4.3.1/§8.6.1: every correction archives the whole row it replaced, numbered with no gap."""
    first = _correct_quinn(lane, key="correct-one", revision=1, immediate=2, owed=1, reason="one more box handed over")
    second = _correct(
        lane,
        key="correct-two",
        revision=2,
        lines=[{"productId": BUTTER, "immediateQty": 1, "weOweQty": 0}],
        reason="Quinn exchanged for Butter",
        paymentMethodCode="CASH",
    )
    assert first["draftOnly"] is False and second["draftOnly"] is False

    sale = sm.sale_payload(_sale_row(lane))
    assert sale[sm.REVISION_ATTRIBUTE] == 3
    assert [(line["productId"], line["immediateQty"], line["weOweQty"]) for line in sale["lineItems"]] == [
        (BUTTER, 1, 0)
    ]
    assert sale[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]["methodCode"] == "CASH"

    rows = sorted(_revision_rows(lane), key=lambda row: int(row[sm.REVISION_ATTRIBUTE]))
    assert [int(row[sm.REVISION_ATTRIBUTE]) for row in rows] == [1, 2], "no gap, no missing revision"
    revision_one, revision_two = (sm.sale_revision_payload(row) for row in rows)
    assert [(line["productId"], line["immediateQty"], line["weOweQty"]) for line in revision_one["lineItems"]] == [
        (CHOCOLATE, 1, 2)
    ]
    assert [(line["productId"], line["immediateQty"], line["weOweQty"]) for line in revision_two["lineItems"]] == [
        (CHOCOLATE, 2, 1)
    ]
    assert revision_two["reason"] == "Quinn exchanged for Butter"
    assert revision_one["reason"] == "one more box handed over", (
        "each archive carries the reason of the correction that made it"
    )
    assert revision_two["correctedByAccountId"] == revision_one["correctedByAccountId"] == account_id(ADMIN)
    for revision in (revision_one, revision_two):
        assert revision[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]["methodCode"] == "OTHER", (
            "history keeps the words it was written in"
        )
        assert revision["buyerName"] == "Quinn WeOwe"
        assert revision["saleAt"] == DEFAULT_LANE.moment(30)
        assert revision["enteredByAccountId"] == account_id(ADMIN)
        assert revision["status"] == "ACTIVE"

    assert second["priorRevision"]["revision"] == 2
    assert second["priorRevision"]["totalCents"] == revision_two["totalCents"] == 7500

    chocolate = _picture(lane, CHOCOLATE)
    assert chocolate["kernelPhysicalQty"] == 3, "the second correction handed both corrected Chocolate boxes back"
    assert _ledger(lane, CHOCOLATE)["EVENT_IMMEDIATE_SALE"] == {"kernelPhysicalDelta": 0, "assignedDelta": 0}, (
        "the ledger reflects the net of both corrections, never a re-applied original"
    )

    stale = assert_is_error(
        _turn(
            {
                "showAndSellId": str(lane["eventId"]),
                "saleId": str(lane["saleId"]),
                "reason": "trying to edit revision 1 again",
                "lineItems": _quinn_with_id(lane, 1, 1),
                "version": {"expectedVersion": event_version(str(lane["eventId"]))},
                "saleVersion": {"expectedVersion": 1},
                "idempotency": {"idempotencyKey": DEFAULT_LANE.key("correct-stale-revision")},
            }
        ),
        "CONFLICT",
    )
    assert "revision" in stale["message"].lower()
    assert [int(row[sm.REVISION_ATTRIBUTE]) for row in _revision_rows(lane)] == [1, 2], (
        "the stale write archived nothing"
    )


# --- Voiding the whole sale --------------------------------------------------------


def _void(
    world: Dict[str, Any], *, key: str, revision: int, reason: str = "the buyer left", version: int | None = None
) -> Any:
    return handle_unit_operation(
        unit_operation_event(
            VOID_SALE_FIELD,
            ADMIN,
            input={
                "showAndSellId": str(world["eventId"]),
                "saleId": str(world["saleId"]),
                "reason": reason,
                "version": {
                    "expectedVersion": version if version is not None else event_version(str(world["eventId"]))
                },
                "saleVersion": {"expectedVersion": revision},
                "idempotency": {"idempotencyKey": DEFAULT_LANE.key(key)},
            },
        ),
        None,
    )


def test_voiding_the_sale_returns_its_box_reopens_its_allocation_and_cancels_the_owed_quantity(
    lane: Dict[str, Any],
) -> None:
    """``voidShowAndSellSale`` on the same lane: the whole sale reverses, the obligation closes cancelled.

    The lane stops at Quinn — one immediate box, two owed, nothing reserved or fulfilled — the
    cleanest base a void can have. The immediate leg reverses as a mirrored pair in the ledger, the
    owed two never spent stock so they cancel on the obligation alone, and revision 1 is archived
    whole, so the chain from the VOIDED row back to what the desk first entered stays walkable.
    """
    held_event = event_version(str(lane["eventId"]))
    answer = _ok(_void(lane, key="void-quinn", revision=1, version=held_event))
    assert answer["draftOnly"] is False, "nothing has been finalized: this void is live, not a draft"

    row = _sale_row(lane)
    assert row["status"] == sm.SALE_STATUS_VOIDED
    assert row[sm.VOIDED_BY_ATTRIBUTE] == account_id(ADMIN) and row[sm.VOIDED_AT_ATTRIBUTE]

    obligation = _obligation(lane)
    assert (obligation["status"], obligation["closeReason"]) == (
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_CANCELLED,
    )
    assert (obligation["originalQty"], obligation["cancelledQty"], obligation["remainingQty"]) == (2, 2, 0), (
        "the owed two cancel on the obligation — they never left a shelf to reverse"
    )

    chocolate = _picture(lane, CHOCOLATE)
    assert (chocolate["kernelPhysicalQty"], chocolate["soldInPossessionQty"], chocolate["assignedOpenQty"]) == (
        3,
        0,
        2,
    ), "the box comes back to Kernel stock and the assignment that funded it reopens"
    assert _ledger(lane, CHOCOLATE) == {
        "RECEIPT": {"kernelPhysicalDelta": 3},
        "EVENT_ASSIGN": {"assignedDelta": 2},
        "EVENT_IMMEDIATE_SALE": {"kernelPhysicalDelta": 0, "assignedDelta": 0},
    }, "the sale and its void sit in the ledger as a mirrored pair that nets to zero, never deleted"

    revisions = _revision_rows(lane)
    assert len(revisions) == 1 and int(revisions[0][sm.REVISION_ATTRIBUTE]) == 1
    archived = revisions[0]
    assert archived["buyerName"] == "Quinn WeOwe" and archived[sm.TOTAL_CENTS_ATTRIBUTE] == 7500
    assert [
        (line[sm.IMMEDIATE_QTY_ATTRIBUTE], line[sm.WE_OWE_QTY_ATTRIBUTE]) for line in archived[sm.LINE_ITEMS_ATTRIBUTE]
    ] == [(1, 2)], "the archived revision holds the sale as entered, void included"

    assert _ok(_void(lane, key="void-quinn", revision=1, version=held_event)) == answer, (
        "the same key with the same content replays the same answer"
    )
    again = assert_is_error(_void(lane, key="void-quinn-fresh", revision=1, version=held_event), "CONFLICT")
    assert "already voided" in again["message"]
    assert _picture(lane, CHOCOLATE)["kernelPhysicalQty"] == 3, "the refused second void moved nothing again"
