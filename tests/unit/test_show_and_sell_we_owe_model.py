"""Wave 5.3 (§4.4.1-§4.4.3) — the We Owe obligation and fulfillment model.

The pure half of the We Owe surface: what one append-only fulfillment record is, what
makes it a record of something that actually happened, and the arithmetic a reservation
or a fulfillment moves an obligation to. The resolver half — the transaction a
``setWeOweReservation``/``fulfillWeOwe`` request commits against DynamoDB, and the two
reads — is ``tests/unit/test_show_and_sell_we_owe.py``.

What is proved here is the part no transaction can vouch for:

- a fulfillment record is a child of exactly one obligation, keyed under it, with no
  ``version`` attribute and no obligation state of its own, because §5.15 makes history
  append-only and the obligation row the only aggregate (§5.15);
- the source and the movement it names are one fact: ``KERNEL_STOCK`` names the movement
  that moved the stock, ``EXTERNAL_COUNCIL`` names none, because a Council that supplied a
  quantity changed no Unit quantity and a movement row would describe a stock change that
  never happened (OWE-07);
- ``KERNEL_STOCK`` is bounded by the reserved quantity and ``EXTERNAL_COUNCIL`` by the
  uncovered quantity, which is what forces a covered portion to be released before a
  Council supplies it, and an obligation closes only when nothing is owed and nothing is
  held (OWE-07, OWE-09);
- nothing in either row carries a due date, an assignee, or an aging field, and ``CLOSED``
  has two reasons and no third state (OWE-06, OWE-10).

The obligations are built by the sale builder and then moved to the mid-life state Wave
5.3's writes produce: a sale only ever creates an OPEN obligation with nothing fulfilled,
cancelled, or reserved.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils.errors import AppError, ErrorCode

EVENT = "SSE#owe-model"
CAMPAIGN = "uc-owe-model"
PRODUCT = "CATALOG#owe-model#prod-1"
AVERY = "ACCOUNT#avery-fixture"
NOW = "2026-11-23T18:00:00+00:00"
LATER = "2026-11-23T19:00:00+00:00"

PRICES = {
    PRODUCT: {
        sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: "Caramel Cremes",
        sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: 500,
    }
}

#: The fulfillment record's own attribute set, in the order the payload answers it. Kept
#: here rather than read from the SDL because the two are checked against each other by
#: ``tests/unit/check_show_and_sell_schema.test.ts``.
FULFILLMENT_FIELDS = (
    "fulfillmentId",
    "weOweId",
    "quantity",
    "source",
    "inventoryMovementId",
    "actorAccountId",
    "createdAt",
)

#: OWE-10: We Owe is a list a Unit prioritizes by looking at it. Any of these would be a
#: work-queue state machine the specification rejects, and a row that grew one would grow
#: a UI, a sort, and a report nobody asked for.
FORBIDDEN_WE_OWE_FIELDS = (
    "dueDate",
    "dueAt",
    "due",
    "agingDays",
    "ageDays",
    "age",
    "assigneeId",
    "assignee",
    "assignedTo",
    "priority",
    "statusReason",
    "notes",
    "buyerPhone",
    "buyerEmail",
    "buyerAccountId",
    "profileId",
)


def _line(*, quantity: int = 3) -> Dict[str, Any]:
    return sm.snapshot_line_items([{"productId": PRODUCT, "immediateQty": 0, "weOweQty": quantity}], PRICES)[0]


def _owe(
    *, quantity: int = 3, fulfilled: int = 0, cancelled: int = 0, reserved: int = 0, line: Any = None
) -> Dict[str, Any]:
    """One obligation, moved to the mid-life state a Wave 5.3 write would leave it in."""
    line = line or _line(quantity=quantity)
    item = sm.build_we_owe_item(
        show_and_sell_id=EVENT,
        unit_campaign_id=CAMPAIGN,
        sale_id="sale-owe-model-1",
        line_item=line,
        buyer_name="Buyer Bee",
        now_iso=NOW,
    )
    remaining = quantity - fulfilled - cancelled
    item[sm.FULFILLED_QTY_ATTRIBUTE] = fulfilled
    item[sm.CANCELLED_QTY_ATTRIBUTE] = cancelled
    item[sm.RESERVED_QTY_ATTRIBUTE] = reserved
    item[sm.REMAINING_QTY_ATTRIBUTE] = remaining
    item[sm.UNCOVERED_QTY_ATTRIBUTE] = remaining - reserved
    if remaining == 0 and reserved == 0:
        item[sm.STATUS_ATTRIBUTE] = sm.WE_OWE_STATUS_CLOSED
        item[sm.CLOSE_REASON_ATTRIBUTE] = sm.WE_OWE_CLOSE_FULFILLED if fulfilled else sm.WE_OWE_CLOSE_CANCELLED
        item[sm.CLOSED_AT_ATTRIBUTE] = LATER
        item[sm.VERSION_ATTRIBUTE] = 4
    return item


def _record(
    *,
    fulfillment_id: str = "11111111-1111-4111-8111-111111111111",
    quantity: int = 2,
    source: Any = sm.WE_OWE_SOURCE_KERNEL,
    movement_id: Any = None,
    we_owe_id: Any = None,
    now_iso: str = NOW,
) -> Dict[str, Any]:
    return sm.build_we_owe_fulfillment_item(
        show_and_sell_id=EVENT,
        we_owe_id=we_owe_id or str(sm.new_we_owe_id()),
        fulfillment_id=fulfillment_id,
        quantity=quantity,
        source=source,
        actor_account_id=AVERY,
        now_iso=now_iso,
        inventory_movement_id=movement_id,
    )


# --- §4.4.1: the append-only fulfillment record ----------------------------------


def test_a_fulfillment_record_is_an_append_only_child_of_exactly_one_obligation() -> None:
    """§4.4.1, §6.4: the record hangs under its obligation and carries no state of its own."""
    obligation = _owe(quantity=3)
    obligation_id = str(obligation[sm.WE_OWE_ID_ATTRIBUTE])
    record = _record(we_owe_id=obligation_id, movement_id=inv.new_inventory_movement_id())

    assert record["pk"] == ssm.show_and_sell_pk(EVENT)
    assert record["sk"] == f"WE_OWE#{obligation_id}#FULFILLMENT#{record[sm.FULFILLMENT_ID_ATTRIBUTE]}"
    assert record["sk"].startswith(f"{sm.we_owe_sk(obligation_id)}{ssm.WE_OWE_FULFILLMENT_SK_MARKER}")
    assert sm.we_owe_fulfillment_key(EVENT, obligation_id, str(record[sm.FULFILLMENT_ID_ATTRIBUTE])) == {
        "pk": record["pk"],
        "sk": record["sk"],
    }
    assert record["entityType"] == sm.WE_OWE_FULFILLMENT_ENTITY_TYPE
    assert record[sm.WE_OWE_ID_ATTRIBUTE] == obligation_id
    assert record[sm.CREATED_AT_ATTRIBUTE] == NOW

    # The two attributes that would make history a second aggregate: no version, because a
    # record with a version is a record someone can edit, and no unitCampaignId or status,
    # because unitCampaignId-status-index is the obligation list and a history row in it
    # would answer "what is still owed" with rows that owe nothing.
    assert sm.VERSION_ATTRIBUTE not in record
    assert sm.UNIT_CAMPAIGN_ID_ATTRIBUTE not in record
    assert sm.STATUS_ATTRIBUTE not in record
    assert sm.RESERVED_QTY_ATTRIBUTE not in record, "the obligation row is the aggregate; the record is one fact"

    payload = sm.we_owe_fulfillment_payload(record)
    assert tuple(payload) == FULFILLMENT_FIELDS
    assert payload["quantity"] == 2
    assert payload["source"] == sm.WE_OWE_SOURCE_KERNEL
    assert payload["actorAccountId"] == AVERY


def test_no_we_owe_row_carries_a_due_date_an_assignee_or_an_aging_field() -> None:
    """OWE-10, §5.15: the buyer is a name and the list has no queue state."""
    for row in (_owe(quantity=3), _record(movement_id=inv.new_inventory_movement_id())):
        for name in FORBIDDEN_WE_OWE_FIELDS:
            assert name not in row, f"{row['entityType']}.{name} would be a work-queue field"
    for payload in (sm.we_owe_payload(_owe(quantity=3)), sm.we_owe_fulfillment_payload(_record())):
        for name in FORBIDDEN_WE_OWE_FIELDS:
            assert name not in payload, f"a read would answer {name}, which nothing writes"


def test_the_source_and_the_movement_it_names_are_one_fact() -> None:
    """§5.15, OWE-07: a Kernel fulfillment names its movement; a Council's names none."""
    kernel = _record(source=sm.WE_OWE_SOURCE_KERNEL, movement_id=inv.new_inventory_movement_id())
    external = _record(source=sm.WE_OWE_SOURCE_EXTERNAL)

    assert sm.we_owe_fulfillment_invariant_violations(kernel) == []
    assert sm.we_owe_fulfillment_invariant_violations(external) == []

    stranded = dict(kernel)
    del stranded[sm.FULFILLMENT_MOVEMENT_ATTRIBUTE]
    assert any("movement" in line for line in sm.we_owe_fulfillment_invariant_violations(stranded))

    invented = dict(external)
    invented[sm.FULFILLMENT_MOVEMENT_ATTRIBUTE] = inv.new_inventory_movement_id()
    violations = sm.we_owe_fulfillment_invariant_violations(invented)
    assert any("changed no Unit stock" in line for line in violations), (
        "an EXTERNAL_COUNCIL movement row would describe a stock change that never happened"
    )


