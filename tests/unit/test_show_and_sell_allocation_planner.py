"""Wave 4.2 — the allocation-target planner and the interval evaluator (§3.2.1, §3.2.2).

Both leaves are pure, so these cases need no table: every one of them is the question
``assignShowAndSellInventory`` has to answer before it stages a write, and each assertion
names the rule the answer protects. The resolver-level half (the same rules against moto,
with the transaction and the audit trail) is
``tests/unit/test_show_and_sell_allocation.py``.

The scenario fixtures are the specification's own (§7 ALLOC-01..08): four boxes of caramel
that must not be promised three to each of two overlapping events (ALLOC-02, AC-09), and
three to a morning plus three to an afternoon against the same four, which is allowed and
has to be reported (ALLOC-03, AC-10). The interval fixtures use literal instants on
purpose — nothing here reads the clock, so a test cannot go stale the way a "tomorrow"
fixture does.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.utils import allocation_models as am
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils.errors import AppError, ErrorCode

CAMPAIGN = "uc-pack-3149-fall-2026"
MORNING_EVENT = "evt-morning"
AFTERNOON_EVENT = "evt-afternoon"
PRODUCT = "CATALOG#fixture-default#prod-1"
OTHER_PRODUCT = "CATALOG#fixture-default#prod-2"

MORNING_START, MORNING_END = "2026-11-07T09:00:00+00:00", "2026-11-07T12:00:00+00:00"
AFTERNOON_START, AFTERNOON_END = "2026-11-07T12:00:00+00:00", "2026-11-07T15:00:00+00:00"
OVERLAP_START, OVERLAP_END = "2026-11-07T10:00:00+00:00", "2026-11-07T14:00:00+00:00"


# --- Fixtures --------------------------------------------------------------------


def _event(
    show_and_sell_id: str = MORNING_EVENT,
    *,
    start_at: str = MORNING_START,
    end_at: str = MORNING_END,
    product_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """The event facts the planner reads: its id, its campaign, and its immutable interval."""
    row: Dict[str, Any] = {
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.START_AT_ATTRIBUTE: start_at,
        ssm.END_AT_ATTRIBUTE: end_at,
        ssm.PRODUCT_IDS_ATTRIBUTE: list(product_ids or []),
    }
    row.update(overrides)
    return row


def _allocation(
    show_and_sell_id: str,
    *,
    product_id: str = PRODUCT,
    start_at: str = MORNING_START,
    end_at: str = MORNING_END,
    allocated: int,
    sold: int = 0,
    released: int = 0,
    status: str = inv.ALLOCATION_OPEN,
    version: int = 1,
) -> Dict[str, Any]:
    """One stored allocation row, built by the model so its own invariants hold first."""
    return inv.build_event_inventory_allocation_item(
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        show_and_sell_id=show_and_sell_id,
        start_at=start_at,
        end_at=end_at,
        allocated_qty=allocated,
        sold_qty=sold,
        released_qty=released,
        status=status,
        now_iso=start_at,
        version=version,
    )


def _target(quantity: int, product_id: str = PRODUCT) -> am.AllocationTarget:
    return am.AllocationTarget(product_id=product_id, quantity=quantity)


# --- §3.2.1 — target, not delta --------------------------------------------------


def test_a_re_statement_of_the_target_is_not_an_amount_to_add() -> None:
    """§3.2.1: the caller sends the quantity it wants to see, and the delta is derived."""
    existing = _allocation(MORNING_EVENT, allocated=3)

    change = am.plan_allocation_target(_event(), _target(5), existing)

    assert change is not None
    assert change.allocated_qty == 5, "the row says 5, not 8"
    assert change.assigned_delta == 2, "and the movement reports the 2 this request moved"
    assert change.movement_type == inv.EVENT_ASSIGN
    assert change.remaining_qty == 5
    assert change.creates_row is False
    assert change.expected_version == 1, "the read row's version is what the write conditions on"


def test_a_lower_target_is_a_manual_reduction() -> None:
    """§3.2.1, ALLOC-04: a reduction is the same target rule, audited as ``EVENT_MANUAL_REDUCE``."""
    existing = _allocation(MORNING_EVENT, allocated=10)

    change = am.plan_allocation_target(_event(), _target(4), existing)

    assert change is not None
    assert (change.allocated_qty, change.assigned_delta, change.movement_type) == (4, -6, inv.EVENT_MANUAL_REDUCE)
    assert change.remaining_qty == 4


def test_a_target_of_zero_releases_the_remaining_allocation() -> None:
    """EVT-M-04-02: zero is a target that means "nothing", and it releases only this row's remainder."""
    existing = _allocation(MORNING_EVENT, allocated=10)

    change = am.plan_allocation_target(_event(), _target(0), existing)

    assert change is not None
    assert change.allocated_qty == 0
    assert change.remaining_qty == 0, "nothing is left assigned, so assignedOpenQty drops by 10"
    assert change.assigned_delta == -10
    assert change.status == inv.ALLOCATION_OPEN, "a manual reduction is not the RELEASED state §9.2 reserves"


