"""Leaf 2.1 — inventory persistence and the derived quantities.

Persistence-level tests for §2.1.1 and §2.1.2: the §6.3 product-prefix key layout,
the item builders and the §4.1/§5.9/§5.11 invariants they refuse, the allocation
equation and its OPEN/RELEASED/CANCELLED machine, Scout-custody identity, the
append-only rule on movement rows, and the pure §7 derived helpers.

The derived helpers are the part a page renders, so they are tested as a table:
zero stock, an open reservation, sequential over-assignment, a released
allocation, and several Scouts holding the same product are all cases an admin
screen has to show correctly, and each one answers from the raw rows rather than
from any stored counter (§7's "never store what you can compute").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest
from botocore.exceptions import ClientError

from src.utils import inventory_models as inv
from src.utils.dynamodb import get_dynamodb_client
from src.utils.errors import AppError, ErrorCode

CAMPAIGN = "uc-pack-3149-fall-2026"
# The product ids this application actually spells: the catalog id is part of the
# product id, so a `#` sits inside it.
PRODUCT = "CATALOG#fixture-default#prod-1"
SIBLING = "CATALOG#fixture-default#prod-10"
SCOUT = "PROFILE#devon-uuid"
OTHER_SCOUT = "PROFILE#riley-uuid"
EVENT = "SSE#morning"
NOW = "2026-11-01T00:00:00+00:00"
LATER = "2026-11-01T12:00:00+00:00"


def _balance(physical: Any = 0, reserved: Any = 0, on_order: Any = 0, **overrides: Any) -> Dict[str, Any]:
    return inv.build_inventory_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        kernel_physical_qty=physical,
        sold_in_possession_qty=reserved,
        council_on_order_qty=on_order,
        now_iso=NOW,
        **overrides,
    )


def _allocation(
    allocated: Any,
    sold: Any = 0,
    released: Any = 0,
    status: str = inv.ALLOCATION_OPEN,
    show_and_sell_id: str = EVENT,
) -> Dict[str, Any]:
    return inv.build_event_inventory_allocation_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        show_and_sell_id=show_and_sell_id,
        start_at="2026-11-07T08:00:00+00:00",
        end_at="2026-11-07T12:00:00+00:00",
        allocated_qty=allocated,
        sold_qty=sold,
        released_qty=released,
        status=status,
        now_iso=NOW,
    )


def _custody(qty: Any, profile_id: str = SCOUT) -> Dict[str, Any]:
    return inv.build_scout_custody_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        profile_id=profile_id,
        campaign_id="CAMPAIGN#devon-fixture",
        with_scout_qty=qty,
        now_iso=NOW,
    )


def _movement(kind: str = inv.RECEIPT, **kwargs: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "movement_id": "mov-1",
        "unit_campaign_id": CAMPAIGN,
        "product_id": PRODUCT,
        "movement_type": kind,
        "actor_account_id": "acct-avery",
        "occurred_at": NOW,
        "idempotency_key": "idem-1",
    }
    arguments.update(kwargs)
    return inv.build_inventory_movement_item(**arguments)


# --- key layout (§6.3) -----------------------------------------------------------


def test_one_partition_holds_a_campaign_and_every_row_kind_has_its_own_sort_key() -> None:
    """Balance, allocation, custody and movement rows share the campaign partition."""
    assert inv.inventory_pk(CAMPAIGN) == f"UNIT_CAMPAIGN#{CAMPAIGN}"
    assert inv.balance_sk(PRODUCT) == f"PRODUCT#{PRODUCT}#BALANCE"
    assert inv.allocation_sk(PRODUCT, EVENT) == f"PRODUCT#{PRODUCT}#EVENT#{EVENT}"
    assert inv.custody_sk(PRODUCT, SCOUT) == f"PRODUCT#{PRODUCT}#CUSTODY#{SCOUT}"
    assert inv.balance_key(CAMPAIGN, PRODUCT) == {"pk": inv.inventory_pk(CAMPAIGN), "sk": inv.balance_sk(PRODUCT)}
    assert inv.custody_key(CAMPAIGN, PRODUCT, SCOUT)["sk"] == inv.custody_sk(PRODUCT, SCOUT)


def test_product_ids_keep_their_hash_because_that_is_how_they_are_spelled() -> None:
    """An interior ``#`` is normal; an empty segment is what collides with a marker.

    Refusing every ``#`` would make this surface unable to name the products it
    exists to count, since a catalog product id is ``<catalogId>#prod-N``.
    """
    assert inv.normalize_inventory_id(PRODUCT, "productId") == PRODUCT
    for hostile in ("#lead", "trail#", "mid##dle", "", "   "):
        with pytest.raises(AppError) as caught:
            inv.normalize_inventory_id(hostile, "productId")
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
    with pytest.raises(AppError):
        inv.normalize_inventory_id(None, "productId")
    with pytest.raises(AppError):
        inv.normalize_inventory_id("x" * 500, "productId")


def test_movement_sort_key_orders_by_instant_then_identity() -> None:
    """Business time is the sort dimension; the id only breaks a same-instant tie."""
    first = inv.movement_sk(PRODUCT, "2026-11-07T08:00:00+00:00", "mov-a")
    same_instant = inv.movement_sk(PRODUCT, "2026-11-07T08:00:00+00:00", "mov-b")
    later = inv.movement_sk(PRODUCT, "2026-11-07T08:00:01+00:00", "mov-z")
    assert first != same_instant
    assert first < same_instant < later


def test_sort_key_spelling_is_fixed_so_lexicographic_order_is_chronological() -> None:
    """``Z`` and ``+00:00`` for one instant must produce one sort key, not two."""
    assert inv.movement_sk(PRODUCT, "2026-11-07T08:00:00Z", "mov-a") == inv.movement_sk(
        PRODUCT, "2026-11-07T08:00:00+00:00", "mov-a"
    )
    offset = inv.movement_sk(PRODUCT, "2026-11-07T03:00:00-05:00", "mov-a")
    assert offset == inv.movement_sk(PRODUCT, "2026-11-07T08:00:00+00:00", "mov-a")


def test_a_product_prefix_cannot_reach_a_sibling_product() -> None:
    """``prod-1`` and ``prod-10`` share a textual prefix and must stay separate.

    The closing ``#`` in the prefix is what makes the range exact; without it a
    position read for one product would return the other's balance and movements.
    """
    prefix = inv.product_scope_prefix(PRODUCT)
    assert prefix == f"PRODUCT#{PRODUCT}#"
    assert not SIBLING.startswith(f"{PRODUCT}#")
    assert not inv.product_movement_prefix(PRODUCT).startswith(inv.product_movement_prefix(SIBLING))
    assert inv.product_movement_prefix(PRODUCT) == f"{prefix}MOVEMENT#"


# --- builders and invariants (§2.1.1) --------------------------------------------


def test_a_balance_row_stores_every_quantity_including_zero() -> None:
    """A row that "means" zero by omitting an attribute breaks the next write.

    Update and condition expressions on a missing attribute fail against real
    DynamoDB, so the builder writes the zeros it is given.
    """
    item = _balance(0, 0, 0)
    for attribute in inv.BALANCE_QUANTITY_ATTRIBUTES:
        assert attribute in item and item[attribute] == 0
    assert item["entityType"] == "InventoryBalance"
    assert item["version"] == 1
    assert item["createdAt"] == item["updatedAt"] == NOW
    assert item["unitCampaignId"] == CAMPAIGN and item["productId"] == PRODUCT


def test_a_balance_row_may_not_hold_stock_below_what_we_owe_reserved() -> None:
    """§4.1: ``kernelPhysicalQty >= soldInPossessionQty >= 0``."""
    assert inv.balance_invariant_violations(_balance(4, 4, 0)) == []
    with pytest.raises(AppError) as caught:
        _balance(3, 4)
    assert caught.value.error_code is ErrorCode.INVALID_INPUT
    assert "kernelPhysicalQty" in str(caught.value.message)
    assert any(
        "kernelPhysicalQty is below soldInPossessionQty" in v
        for v in inv.balance_invariant_violations(
            {"kernelPhysicalQty": 3, "soldInPossessionQty": 4, "councilOnOrderQty": 0}
        )
    )
    assert any(
        "soldInPossessionQty is negative" in v
        for v in inv.balance_invariant_violations(
            {"kernelPhysicalQty": 5, "soldInPossessionQty": -1, "councilOnOrderQty": 0}
        )
    )
    assert any(
        "councilOnOrderQty is negative" in v
        for v in inv.balance_invariant_violations(
            {"kernelPhysicalQty": 5, "soldInPossessionQty": 0, "councilOnOrderQty": -1}
        )
    )


def test_the_invariant_checkers_classify_a_stored_row_without_raising() -> None:
    """These run against rows already in the table, so a junk type is a finding.

    A DynamoDB number arrives as a ``Decimal``; anything else is a row some other
    writer got wrong. Neither may turn an audit read into an exception, and a
    ``bool`` is never a count — a missing quantity reads as zero, which is what the
    §4.1 comparison then judges.
    """
    assert (
        inv.balance_invariant_violations(
            {"kernelPhysicalQty": Decimal("9"), "soldInPossessionQty": Decimal("4"), "councilOnOrderQty": "3"}
        )
        == []
    )
    assert inv.balance_invariant_violations({"kernelPhysicalQty": True, "soldInPossessionQty": None}) == []
    assert inv.custody_invariant_violations({"withScoutQty": "two"}) == []


def test_the_allocation_remainder_is_derived_never_supplied() -> None:
    """``remainingQty`` is computed from the parts so it cannot contradict them."""
    item = _allocation(10, sold=3, released=2)
    assert item["remainingQty"] == 5
    hostile = dict(item, remainingQty=99)
    assert any("remainingQty does not equal" in v for v in inv.allocation_invariant_violations(hostile))
    # A row whose parts are internally consistent but impossible: a released count
    # below zero is a finding even though the arithmetic still closes.
    impossible = {
        "allocatedQty": 6,
        "soldQty": 0,
        "releasedQty": -1,
        "remainingQty": 7,
        "allocationStatus": inv.ALLOCATION_OPEN,
    }
    assert inv.allocation_invariant_violations(impossible) == ["releasedQty is negative"]


def test_allocation_equations_are_refused_at_the_builder() -> None:
    """Sold cannot exceed allocated and the remainder cannot go negative."""
    for arguments, expected in (
        ((6, 7, 0), "allocatedQty is below soldQty"),
        ((6, 1, 8), "remainingQty is negative"),
    ):
        with pytest.raises(AppError) as caught:
            _allocation(*arguments)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
        assert expected in str(caught.value.message)


def test_allocation_status_moves_once_and_never_back() -> None:
    """OPEN may be released or cancelled; both endings are terminal (§5.11)."""
    inv.require_allocation_transition(inv.ALLOCATION_OPEN, inv.ALLOCATION_RELEASED)
    inv.require_allocation_transition(inv.ALLOCATION_OPEN, inv.ALLOCATION_CANCELLED)
    for current, target in (
        (inv.ALLOCATION_RELEASED, inv.ALLOCATION_OPEN),
        (inv.ALLOCATION_RELEASED, inv.ALLOCATION_CANCELLED),
        (inv.ALLOCATION_CANCELLED, inv.ALLOCATION_OPEN),
        (inv.ALLOCATION_CANCELLED, inv.ALLOCATION_RELEASED),
    ):
        with pytest.raises(AppError) as caught:
            inv.require_allocation_transition(current, target)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
        assert f"from {current} to {target}" in str(caught.value.message)
    with pytest.raises(AppError):
        inv.normalize_allocation_status("DONE")
    assert (
        inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at="2026-11-07T08:00:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            allocated_qty=4,
            status=inv.ALLOCATION_CANCELLED,
            now_iso=NOW,
        )["status"]
        == "CANCELLED"
    )


def test_custody_is_one_row_per_product_and_scout_and_names_its_campaign() -> None:
    """§5.9: the same Scout in two Unit Campaigns holds two separate custodies."""
    one = _custody(4)
    two = _custody(4, profile_id=OTHER_SCOUT)
    assert one["sk"] != two["sk"]
    assert one["profileId"] == SCOUT and one["campaignId"] == "CAMPAIGN#devon-fixture"
    assert inv.custody_invariant_violations(one) == []
    with pytest.raises(AppError):
        _custody(-1)
    assert inv.custody_invariant_violations({"withScoutQty": -1}) == ["withScoutQty is negative"]


def test_a_movement_row_carries_no_version_and_no_undeclared_attribute() -> None:
    """History is append-only: a ``version`` attribute would advertise a mutation path."""
    row = _movement(inv.RECEIPT, kernel_physical_delta=12, inventory_version=1, reason="delivered")
    assert inv.movement_row_violations(row) == []
    assert "version" not in row
    assert inv.movement_row_violations(dict(row, version=2)) == [
        "unexpected attribute version",
        "version would make an append-only movement mutable",
    ]
    assert any("unexpected attribute smuggledQty" in v for v in inv.movement_row_violations(dict(row, smuggledQty=5)))


def test_a_movement_may_only_move_the_quantities_its_type_owns() -> None:
    """§5.8 assigns each delta to specific types; a receipt cannot also assign stock."""
    _movement(inv.SCOUT_ISSUE, kernel_physical_delta=-2, with_scout_delta=2, profile_id=SCOUT, show_and_sell_id=EVENT)
    with pytest.raises(AppError) as caught:
        _movement(inv.RECEIPT, kernel_physical_delta=5, assigned_delta=5)
    assert "assignedDelta" in str(caught.value.message)
    with pytest.raises(AppError):
        _movement(inv.COUNCIL_ON_ORDER_ADJUST, kernel_physical_delta=1, council_on_order_delta=1)
    # A reversal mirrors the movement it reverses, so any delta is legal for it.
    _movement(inv.REVERSAL, kernel_physical_delta=-3, with_scout_delta=3, fulfillment_id="ful-1")


def test_a_movement_delta_beyond_the_countable_range_is_refused() -> None:
    """One movement cannot record a quantity no Kernel count could hold."""
    for delta in (inv.MAX_QUANTITY + 1, -(inv.MAX_QUANTITY + 1)):
        with pytest.raises(AppError) as caught:
            _movement(inv.RECEIPT, kernel_physical_delta=delta, inventory_version=1)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
        assert "kernelPhysicalDelta" in str(caught.value.message)


def test_a_movement_names_the_event_sale_order_or_scout_it_came_from() -> None:
    """An audit row with no source is untraceable, which is the trail's whole point."""
    _movement(inv.EVENT_ASSIGN, assigned_delta=3, show_and_sell_id=EVENT)
    with pytest.raises(AppError) as caught:
        _movement(inv.EVENT_ASSIGN, assigned_delta=3)
    assert "showAndSellId" in str(caught.value.message)
    with pytest.raises(AppError):
        _movement(inv.SCOUT_ISSUE, kernel_physical_delta=-1, with_scout_delta=1)
    with pytest.raises(AppError):
        _movement(inv.INDIVIDUAL_FULFILL, kernel_physical_delta=-1, order_id="order-1")
    with pytest.raises(AppError):
        _movement(inv.RECEIPT, kernel_physical_delta=1, movement_type="DONATION")  # type: ignore[arg-type]