def test_a_record_of_something_that_did_not_happen_is_refused() -> None:
    """§4.4.1: the builder refuses an unusable record and the invariant refuses an unusable row."""
    # Two sources and no third, a quantity that delivered something, and an id that can
    # sit at the end of a composite sort key: none of these are worth a record.
    for build, fragment in (
        (lambda: _record(source="SCOUT_CUSTODY"), "must be one of"),
        (lambda: _record(quantity=0), "quantity"),
        (lambda: _record(quantity=inv.MAX_QUANTITY + 1), "quantity"),
        (lambda: _record(fulfillment_id=""), "fulfillmentId"),
        (lambda: _record(fulfillment_id="x" * 200), "fulfillmentId"),
    ):
        error = pytest.raises(AppError, build).value
        assert error.error_code == ErrorCode.INVALID_INPUT, f"{fragment} should be a refusal, not a stored row"
        assert fragment in error.message, error.message

    unknown_source = dict(_record(source=sm.WE_OWE_SOURCE_EXTERNAL))
    unknown_source[sm.FULFILLMENT_SOURCE_ATTRIBUTE] = "SCOUT_CUSTODY"
    assert any(
        "must be one of" in line for line in sm.we_owe_fulfillment_invariant_violations(unknown_source)
    ), "a row naming a source the vocabulary does not carry is a violation, not a record"

    mutable = dict(_record(source=sm.WE_OWE_SOURCE_EXTERNAL))
    mutable[sm.VERSION_ATTRIBUTE] = 1
    assert any("append-only" in line for line in sm.we_owe_fulfillment_invariant_violations(mutable))

    unsigned = dict(_record(source=sm.WE_OWE_SOURCE_EXTERNAL))
    unsigned[sm.FULFILLMENT_QTY_ATTRIBUTE] = 0
    assert any("positive" in line for line in sm.we_owe_fulfillment_invariant_violations(unsigned))

    incomplete = dict(_record(source=sm.WE_OWE_SOURCE_EXTERNAL))
    del incomplete[sm.FULFILLMENT_QTY_ATTRIBUTE]
    assert sm.we_owe_fulfillment_invariant_violations(incomplete) == [f"{sm.FULFILLMENT_QTY_ATTRIBUTE} is required"]