def test_an_omitted_product_is_never_touched() -> None:
    """§3.2.1: a product with no entry in the batch is left exactly as it stands."""
    morning = _allocation(MORNING_EVENT, allocated=6)
    afternoon = _allocation(AFTERNOON_EVENT, allocated=7)

    changes = am.plan_allocation_targets(_event(), [_target(2)], {PRODUCT: morning})

    assert [change.allocated_qty for change in changes] == [2]
    assert afternoon[inv.ALLOCATED_QTY] == 7, "the plan is keyed by the batch, not by what is stored"


def test_a_first_target_creates_the_row_at_that_target() -> None:
    """§3.2.1: no row yet and a positive target — one row per (campaign, product, event)."""
    change = am.plan_allocation_target(_event(), _target(6), None)

    assert change is not None
    assert change.creates_row is True
    assert change.expected_version is None, "a Put carries attribute_not_exists, not a version pin"
    assert (change.allocated_qty, change.remaining_qty, change.movement_type) == (6, 6, inv.EVENT_ASSIGN)
    assert change.product_id == PRODUCT
    assert change.unit_campaign_id == CAMPAIGN
    assert change.start_at == MORNING_START and change.end_at == MORNING_END


def test_a_zero_target_for_a_product_the_event_never_held_writes_nothing() -> None:
    """An explicit zero for a product with no allocation is not a state change."""
    assert am.plan_allocation_target(_event(), _target(0), None) is None


def test_the_same_target_writes_nothing() -> None:
    """Restating an unchanged target would spend an action, a movement, and a version on nothing."""
    assert am.plan_allocation_target(_event(), _target(3), _allocation(MORNING_EVENT, allocated=3)) is None


def test_a_target_below_what_the_event_sold_and_released_is_refused() -> None:
    """§3.2.1 sold-stock protection: sold and released quantities are history, not a clamp target."""
    existing = _allocation(MORNING_EVENT, allocated=10, sold=4, released=2)

    with pytest.raises(AppError) as refused:
        am.plan_allocation_target(_event(), _target(5), existing)
    assert refused.value.error_code == ErrorCode.INVALID_INPUT
    assert "6" in refused.value.message

    at_the_floor = am.plan_allocation_target(_event(), _target(6), existing)
    assert at_the_floor is not None
    assert at_the_floor.remaining_qty == 0, "6 allocated, 4 sold, 2 released: the remainder is exactly 0"


def test_a_released_or_cancelled_allocation_is_not_re_opened() -> None:
    """§9.2: a terminal allocation's stock went back on the shelf; re-opening it counts it twice."""
    for status, subcode in ((inv.ALLOCATION_RELEASED, "ALLOCATION_CLOSED"), (inv.ALLOCATION_CANCELLED, None)):
        with pytest.raises(AppError) as refused:
            am.plan_allocation_target(_event(), _target(3), _allocation(MORNING_EVENT, allocated=0, status=status))
        assert refused.value.error_code == ErrorCode.CONFLICT
        assert refused.value.details is not None and refused.value.details["status"] == status
        assert subcode is None or refused.value.details["subcode"] == subcode


def test_sixteen_products_are_planned_and_the_product_list_stays_cumulative() -> None:
    """§5.10: no event-wide product cap — the ceiling is the write plan, never a count."""
    event = _event(product_ids=[f"CATALOG#fixture-default#prod-{index}" for index in range(1, 4)])
    products = [f"CATALOG#fixture-default#prod-{index}" for index in range(1, 17)]
    targets = [_target(1, product_id) for product_id in products]

    changes = am.plan_allocation_targets(event, targets, {})

    assert len(changes) == 16
    planned = am.planned_product_ids(event, changes)
    assert len(planned) == 16
    assert planned[:3] == [f"CATALOG#fixture-default#prod-{index}" for index in range(1, 4)], (
        "an entry that was already listed keeps its place"
    )
    assert len(set(planned)) == len(planned), "a repeated product would double-count an allocation read"