def test_a_custody_movement_needs_the_scout_and_never_an_event_it_did_not_happen_at() -> None:
    """§2.3 issue and return are custody acts, not event acts (CUST-01, CUST-06).

    Stock goes from the Kernel's shelf to the Scout's trunk outside any Show & Sell,
    so the Scout is the only source the row can honestly name. Demanding a
    ``showAndSellId`` here would make the two movements that create and undo a custody
    impossible to record, and inventing one would put a stock change behind an event
    that never promised it.
    """
    issued = _movement(inv.SCOUT_ISSUE, kernel_physical_delta=-3, with_scout_delta=3, profile_id=SCOUT)
    returned = _movement(inv.SCOUT_RETURN, kernel_physical_delta=3, with_scout_delta=-3, profile_id=SCOUT)
    assert issued["profileId"] == SCOUT and "showAndSellId" not in issued
    assert returned["profileId"] == SCOUT and "showAndSellId" not in returned
    for kind in (inv.SCOUT_ISSUE, inv.SCOUT_RETURN):
        with pytest.raises(AppError) as caught:
            _movement(kind, kernel_physical_delta=-1, with_scout_delta=1)
        assert "profileId" in str(caught.value.message)


# --- validators -------------------------------------------------------------------


def test_quantity_and_delta_rules_reject_what_a_form_should_not_send() -> None:
    """A receipt must be positive; an adjustment must be signed and nonzero."""
    assert inv.normalize_quantity(Decimal("12"), "quantity", minimum=1) == 12
    assert inv.normalize_signed_delta(-3, "quantityDelta", nonzero=True) == -3
    # A Decimal that is not a count is refused too: ``int(Decimal("NaN"))`` raises,
    # and a handler that let the exception escape would answer 500 instead of a
    # validation error.
    for value in (0, -1, None, True, 1.5, "4", Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(AppError) as caught:
            inv.normalize_quantity(value, "quantity", minimum=1)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
    with pytest.raises(AppError, match="must not be zero"):
        inv.normalize_signed_delta(0, "quantityDelta", nonzero=True)
    assert inv.normalize_signed_delta(0, "quantityDelta", nonzero=False) == 0
    with pytest.raises(AppError, match="at most"):
        inv.normalize_quantity(inv.MAX_QUANTITY + 1, "quantity")
    with pytest.raises(AppError, match="between"):
        inv.normalize_signed_delta(-(inv.MAX_QUANTITY + 1), "quantityDelta", nonzero=True)


def test_a_reason_is_required_for_the_paths_that_have_no_document_behind_them() -> None:
    assert inv.normalize_reason("  counted miscount  ", "reason", required=True) == "counted miscount"
    assert inv.normalize_reason(None, "reason", required=False) is None
    assert inv.normalize_reason("   ", "reason", required=False) is None
    with pytest.raises(AppError, match="is required"):
        inv.normalize_reason(None, "reason", required=True)
    with pytest.raises(AppError, match="must be a string"):
        inv.normalize_reason(12, "reason", required=True)
    with pytest.raises(AppError, match="at most"):
        inv.normalize_reason("x" * (inv.MAX_REASON_LENGTH + 1), "reason", required=False)


def test_moments_need_a_zone_because_an_assumed_one_cannot_be_detected_later() -> None:
    assert inv.normalize_moment("2026-11-07T08:00:00Z", "occurredAt") == "2026-11-07T08:00:00+00:00"
    for hostile in ("2026-11-07T08:00:00", "2026-11-07", "yesterday", None, 1730000000):
        with pytest.raises(AppError):
            inv.normalize_moment(hostile, "occurredAt")
    # A shape the pattern accepts and no calendar has: 30 February is a form bug,
    # and it must not become an instant that sorts somewhere the admin cannot find.
    with pytest.raises(AppError, match="time zone"):
        inv.normalize_moment("2026-02-30T08:00:00Z", "occurredAt")


def test_the_history_window_is_bounded_so_a_read_cannot_scan_forever() -> None:
    """§3.1: end after start, at most 366 days wide."""
    assert inv.normalize_date_range(None) == (None, None)
    start = "2026-01-01T00:00:00+00:00"
    assert inv.normalize_date_range({"startAt": start, "endAt": NOW})[1] == NOW
    with pytest.raises(AppError, match="must be after"):
        inv.normalize_date_range({"startAt": NOW, "endAt": NOW})
    wide = inv.normalize_date_range({"startAt": start})
    beyond = (datetime.fromisoformat(start) + timedelta(days=inv.MAX_DATE_RANGE_DAYS + 1)).isoformat()
    assert wide == (start, None)
    with pytest.raises(AppError, match="366 days"):
        inv.normalize_date_range({"startAt": start, "endAt": beyond})
    with pytest.raises(AppError):
        inv.normalize_date_range("2026-01-01")


def test_the_position_product_list_is_capped_and_deduplicated() -> None:
    """15 products is 15 range reads; a repeated id would answer the same row twice."""
    assert inv.normalize_product_ids(None) == []
    assert inv.normalize_product_ids([PRODUCT, SIBLING]) == [PRODUCT, SIBLING]
    with pytest.raises(AppError, match="at most 15"):
        inv.normalize_product_ids([f"p-{index}" for index in range(16)])
    with pytest.raises(AppError, match="must not repeat"):
        inv.normalize_product_ids([PRODUCT, PRODUCT])
    with pytest.raises(AppError):
        inv.normalize_product_ids(PRODUCT)


def test_a_custody_return_batch_needs_a_product_and_a_positive_quantity_each() -> None:
    """§2.3.2: a return is a batch of (product, quantity) pairs, and the batch is the atom.

    An empty batch is a click that would write a marker and no stock movement; a
    repeated product is two writes to one custody row, which one transaction cannot
    do at all; a zero or negative quantity is an issue wearing a return's shape.
    """
    assert inv.normalize_return_items(
        [{"productId": PRODUCT, "quantity": 2}, {"productId": SIBLING, "quantity": 3}]
    ) == [
        (PRODUCT, 2),
        (SIBLING, 3),
    ]
    for batch in (None, [], PRODUCT, [{"productId": PRODUCT}], [{"quantity": 2}]):
        with pytest.raises(AppError) as caught:
            inv.normalize_return_items(batch)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
    for quantity in (0, -3, "two", None, True):
        with pytest.raises(AppError, match="quantity"):
            inv.normalize_return_items([{"productId": PRODUCT, "quantity": quantity}])
    with pytest.raises(AppError, match="must not repeat"):
        inv.normalize_return_items([{"productId": PRODUCT, "quantity": 1}, {"productId": PRODUCT, "quantity": 2}])


# --- the derived quantities (§2.1.2) ----------------------------------------------


@pytest.mark.parametrize(
    ("label", "balance", "allocations", "custody", "expected"),
    [
        (
            "nothing received yet",
            None,
            [],
            [],
            {
                "sellableKernelQty": 0,
                "assignedOpenQty": 0,
                "unassignedKernelQty": 0,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 0,
            },
        ),
        (
            "stock received, nothing claimed",
            _balance(10),
            [],
            [],
            {
                "sellableKernelQty": 10,
                "assignedOpenQty": 0,
                "unassignedKernelQty": 10,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 10,
            },
        ),
        (
            "a reservation claims part of the stock",
            _balance(10),
            [_allocation(4)],
            [],
            {
                "sellableKernelQty": 10,
                "assignedOpenQty": 4,
                "unassignedKernelQty": 6,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 10,
            },
        ),
        (
            "sequential over-assignment is an overage, never a negative remainder",
            _balance(3),
            [_allocation(2, show_and_sell_id="SSE#morning"), _allocation(2, show_and_sell_id="SSE#afternoon")],
            [],
            {
                "sellableKernelQty": 3,
                "assignedOpenQty": 4,
                "unassignedKernelQty": 0,
                "assignmentOverageQty": 1,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 3,
            },
        ),
        (
            "a We Owe reservation stops being sellable without leaving the count",
            _balance(10, reserved=4),
            [_allocation(3)],
            [],
            {
                "sellableKernelQty": 6,
                "assignedOpenQty": 3,
                "unassignedKernelQty": 3,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 10,
            },
        ),
        (
            "released and cancelled allocations stop competing for stock",
            _balance(6),
            [
                _allocation(4, status=inv.ALLOCATION_RELEASED),
                _allocation(2, status=inv.ALLOCATION_CANCELLED, show_and_sell_id="SSE#afternoon"),
                _allocation(1, show_and_sell_id="SSE#evening"),
            ],
            [],
            {
                "sellableKernelQty": 6,
                "assignedOpenQty": 1,
                "unassignedKernelQty": 5,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 6,
            },
        ),
        (
            "a partial sale and a partial release leave the same remainder",
            _balance(6),
            [_allocation(6, sold=2, released=1)],
            [],
            {
                "sellableKernelQty": 6,
                "assignedOpenQty": 3,
                "unassignedKernelQty": 3,
                "assignmentOverageQty": 0,
                "withScoutQty": 0,
                "totalUnitOwnedUndeliveredQty": 6,
            },
        ),
        (
            "two Scouts holding the same product count once, together",
            _balance(4),
            [],
            [_custody(3), _custody(2, profile_id=OTHER_SCOUT)],
            {
                "sellableKernelQty": 4,
                "assignedOpenQty": 0,
                "unassignedKernelQty": 4,
                "assignmentOverageQty": 0,
                "withScoutQty": 5,
                "totalUnitOwnedUndeliveredQty": 9,
            },
        ),
        (
            "a full day: stock, reservations, custody and We Owe at once",
            _balance(20, reserved=5, on_order=8),
            [
                _allocation(6, sold=2, show_and_sell_id="SSE#morning"),
                _allocation(4, show_and_sell_id="SSE#afternoon"),
            ],
            [_custody(3), _custody(1, profile_id=OTHER_SCOUT)],
            {
                "sellableKernelQty": 15,
                "assignedOpenQty": 8,
                "unassignedKernelQty": 7,
                "assignmentOverageQty": 0,
                "withScoutQty": 4,
                "totalUnitOwnedUndeliveredQty": 24,
            },
        ),
    ],
    ids=[
        "zero-stock",
        "received",
        "reservation",
        "sequential-over-assignment",
        "we-owe-reserved",
        "released-allocations",
        "partial-sale-and-release",
        "multiple-custody-rows",
        "mixed-day",
    ],
)
def test_every_position_quantity_is_computed_from_the_raw_rows(
    label: str,
    balance: Optional[Dict[str, Any]],
    allocations: List[Dict[str, Any]],
    custody: List[Dict[str, Any]],
    expected: Dict[str, int],
) -> None:
    """§7 equations, one row per state an inventory screen has to render."""
    assert label
    derived = inv.derived_inventory_quantities(balance, allocations, custody)
    assert derived == expected
    assert derived["unassignedKernelQty"] + derived["assignmentOverageQty"] >= 0
    assert inv.sellable_kernel_qty(balance) == expected["sellableKernelQty"]
    assert inv.assigned_open_qty(allocations) == expected["assignedOpenQty"]
    assert inv.with_scout_qty(custody) == expected["withScoutQty"]
    assert inv.total_unit_owned_undelivered_qty(balance, custody) == expected["totalUnitOwnedUndeliveredQty"]


def test_no_derived_quantity_is_stored_on_any_row() -> None:
    """A stored copy is a counter a later write can forget, and a page would read it."""
    balance = _balance(10, on_order=4)
    stored = set(balance) - {
        "pk",
        "sk",
        "entityType",
        "unitCampaignId",
        "productId",
        "version",
        "createdAt",
        "updatedAt",
    }
    assert stored == set(inv.BALANCE_QUANTITY_ATTRIBUTES)
    for name in ("sellableKernelQty", "assignedOpenQty", "unassignedKernelQty", "assignmentOverageQty", "withScoutQty"):
        assert name not in balance


def test_the_council_on_order_balance_never_touches_the_sellable_count() -> None:
    """§4.1: on-order is expected supply counted beside the Kernels, not inside them."""
    quiet = inv.derived_inventory_quantities(_balance(10, on_order=0), [], [])
    loud = inv.derived_inventory_quantities(_balance(10, on_order=99), [], [])
    assert quiet == loud


# --- reads against the table (§6.3) -----------------------------------------------


def _put(table: Any, item: Dict[str, Any]) -> None:
    table.put_item(Item=item)


def test_a_product_range_returns_only_that_product(inventory_table: Any) -> None:
    """The prefix ends in ``#`` so ``prod-1`` never answers with ``prod-10``."""
    for product in (PRODUCT, SIBLING):
        _put(
            inventory_table,
            inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN, product_id=product, kernel_physical_qty=7, now_iso=NOW
            ),
        )
    rows = inv.read_inventory_product_rows(CAMPAIGN, PRODUCT)
    assert [row["sk"] for row in rows] == [inv.balance_sk(PRODUCT)]
    assert inv.read_inventory_balance(CAMPAIGN, PRODUCT)["productId"] == PRODUCT
    assert inv.read_inventory_balance(CAMPAIGN, "CATALOG#fixture-default#prod-99") is None