def test_the_fulfillment_id_is_minted_server_side_and_shared_by_both_rows() -> None:
    """§5.15: the record and the movement it consumed name one identity."""
    first, second = sm.new_fulfillment_id(), sm.new_fulfillment_id()
    assert first != second
    assert sm.normalize_fulfillment_id(first) == first
    for bad in ("", " ", "x" * 200, 7):
        assert pytest.raises(AppError, lambda: sm.normalize_fulfillment_id(bad)).value.error_code == (
            ErrorCode.INVALID_INPUT
        )

    movement_id = inv.new_inventory_movement_id()
    record = _record(fulfillment_id=first, source=sm.WE_OWE_SOURCE_KERNEL, movement_id=movement_id)
    action, body = sm.put_we_owe_fulfillment_action(record)

    assert action == "Put"
    assert body["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)", (
        "the record's own id is the replay guard: a second attempt collides instead of appending a delivery"
    )
    assert record[sm.FULFILLMENT_ID_ATTRIBUTE] == first
    assert record[sm.FULFILLMENT_MOVEMENT_ATTRIBUTE] == movement_id


# --- §4.4.2: the reservation target ----------------------------------------------


def test_a_reservation_target_moves_the_obligation_and_says_what_it_released() -> None:
    """§4.4.2: a target, not a delta — and the released quantity is what the write hands back."""
    row = _owe(quantity=3)

    reserve = sm.we_owe_reservation_targets(row, 2, unassigned_qty=4)
    assert (reserve.reserved_qty, reserve.remaining_qty, reserve.uncovered_qty) == (2, 3, 1)
    assert (reserve.release_qty, reserve.status, reserve.close_reason, reserve.changed) == (
        0,
        sm.WE_OWE_STATUS_OPEN,
        None,
        True,
    )

    held = _owe(quantity=3, reserved=2)
    release = sm.we_owe_reservation_targets(held, 1, unassigned_qty=4)
    assert (release.reserved_qty, release.uncovered_qty, release.release_qty) == (1, 2, 1)
    assert release.status == sm.WE_OWE_STATUS_OPEN

    zero = sm.we_owe_reservation_targets(held, 0, unassigned_qty=4)
    assert (zero.reserved_qty, zero.uncovered_qty, zero.release_qty) == (0, 3, 2)
    assert zero.status == sm.WE_OWE_STATUS_OPEN, "releasing every reserved unit does not settle what is still owed"

    same = sm.we_owe_reservation_targets(held, 2, unassigned_qty=0)
    assert same.changed is False and same.release_qty == 0, "an equal target writes nothing and moves no stock"


def test_a_reservation_target_cannot_promise_more_than_is_owed_or_unassigned() -> None:
    """§4.4.2, OWE-04: the two bounds, and a closed obligation has nothing to reserve against."""
    row = _owe(quantity=3)

    above_remaining = pytest.raises(AppError, lambda: sm.we_owe_reservation_targets(row, 4, unassigned_qty=9)).value
    assert above_remaining.error_code == ErrorCode.CONFLICT
    assert above_remaining.details["subcode"] == sm.RESERVATION_ABOVE_REMAINING

    above_unassigned = pytest.raises(AppError, lambda: sm.we_owe_reservation_targets(row, 3, unassigned_qty=2)).value
    assert above_unassigned.details["subcode"] == sm.RESERVATION_ABOVE_UNASSIGNED
    assert "already assigned to an event" in above_unassigned.message

    negative = pytest.raises(AppError, lambda: sm.we_owe_reservation_targets(row, -1, unassigned_qty=9)).value
    assert negative.error_code == ErrorCode.INVALID_INPUT

    closed = _owe(quantity=2, fulfilled=2)
    refused = pytest.raises(AppError, lambda: sm.we_owe_reservation_targets(closed, 1, unassigned_qty=9)).value
    assert refused.details["subcode"] == sm.WE_OWE_OBLIGATION_CLOSED

    cancelled_closed = _owe(quantity=2, cancelled=2)
    assert (
        pytest.raises(AppError, lambda: sm.we_owe_reservation_targets(cancelled_closed, 0, unassigned_qty=9)).value.details[
            "subcode"
        ]
        == sm.WE_OWE_OBLIGATION_CLOSED
    )


def test_new_stock_never_reserves_itself_for_an_older_obligation() -> None:
    """OWE-05: the target is what the caller asked for, whatever the campaign now holds."""
    held = _owe(quantity=1, reserved=1)
    same = sm.we_owe_reservation_targets(held, 1, unassigned_qty=50)
    assert (same.reserved_qty, same.changed, same.release_qty) == (1, False, 0)
    assert sm.we_owe_reservation_targets(_owe(quantity=1), 0, unassigned_qty=50).reserved_qty == 0


# --- §4.4.3: the fulfillment target ----------------------------------------------


def test_a_kernel_fulfillment_moves_both_stock_terms_and_consumes_the_reservation() -> None:
    """OWE-07: physical and sold-in-possession leave together, on one movement."""
    held = _owe(quantity=3, reserved=2)

    plan = sm.we_owe_fulfillment_targets(held, 2, sm.WE_OWE_SOURCE_KERNEL)

    assert (plan.target.fulfilled_qty, plan.target.remaining_qty, plan.target.reserved_qty) == (2, 1, 0)
    assert plan.target.uncovered_qty == 1, "the third Kernel is still owed and no longer covered"
    assert (plan.kernel_physical_delta, plan.sold_possession_delta) == (-2, -2)
    assert (plan.source, plan.quantity) == (sm.WE_OWE_SOURCE_KERNEL, 2)
    assert plan.inventory_movement_id is not None
    assert plan.target.status == sm.WE_OWE_STATUS_OPEN and plan.target.close_reason is None
    assert plan.target.release_qty == 0, "the WE_OWE_FULFILL movement carries the possession decrement"

    whole = sm.we_owe_fulfillment_targets(_owe(quantity=2, reserved=2), 2, sm.WE_OWE_SOURCE_KERNEL)
    assert (whole.target.status, whole.target.close_reason, whole.target.uncovered_qty) == (
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_FULFILLED,
        0,
    )


def test_an_external_fulfillment_moves_no_stock_and_may_only_reach_the_uncovered_quantity() -> None:
    """OWE-07: a Council supplies what Kernel stock is not already promised to."""
    held = _owe(quantity=4, reserved=3)

    plan = sm.we_owe_fulfillment_targets(held, 1, sm.WE_OWE_SOURCE_EXTERNAL)

    assert (plan.kernel_physical_delta, plan.sold_possession_delta) == (0, 0)
    assert plan.inventory_movement_id is None
    assert (plan.target.reserved_qty, plan.target.uncovered_qty) == (3, 0)

    covered = pytest.raises(AppError, lambda: sm.we_owe_fulfillment_targets(held, 2, sm.WE_OWE_SOURCE_EXTERNAL)).value
    assert covered.error_code == ErrorCode.CONFLICT
    assert covered.details["subcode"] == sm.FULFILLMENT_ABOVE_UNCOVERED
    assert "release the reservation" in covered.message, "the refusal names the step the admin has to take first"


def test_a_fulfillment_refuses_excess_a_bad_source_and_a_closed_obligation() -> None:
    """§4.4.3: the excess refusals say which bound they hit; zero and a bad source never get that far."""
    held = _owe(quantity=3, reserved=1)

    assert (
        pytest.raises(AppError, lambda: sm.we_owe_fulfillment_targets(held, 4, sm.WE_OWE_SOURCE_KERNEL)).value.details[
            "subcode"
        ]
        == sm.FULFILLMENT_ABOVE_REMAINING
    )
    assert (
        pytest.raises(AppError, lambda: sm.we_owe_fulfillment_targets(held, 2, sm.WE_OWE_SOURCE_KERNEL)).value.details[
            "subcode"
        ]
        == sm.FULFILLMENT_ABOVE_RESERVED
    )
    for build in (
        lambda: sm.we_owe_fulfillment_targets(held, 0, sm.WE_OWE_SOURCE_KERNEL),
        lambda: sm.we_owe_fulfillment_targets(held, 1, "SCOUT_CUSTODY"),
        lambda: sm.we_owe_fulfillment_targets(held, 1.5, sm.WE_OWE_SOURCE_EXTERNAL),
    ):
        assert pytest.raises(AppError, build).value.error_code == ErrorCode.INVALID_INPUT

    refused = pytest.raises(
        AppError, lambda: sm.we_owe_fulfillment_targets(_owe(quantity=2, fulfilled=2), 1, sm.WE_OWE_SOURCE_EXTERNAL)
    ).value
    assert refused.details["subcode"] == sm.WE_OWE_OBLIGATION_CLOSED


def test_an_obligation_closes_fulfilled_or_cancelled_and_never_a_third_way() -> None:
    """§4.4.1: two endings, both audit detail on a CLOSED row, never a third status."""
    fulfilled = sm.we_owe_fulfillment_targets(_owe(quantity=1, reserved=1), 1, sm.WE_OWE_SOURCE_KERNEL).target
    assert (fulfilled.status, fulfilled.close_reason) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_FULFILLED)

    cancelled = sm.we_owe_correction_targets(_owe(quantity=3, reserved=2), 0)
    assert (cancelled.status, cancelled.close_reason) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_CANCELLED)
    assert (cancelled.cancelled_qty, cancelled.remaining_qty, cancelled.reserved_qty) == (3, 0, 0)
    assert cancelled.release_qty == 2, "the reservation goes with the quantity in the same write"

    reopened = sm.we_owe_reservation_targets(_owe(quantity=3, cancelled=2), 1, unassigned_qty=4)
    assert (reopened.status, reopened.close_reason, reopened.remaining_qty) == (
        sm.WE_OWE_STATUS_OPEN,
        None,
        1,
    )