def test_a_released_product_stays_on_the_list() -> None:
    """§6.3: nothing removes an entry, or finalization's product walk loses the rows it must find."""
    existing = _allocation(MORNING_EVENT, allocated=4)
    change = am.plan_allocation_target(_event(product_ids=[PRODUCT]), _target(0), existing)

    assert change is not None
    assert am.planned_product_ids(_event(product_ids=[PRODUCT]), [change]) == [PRODUCT]


def test_the_batch_shape_rules_are_refused_before_any_planning() -> None:
    """§3.1 input contract: non-empty, one entry per product, quantity 0..1,000,000."""
    duplicate = {"productId": PRODUCT, "quantity": 4}
    refused_cases: List[tuple[Any, str]] = [
        ([], "an empty batch would answer a save that changed nothing"),
        (None, "a missing items list"),
        ("items", "an items value that is not a list"),
        ([duplicate, duplicate], "two entries for one product are two writes to one row"),
        ([{"productId": PRODUCT, "quantity": -1}], "a negative target"),
        ([{"productId": PRODUCT, "quantity": 1_000_001}], "over the §3.1 quantity maximum"),
        ([{"quantity": 4}], "a missing productId"),
        ([{"productId": "", "quantity": 4}], "a blank productId"),
        (["not-a-target"], "an entry that is not an object"),
        ([{"productId": PRODUCT, "quantity": True}], "a boolean is not a quantity"),
    ]
    for items, why in refused_cases:
        with pytest.raises(AppError) as refused:
            am.normalize_allocation_targets(items)
        assert refused.value.error_code == ErrorCode.INVALID_INPUT, why

    zero_is_meaningful = am.normalize_allocation_targets([{"productId": PRODUCT, "quantity": 0}])
    assert [(target.product_id, target.quantity) for target in zero_is_meaningful] == [(PRODUCT, 0)]


# --- §3.2.1 — the reopened draft -------------------------------------------------


def test_the_draft_map_is_merged_and_each_product_s_target_is_replaced() -> None:
    """§3.2.3 REOPENED: two entered targets do not erase a third product's draft."""
    stored = {OTHER_PRODUCT: 11, PRODUCT: 3}
    event = _event(**{ssm.ALLOCATION_DRAFT_ATTRIBUTE: stored})

    draft = am.draft_allocation_targets(event, [_target(6)])

    assert draft == {OTHER_PRODUCT: 11, PRODUCT: 6}
    assert stored == {OTHER_PRODUCT: 11, PRODUCT: 3}, "the stored row is not annotated on the way out"


def test_a_malformed_draft_is_refused_rather_than_guessed() -> None:
    with pytest.raises(AppError) as refused:
        am.draft_allocation_targets(_event(**{ssm.ALLOCATION_DRAFT_ATTRIBUTE: "nope"}), [_target(1)])
    assert refused.value.error_code == ErrorCode.INVALID_INPUT


def test_a_draft_names_a_product_only_when_it_asks_for_stock() -> None:
    """A zero draft for a product the event never held would make the event un-finalizable."""
    ids = am.draft_product_ids(_event(), [_target(6), _target(0, "CATALOG#fixture-default#prod-2")])

    assert ids == [PRODUCT]


# --- §3.2.2 — the interval rule --------------------------------------------------


def test_four_boxes_cannot_carry_three_to_each_of_two_overlapping_events() -> None:
    """ALLOC-02, AC-09: the refusal names the product, the stock, the total, and the overage."""
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=4,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=3,
        other_allocations=[_allocation(AFTERNOON_EVENT, allocated=3, start_at=OVERLAP_START, end_at=OVERLAP_END)],
    )

    assert conflict is not None
    assert (conflict.current_stock_qty, conflict.assigned_qty, conflict.overage_qty) == (4, 6, 2)
    assert conflict.at == OVERLAP_START
    message = am.conflict_message(conflict)
    for fact in (PRODUCT, "4", "6", "2"):
        assert fact in message