def test_a_product_range_excludes_a_product_whose_id_continues_this_one(inventory_table: Any) -> None:
    """``PRODUCT#P#`` is a range, and a product spelled ``P#<extra>`` lives inside it.

    The trailing ``#`` is what keeps ``prod-1`` from answering with ``prod-10``, but a
    nested id starts with the whole prefix of its parent, so its balance, allocation and
    custody rows fall into the parent's section. A mutation that plans from that section
    then writes the neighbour's row while bumping the parent's balance and auditing the
    parent — three rows disagreeing about which product moved. The row's own ``productId``
    attribute is the identity that separates them, which is also what the campaign-wide
    bucketing and the movement reader filter on.
    """
    nested = f"{PRODUCT}#case-lot"
    for product in (PRODUCT, nested):
        _put(
            inventory_table,
            inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN, product_id=product, kernel_physical_qty=4, now_iso=NOW
            ),
        )
        _put(
            inventory_table,
            inv.build_event_inventory_allocation_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product,
                show_and_sell_id=EVENT,
                start_at="2026-11-07T08:00:00+00:00",
                end_at="2026-11-07T12:00:00+00:00",
                allocated_qty=3,
                now_iso=NOW,
            ),
        )

    rows = inv.read_inventory_product_rows(CAMPAIGN, PRODUCT)
    assert {str(row["productId"]) for row in rows} == {PRODUCT}, "the range is not an identity test"
    sections = inv.inventory_position_rows(CAMPAIGN, PRODUCT)
    assert [row[inv.ALLOCATED_QTY] for row in sections["allocations"]] == [3]
    assert {row["productId"] for row in sections["balance"] + sections["allocations"]} == {PRODUCT}
    assert inv.read_inventory_balance(CAMPAIGN, nested)["productId"] == nested, "an exact key still finds it"