def test_an_invalid_obligation_state_is_a_violation_not_a_report_category() -> None:
    """§5.15's invariant block, stated over the row a read would return."""
    bogus = dict(_owe(quantity=2))
    bogus[sm.STATUS_ATTRIBUTE] = "PARTIALLY_FULFILLED"
    assert any("status must be one of" in line for line in sm.we_owe_invariant_violations(bogus))

    closed_but_owed = dict(_owe(quantity=2, fulfilled=2))
    closed_but_owed[sm.REMAINING_QTY_ATTRIBUTE] = 1
    assert any("CLOSED requires" in line for line in sm.we_owe_invariant_violations(closed_but_owed))

    over_reserved = _owe(quantity=3, reserved=4)
    assert any("between 0 and remainingQty" in line for line in sm.we_owe_invariant_violations(over_reserved))

    drift = dict(_owe(quantity=3, fulfilled=1))
    drift[sm.REMAINING_QTY_ATTRIBUTE] = 3
    assert any("remainingQty must equal" in line for line in sm.we_owe_invariant_violations(drift))

    assert sm.we_owe_invariant_violations(_owe(quantity=3, fulfilled=1, reserved=1)) == []


# --- §4.4.2, §4.4.3: the version guard -------------------------------------------


def test_a_stale_expected_version_names_the_obligation_that_moved() -> None:
    """VER-01 for both writes: the refusal says which obligation raced, before any plan is built."""
    row = _owe(quantity=3)
    sm.require_we_owe_version(row, 1)

    error = pytest.raises(AppError, lambda: sm.require_we_owe_version(row, 4)).value
    assert error.error_code == ErrorCode.CONFLICT
    assert error.details["subcode"] == sm.WE_OWE_VERSION_STALE
    assert error.details["we_owe_id"] == row[sm.WE_OWE_ID_ATTRIBUTE]
    assert (error.details["expectedVersion"], error.details["currentVersion"]) == (4, 1)