def test_the_same_three_and_three_is_allowed_when_the_events_do_not_overlap() -> None:
    """ALLOC-03: a morning and an afternoon against four boxes is legal, and reported."""
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=4,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=3,
        other_allocations=[_allocation(AFTERNOON_EVENT, allocated=3, start_at=AFTERNOON_START, end_at=AFTERNOON_END)],
    )

    assert conflict is None, "an endpoint that only touches is not a shared instant (§5.11)"


def test_three_events_are_measured_at_the_instant_the_third_one_starts() -> None:
    """The boundary case: the peak is attained at a ``startAt``, which is why the check is exact."""
    others = [
        _allocation("evt-a", allocated=3, start_at="2026-11-07T09:00:00+00:00", end_at="2026-11-07T13:00:00+00:00"),
        _allocation("evt-b", allocated=3, start_at="2026-11-07T10:00:00+00:00", end_at="2026-11-07T14:00:00+00:00"),
        _allocation("evt-c", allocated=3, start_at="2026-11-07T11:00:00+00:00", end_at="2026-11-07T12:00:00+00:00"),
    ]
    peak, peak_at = am.peak_concurrent_assignment(others)
    assert (peak, peak_at) == (9, "2026-11-07T11:00:00+00:00")

    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=7,
        start_at="2026-11-07T11:30:00+00:00",
        end_at="2026-11-07T11:45:00+00:00",
        remaining_qty=1,
        other_allocations=others,
    )

    assert conflict is not None
    assert conflict.assigned_qty == 10 and conflict.overage_qty == 3
    assert conflict.at == "2026-11-07T11:30:00+00:00", "the candidate's own start is where its Kernel is committed"


def test_a_tie_reports_the_earliest_instant() -> None:
    """Two instants carrying the same peak name the one the Kernel would fix first."""
    others = [
        _allocation("evt-a", allocated=2, start_at="2026-11-07T08:00:00+00:00", end_at="2026-11-07T09:00:00+00:00"),
        _allocation("evt-b", allocated=2, start_at="2026-11-07T08:30:00+00:00", end_at="2026-11-07T09:30:00+00:00"),
        _allocation("evt-c", allocated=2, start_at="2026-11-07T10:00:00+00:00", end_at="2026-11-07T11:00:00+00:00"),
        _allocation("evt-d", allocated=2, start_at="2026-11-07T10:30:00+00:00", end_at="2026-11-07T11:30:00+00:00"),
    ]

    assert am.peak_concurrent_assignment(others) == (4, "2026-11-07T08:30:00+00:00")


def test_zero_stock_refuses_any_positive_target() -> None:
    """A campaign holding nothing cannot be promised one Kernel at one instant."""
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=0,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=1,
        other_allocations=[],
    )

    assert conflict is not None and (conflict.assigned_qty, conflict.overage_qty) == (1, 1)


def test_a_zero_remainder_never_conflicts() -> None:
    """Releasing an assignment adds nothing to any instant, whatever the stock is."""
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=0,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=0,
        other_allocations=[_allocation(AFTERNOON_EVENT, allocated=9)],
    )

    assert conflict is None


def test_a_reduction_is_never_blocked_by_an_over_assignment_it_leaves() -> None:
    """The remedy has to stay reachable: a state already over stock is corrected, not frozen.

    The campaign holds 4 and two events are committed to 8 (stock left the campaign after
    the assignments were made). Reducing one to 5 is progress, so it is accepted; the
    warning surface reports what is still over.
    """
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=4,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=5,
        current_remaining_qty=8,
        other_allocations=[_allocation(AFTERNOON_EVENT, allocated=3)],
    )

    assert conflict is None


def test_an_increase_beyond_an_already_over_assigned_state_is_still_refused() -> None:
    """Being over stock is not permission to go further over it (ALLOC-02)."""
    conflict = am.concurrent_conflict(
        product_id=PRODUCT,
        sellable_qty=4,
        start_at=MORNING_START,
        end_at=MORNING_END,
        remaining_qty=6,
        current_remaining_qty=5,
        other_allocations=[_allocation(AFTERNOON_EVENT, allocated=3)],
    )

    assert conflict is not None and (conflict.assigned_qty, conflict.overage_qty) == (9, 5)


def test_only_open_allocations_compete() -> None:
    """A released or cancelled allocation's stock is back on the shelf (§9.2)."""
    rows = [
        _allocation("evt-a", allocated=3, status=inv.ALLOCATION_RELEASED, released=3),
        _allocation("evt-b", allocated=3, status=inv.ALLOCATION_CANCELLED, released=3),
    ]

    assert am.overlapping_assigned_qty(MORNING_START, rows) == 0
    assert am.peak_concurrent_assignment(rows) == (0, "")