def test_sections_bucket_by_the_product_attribute_not_a_split_of_the_sort_key(inventory_table: Any) -> None:
    """A product id contains ``#``, so splitting the key would name the catalog.

    Bucketing that way merges two products of one catalog into a single position:
    the numbers would add up to a total no Scout could sell.
    """
    for product in (PRODUCT, SIBLING):
        _put(
            inventory_table,
            inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN, product_id=product, kernel_physical_qty=4, now_iso=NOW
            ),
        )
        _put(
            inventory_table,
            inv.build_scout_custody_balance_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product,
                profile_id=SCOUT,
                campaign_id="CAMPAIGN#devon",
                now_iso=NOW,
            ),
        )
        _put(
            inventory_table,
            inv.build_event_inventory_allocation_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product,
                show_and_sell_id=EVENT,
                start_at="2026-11-07T08:00:00+00:00",
                end_at="2026-11-07T12:00:00+00:00",
                allocated_qty=2,
                now_iso=NOW,
            ),
        )
    _put(
        inventory_table,
        inv.build_inventory_movement_item(
            movement_id="mov-1",
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            movement_type=inv.RECEIPT,
            actor_account_id="acct-avery",
            occurred_at=NOW,
            idempotency_key="idem-1",
            kernel_physical_delta=4,
        ),
    )

    sections = inv.campaign_product_sections(CAMPAIGN)
    assert list(sections) == sorted([PRODUCT, SIBLING])
    for product, bucket in sections.items():
        assert [row["productId"] for row in bucket["balance"]] == [product]
        assert len(bucket["allocations"]) == 1 and len(bucket["custody"]) == 1
        assert not any(row["entityType"] == "InventoryMovement" for rows in bucket.values() for row in rows)

    one = inv.campaign_product_sections(CAMPAIGN, [PRODUCT])
    assert list(one) == [PRODUCT]
    assert len(one[PRODUCT]["balance"]) == 1
    # A product the campaign has no rows for still answers as an empty section,
    # which is what lets a position render zeros before the first receipt.
    empty = inv.campaign_product_sections(CAMPAIGN, ["CATALOG#fixture-default#prod-99"])
    assert empty == {"CATALOG#fixture-default#prod-99": {"balance": [], "allocations": [], "custody": []}}