def test_a_fulfillment_write_moves_the_fulfilled_quantity_and_nothing_else() -> None:
    """§4.4.3: the fulfilled term is the fulfillment path's one extra term."""
    row = _owe(quantity=3)
    plan = sm.we_owe_fulfillment_targets(row, 1, sm.WE_OWE_SOURCE_EXTERNAL)
    action, body = sm.we_owe_update_action(row=row, target=plan.target, updated_at=LATER, fulfilled_qty=1)

    assert action == "Update"
    expression = body["UpdateExpression"]
    for name in (
        sm.FULFILLED_QTY_ATTRIBUTE,
        sm.RESERVED_QTY_ATTRIBUTE,
        sm.REMAINING_QTY_ATTRIBUTE,
        sm.UNCOVERED_QTY_ATTRIBUTE,
        sm.VERSION_ATTRIBUTE,
    ):
        assert f"#{name} = " in expression or f"#{name}=" in expression, f"{name} is not written"
    assert body["ConditionExpression"].startswith("#version = :expectedVersion")

    correction = sm.we_owe_correction_targets(row, 1)
    _, correction_body = sm.we_owe_update_action(row=row, target=correction, updated_at=LATER)
    assert sm.FULFILLED_QTY_ATTRIBUTE not in correction_body["UpdateExpression"], (
        "§8.6.1 keeps a fulfilled quantity historical: a correction never moves it"
    )