def test_the_interval_comes_from_the_allocation_row() -> None:
    """§5.11 denormalizes the interval so the overlap rule has one source."""
    row = _allocation(AFTERNOON_EVENT, allocated=1, start_at=AFTERNOON_START, end_at=AFTERNOON_END)

    assert am.allocation_interval(row) == (AFTERNOON_START, AFTERNOON_END)


# --- §3.2.2 — the sequential warning (AC-10) -------------------------------------


def test_the_warning_names_the_product_the_stock_the_assigned_total_and_the_overage() -> None:
    """ALLOC-03: the save succeeds and the Kernel has to see by how much, without hover-only help."""
    warning = am.sequential_warning(
        product_id=PRODUCT,
        sellable_qty=4,
        allocations=[
            _allocation(MORNING_EVENT, allocated=3),
            _allocation(AFTERNOON_EVENT, allocated=3, start_at=AFTERNOON_START, end_at=AFTERNOON_END),
        ],
    )

    assert warning is not None
    assert warning == {
        "code": am.SEQUENTIAL_OVER_ASSIGNMENT,
        "productId": PRODUCT,
        "currentStockQty": 4,
        "assignedQty": 6,
        "overageQty": 2,
        "message": warning["message"],
    }
    for fact in (PRODUCT, "6", "4", "2"):
        assert fact in warning["message"], "the screen states the numbers, not only a sentence"


def test_no_warning_when_the_stock_covers_every_assignment() -> None:
    assert (
        am.sequential_warning(product_id=PRODUCT, sellable_qty=6, allocations=[_allocation(MORNING_EVENT, allocated=3)])
        is None
    )
    assert (
        am.sequential_warning(product_id=PRODUCT, sellable_qty=0, allocations=[_allocation(MORNING_EVENT, allocated=0)])
        is None
    )


def test_the_warning_ignores_what_is_no_longer_assigned() -> None:
    """``assignedOpenQty`` is OPEN rows only, so a cancelled event stops looking like a claim."""
    warning = am.sequential_warning(
        product_id=PRODUCT,
        sellable_qty=1,
        allocations=[
            _allocation(MORNING_EVENT, allocated=3),
            _allocation(AFTERNOON_EVENT, allocated=3, released=3, status=inv.ALLOCATION_CANCELLED),
        ],
    )

    assert warning is not None and (warning["assignedQty"], warning["overageQty"]) == (3, 2)


# --- §8.10 — finalization feasibility -------------------------------------------


def test_the_finalization_floor_grows_per_allocated_product() -> None:
    assert am.minimum_finalization_action_count(0) == am.FINALIZATION_OVERHEAD_ACTIONS
    assert am.minimum_finalization_action_count(16) == (
        am.FINALIZATION_OVERHEAD_ACTIONS + 16 * am.FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT
    )


def test_an_event_that_could_no_longer_finalize_is_refused_within_the_same_budget() -> None:
    """§8.10: the verdict and subcode match the plan-size guard, and the remedy is named."""
    fits = (90 - am.FINALIZATION_OVERHEAD_ACTIONS) // am.FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT
    am.require_finalization_feasible(fits, 90)

    with pytest.raises(AppError) as refused:
        am.require_finalization_feasible(fits + 1, 90)
    assert refused.value.error_code == ErrorCode.CONFLICT
    assert refused.value.details is not None
    assert refused.value.details["subcode"] == ErrorCode.OPERATION_TOO_LARGE
    assert refused.value.details["maxActions"] == 90
    assert "Reduce" in refused.value.message or "reduce" in refused.value.message


def test_a_movement_row_s_assigned_delta_is_readable_for_reconciliation() -> None:
    """The audit sums are proved against the staged row, not against the plan's arithmetic."""
    action = ssm.event_assignment_movement_action(
        event=_event(),
        product_id=PRODUCT,
        movement_type=inv.EVENT_MANUAL_REDUCE,
        assigned_delta=-6,
        actor_account_id="ACCOUNT#avery-fixture",
        occurred_at=MORNING_START,
        idempotency_key="assign-1",
    )

    assert am.assigned_delta_of(action[1]) == -6
    assert action[1]["Item"][inv.SHOW_AND_SELL_ID_ATTRIBUTE] == {"S": MORNING_EVENT}