def test_a_position_row_that_names_no_product_is_not_a_position(inventory_table: Any) -> None:
    """A row that lost its ``productId`` cannot join a position.

    Bucketing it under an empty key would merge every malformed row of the campaign
    into one imaginary product and report its stock somewhere it cannot be traced.
    """
    _put(
        inventory_table,
        inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=4, now_iso=NOW
        ),
    )
    for sk, entity in (
        (inv.balance_sk("orphan"), inv.BALANCE_ENTITY_TYPE),
        (inv.custody_sk("orphan", SCOUT), inv.CUSTODY_ENTITY_TYPE),
    ):
        _put(inventory_table, {"pk": inv.inventory_pk(CAMPAIGN), "sk": sk, "entityType": entity})

    assert list(inv.campaign_product_sections(CAMPAIGN)) == [PRODUCT]


def test_a_history_read_applies_every_filter_it_was_given(inventory_table: Any) -> None:
    """Movements come back in key order for one product, one type, one Scout, one window."""
    moments = ["2026-11-07T08:00:00+00:00", "2026-11-07T09:00:00+00:00", "2026-11-08T08:00:00+00:00"]
    for index, moment in enumerate(moments):
        _put(
            inventory_table,
            inv.build_inventory_movement_item(
                movement_id=f"mov-{index}",
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                movement_type=inv.RECEIPT,
                actor_account_id="acct-avery",
                occurred_at=moment,
                idempotency_key=f"idem-{index}",
                kernel_physical_delta=1,
            ),
        )
    _put(
        inventory_table,
        inv.build_inventory_movement_item(
            movement_id="mov-scout",
            unit_campaign_id=CAMPAIGN,
            product_id=SIBLING,
            movement_type=inv.SCOUT_ISSUE,
            actor_account_id="acct-avery",
            occurred_at="2026-11-07T10:00:00+00:00",
            idempotency_key="idem-scout",
            kernel_physical_delta=-1,
            with_scout_delta=1,
            profile_id=SCOUT,
            show_and_sell_id=EVENT,
        ),
    )
    _put(
        inventory_table,
        inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=3, now_iso=NOW
        ),
    )

    campaign_wide = inv.list_inventory_movements(CAMPAIGN)
    assert [row["movementId"] for row in campaign_wide] == ["mov-0", "mov-1", "mov-scout", "mov-2"]

    strongly_consistent = inv.list_inventory_movements(CAMPAIGN, consistent=True)
    assert [row["movementId"] for row in strongly_consistent] == ["mov-0", "mov-1", "mov-scout", "mov-2"]

    product_only = inv.list_inventory_movements(CAMPAIGN, product_id=PRODUCT)
    assert [row["movementId"] for row in product_only] == ["mov-0", "mov-1", "mov-2"]

    by_type = inv.list_inventory_movements(CAMPAIGN, movement_type=inv.SCOUT_ISSUE)
    assert [row["movementId"] for row in by_type] == ["mov-scout"]

    by_scout = inv.list_inventory_movements(CAMPAIGN, profile_id=SCOUT)
    assert [row["movementId"] for row in by_scout] == ["mov-scout"]

    by_event = inv.list_inventory_movements(CAMPAIGN, show_and_sell_id=EVENT)
    assert [row["movementId"] for row in by_event] == ["mov-scout"]

    window = inv.list_inventory_movements(
        CAMPAIGN, start_at="2026-11-07T08:30:00+00:00", end_at="2026-11-07T23:59:59+00:00"
    )
    assert [row["movementId"] for row in window] == ["mov-1", "mov-scout"]

    combined = inv.list_inventory_movements(
        CAMPAIGN,
        product_id=PRODUCT,
        movement_type=inv.RECEIPT,
        start_at="2026-11-07T08:30:00+00:00",
        end_at="2026-11-07T23:59:59+00:00",
    )
    assert [row["movementId"] for row in combined] == ["mov-1"]