# --- §4.4.2, §4.4.3: the version guard -------------------------------------------


def test_the_obligation_reads_answer_the_rows_they_are_stored_as() -> None:
    """§4.4.1: the origin links, the snapshots, and the versions a follow-up write conditions on."""
    line = _line(quantity=3)
    row = _owe(quantity=3, fulfilled=1, reserved=1, line=line)
    payload = sm.we_owe_payload(row)

    assert payload["saleId"] == "sale-owe-model-1"
    assert payload["lineItemId"] == line[sm.LINE_ITEM_ID_ATTRIBUTE]
    assert payload["showAndSellId"] == EVENT and payload["unitCampaignId"] == CAMPAIGN
    assert payload["buyerName"] == "Buyer Bee"
    assert payload["productNameSnapshot"] == "Caramel Cremes"
    assert payload["valueCentsSnapshot"] == 1500, "three Kernels at the sale's snapshot price"
    assert (payload["originalQty"], payload["fulfilledQty"], payload["reservedQty"]) == (3, 1, 1)
    assert (payload["remainingQty"], payload["uncoveredQty"], payload["version"]) == (2, 1, 1)
    assert (payload["status"], payload["closeReason"], payload["closedAt"]) == (
        sm.WE_OWE_STATUS_OPEN,
        None,
        None,
    )


def test_the_fulfillment_marker_keeps_an_obligation_read_out_of_its_history() -> None:
    """§6.4: one sort-key range holds both kinds, so the marker is what separates them."""
    obligation_id = str(sm.new_we_owe_id())
    parent = sm.we_owe_sk(obligation_id)
    child = sm.we_owe_fulfillment_sk(obligation_id, str(sm.new_fulfillment_id()))

    assert child.startswith(f"{parent}{ssm.WE_OWE_FULFILLMENT_SK_MARKER}")
    assert ssm.WE_OWE_FULFILLMENT_SK_MARKER not in parent
    assert child != parent, "a fulfillment never overwrites the obligation it belongs to"


def test_a_reservation_releases_only_what_the_target_lets_go() -> None:
    """§4.4.2: the released quantity is ``before - target``, never the whole reservation."""
    held = _owe(quantity=5, fulfilled=1, reserved=3)
    target = sm.we_owe_reservation_targets(held, 2, unassigned_qty=1)

    assert (target.remaining_qty, target.reserved_qty, target.uncovered_qty) == (4, 2, 2)
    assert target.release_qty == 1
    assert target.status == sm.WE_OWE_STATUS_OPEN


def test_the_reservation_and_fulfillment_movements_are_the_two_the_trail_needs() -> None:
    """§4.4.2, §4.4.3: one movement per write, each naming what it was for."""
    campaign_product = {"unit_campaign_id": CAMPAIGN, "product_id": PRODUCT}
    common = {"actor_account_id": AVERY, "occurred_at": NOW, "idempotency_key": "owe-1"}

    action, body = sm.we_owe_reserve_movement_action(
        **campaign_product, we_owe_id="owe-1", reserve_qty=2, inventory_version=3, **common
    )
    reserve = body["Item"]
    assert action == "Put"
    assert reserve[inv.MOVEMENT_TYPE_ATTRIBUTE]["S"] == inv.WE_OWE_RESERVE
    assert int(reserve[inv.SOLD_POSSESSION_DELTA]["N"]) == 2
    assert int(reserve.get(inv.KERNEL_PHYSICAL_DELTA, {}).get("N", 0)) == 0, "a reservation leaves physical stock alone"
    assert reserve[inv.WE_OWE_ID_ATTRIBUTE]["S"] == "owe-1"

    action, body = sm.we_owe_fulfill_movement_action(
        **campaign_product,
        we_owe_id="owe-1",
        fulfillment_id="ful-1",
        movement_id="mov-1",
        quantity=2,
        inventory_version=4,
        **common,
    )
    fulfill = body["Item"]
    assert fulfill[inv.MOVEMENT_TYPE_ATTRIBUTE]["S"] == inv.WE_OWE_FULFILL
    assert int(fulfill[inv.KERNEL_PHYSICAL_DELTA]["N"]) == -2
    assert int(fulfill[inv.SOLD_POSSESSION_DELTA]["N"]) == -2
    assert fulfill[inv.FULFILLMENT_ID_ATTRIBUTE]["S"] == "ful-1", "the record and the movement name each other"

    action, body = sm.we_owe_release_movement_action(
        **campaign_product, we_owe_id="owe-1", release_qty=2, inventory_version=5, **common
    )
    assert body["Item"][inv.MOVEMENT_TYPE_ATTRIBUTE]["S"] == inv.WE_OWE_RELEASE
    assert int(body["Item"][inv.SOLD_POSSESSION_DELTA]["N"]) == -2