# --- custody reads and conditional custody writes (§2.3) --------------------------


def _transact(*actions: tuple[str, Dict[str, Any]]) -> None:
    """Run model-built actions through the real transaction API.

    The actions are the shapes the resolvers stage, and moto evaluates conditions and
    versions: this is where a floor that should cancel is proven to cancel, which no
    pure-python assertion can show. The plain client is required, not
    ``table.meta.client`` — the staged items are already wire-form, and the service
    resource's client re-encodes them as maps.
    """
    items = [{action: dict(params)} for action, params in actions]
    get_dynamodb_client().transact_write_items(TransactItems=items)


def test_a_balance_floor_cancels_the_request_that_read_the_last_kernel(inventory_table: Any) -> None:
    """§4.1 as DynamoDB enforces it: the loser of the race for the last unit writes nothing.

    The pre-read check buys the actionable message; the version pin plus the quantity
    floor is what makes "the last Kernel" a fact the transaction re-checks. The
    survivor is the request that still held the floor, and the shelf never goes below it.
    """
    _put(
        inventory_table,
        inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=1, now_iso=NOW
        ),
    )
    stale = inv.read_inventory_balance(CAMPAIGN, PRODUCT)
    assert stale is not None

    def stage(delta: int, version: int) -> None:
        _transact(
            inv.inventory_balance_delta_action(
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                existing=stale,
                expected_version=version,
                kernel_physical_delta=delta,
                now_iso=NOW,
            )
        )

    stage(-1, 1)
    assert inv.read_inventory_balance(CAMPAIGN, PRODUCT)["kernelPhysicalQty"] == 0
    with pytest.raises(ClientError) as caught:
        stage(-1, 1)
    assert caught.value.response["Error"]["Code"] == "TransactionCanceledException"
    assert "ConditionalCheckFailed" in str(caught.value)
    assert inv.read_inventory_balance(CAMPAIGN, PRODUCT)["kernelPhysicalQty"] == 0