def test_the_obligation_and_its_history_are_two_rows_that_name_each_other() -> None:
    """§6.4: the record's parent link is the obligation's id, so either row answers the other."""
    obligation = _owe(quantity=3)
    obligation_id = str(obligation[sm.WE_OWE_ID_ATTRIBUTE])
    record = _record(we_owe_id=obligation_id, source=sm.WE_OWE_SOURCE_EXTERNAL)

    assert record[sm.WE_OWE_ID_ATTRIBUTE] == obligation_id
    assert sm.we_owe_fulfillment_sk(obligation_id, str(record[sm.FULFILLMENT_ID_ATTRIBUTE])).startswith(
        sm.we_owe_sk(obligation_id)
    )
    assert sm.we_owe_key(EVENT, obligation_id) != sm.we_owe_fulfillment_key(
        EVENT, obligation_id, str(record[sm.FULFILLMENT_ID_ATTRIBUTE])
    )


def test_a_missing_obligation_on_the_replay_loader_is_an_internal_fault(show_and_sells_table: Any) -> None:
    """The replay loader cannot answer with a fresh write, so a gone obligation is not a NOT_FOUND."""
    with pytest.raises(AppError) as raised:
        sm.load_we_owe_or_internal(EVENT, "00000000-0000-4000-8000-000000000000")
    assert raised.value.error_code == ErrorCode.INTERNAL_ERROR
    assert "could not be loaded" in raised.value.message