def test_a_custody_row_reads_back_and_bounces_on_its_version(inventory_table: Any) -> None:
    """The custody read a write conditions on, and the version pin that serializes it."""
    _put(
        inventory_table,
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT,
            campaign_id="CAMPAIGN#devon-fixture",
            with_scout_qty=3,
            now_iso=NOW,
        ),
    )
    row = inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)
    assert row is not None
    assert (row["withScoutQty"], row["version"]) == (3, 1)
    assert inv.read_scout_custody(CAMPAIGN, PRODUCT, "PROFILE#prof-nobody") is None

    def change(existing: Any, version: int, delta: int) -> None:
        _transact(
            inv.scout_custody_delta_action(
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                profile_id=SCOUT,
                existing=existing,
                expected_version=version,
                with_scout_delta=delta,
                now_iso=NOW,
            )
        )

    change(row, 1, -2)
    after = inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)
    assert (after["withScoutQty"], after["version"]) == (1, 2)

    # The stale read from before that write is a request that no longer holds those Kernels.
    with pytest.raises(ClientError) as caught:
        change(row, 1, -1)
    assert caught.value.response["Error"]["Code"] == "TransactionCanceledException"
    assert inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)["withScoutQty"] == 1


def test_a_custody_floor_cancels_the_second_return_of_the_same_kernels(inventory_table: Any) -> None:
    """CUST-04: With Scout cannot go negative, so two returns of three cannot both land."""
    _put(
        inventory_table,
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT,
            campaign_id="CAMPAIGN#devon-fixture",
            with_scout_qty=3,
            now_iso=NOW,
        ),
    )
    held = inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)

    def return_three() -> None:
        _transact(
            inv.scout_custody_delta_action(
                unit_campaign_id=CAMPAIGN,
                product_id=PRODUCT,
                profile_id=SCOUT,
                existing=held,
                expected_version=1,
                with_scout_delta=-3,
                now_iso=NOW,
            )
        )

    return_three()
    with pytest.raises(ClientError) as caught:
        return_three()
    assert caught.value.response["Error"]["Code"] == "TransactionCanceledException"
    assert inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)["withScoutQty"] == 0


def test_the_first_custody_row_for_a_product_is_a_conditional_put(inventory_table: Any) -> None:
    """Two concurrent first issues to one Scout cannot both start from zero."""
    item = inv.build_scout_custody_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        profile_id=SCOUT,
        campaign_id="CAMPAIGN#devon-fixture",
        with_scout_qty=2,
        now_iso=NOW,
    )
    action = inv.put_scout_custody_action(item)
    assert action[0] == "Put"
    _transact(action)
    assert inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)["withScoutQty"] == 2
    with pytest.raises(ClientError) as caught:
        _transact(action)
    assert caught.value.response["Error"]["Code"] == "TransactionCanceledException"
    assert inv.read_scout_custody(CAMPAIGN, PRODUCT, SCOUT)["withScoutQty"] == 2


def test_a_campaign_custody_read_sees_only_custody_rows_and_the_filter_it_asked_for(inventory_table: Any) -> None:
    """The admin board's read: Scout rows only, filtered by Scout and by product."""
    for row in (
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT,
            campaign_id="CAMPAIGN#devon-fixture",
            with_scout_qty=4,
            now_iso=NOW,
        ),
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=OTHER_SCOUT,
            campaign_id="CAMPAIGN#riley-fixture",
            with_scout_qty=1,
            now_iso=NOW,
        ),
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=SIBLING,
            profile_id=SCOUT,
            campaign_id="CAMPAIGN#devon-fixture",
            with_scout_qty=2,
            now_iso=NOW,
        ),
        inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=10, now_iso=NOW
        ),
        _movement(inv.SCOUT_ISSUE, kernel_physical_delta=-4, with_scout_delta=4, profile_id=SCOUT),
    ):
        _put(inventory_table, row)

    every = inv.campaign_custody_rows(CAMPAIGN)
    assert [(row["profileId"], row["productId"], row["withScoutQty"]) for row in every] == [
        (SCOUT, PRODUCT, 4),
        (OTHER_SCOUT, PRODUCT, 1),
        (SCOUT, SIBLING, 2),
    ]
    assert [row["profileId"] for row in inv.campaign_custody_rows(CAMPAIGN, profile_id=SCOUT)] == [SCOUT, SCOUT]
    assert [
        (row["profileId"], row["productId"]) for row in inv.campaign_custody_rows(CAMPAIGN, product_id=PRODUCT)
    ] == [
        (SCOUT, PRODUCT),
        (OTHER_SCOUT, PRODUCT),
    ]
    assert inv.campaign_custody_rows(CAMPAIGN, profile_id=SCOUT, product_id=SIBLING)[0]["withScoutQty"] == 2
    assert inv.campaign_custody_rows(CAMPAIGN, profile_id="PROFILE#prof-nobody") == []
    assert inv.campaign_custody_rows("uc-nothing-here") == []
