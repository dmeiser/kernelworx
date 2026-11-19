"""The allocation-target planner and the interval overlap evaluator (checklist §3.2.1, §3.2.2).

Two pure leaves, and both are pure on purpose. ``assignShowAndSellInventory`` (§3.2.3)
has to decide, before it stages a single write, what each product's allocation row
should say and whether that state is legal at every instant of the event's interval.
Both answers come from rows already read, so they can be tested — and audited — without
a table: nothing in this module opens a client, and every function is a total mapping
from what is stored to what may be written.

What each rule is protecting:

* **Target, not delta** (§3.2.1). A Kernel's editor states "this event holds 6 of this
  product", so an update re-states the target. A delta would make two Kernels' screens
  additive: both reading 3 and both typing 5 would produce 8. The caller sends the
  quantity it wants to see, and the plan reports the delta only so the movement can
  explain it (§5.8's ``assignedDelta`` is a delta, the row is a target).
* **An omitted product is not a zero** (§3.2.1, EVT-M-04-02). A product with no entry
  in this batch is left exactly as it stands. Only an explicit ``quantity: 0`` releases
  a target, and only its own remainder.
* **Sold stock is protected** (§3.2.1). A target below ``soldQty + releasedQty`` would
  contradict quantities that are history: what was sold at the event and what was
  already released. The refusal is ``INVALID_INPUT``, not a clamp — silently raising
  the target to the floor would assign stock the Kernel did not ask for.
* **No event-wide product cap** (§5.10). Sixteen products is a legal event; the ceiling
  is the computed write plan (§8.10), never a count of products.
* **Concurrent over-assignment is blocked at every instant** (ALLOC-02, AC-09). Four
  boxes cannot carry three to each of two overlapping events. The comparison is made on
  the allocation rows' own denormalized intervals (§5.11), because the row is the record
  the rule was decided on.
* **Sequential over-assignment warns** (ALLOC-03, AC-10). Three boxes to a morning event
  and three to a non-overlapping afternoon event is allowed with four on hand, and the
  warning has to name the product, the actual current stock, the assigned total and the
  overage so the screen can state them without hover-only help.

The interval arithmetic has one simplification worth stating, because it is what makes
the check exact rather than sampled: the sum of overlapping allocations is piecewise
constant and only ever increases at an interval's ``startAt``, so its maximum over the
whole timeline is attained at one of the ``startAt`` instants. Every instant is covered
by checking those, and touching endpoints do not overlap (§5.11 half-open intervals via
:func:`src.utils.show_and_sell_models.intervals_overlap`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from .errors import AppError, ErrorCode
from .inventory_models import (
    ALLOCATED_QTY,
    ALLOCATION_OPEN,
    ASSIGNED_DELTA,
    EVENT_ASSIGN,
    EVENT_MANUAL_REDUCE,
    RELEASED_QTY,
    REMAINING_QTY,
    SOLD_QTY,
    assigned_open_qty,
    normalize_inventory_id,
    normalize_quantity,
)
from .show_and_sell_models import (
    ALLOCATION_DRAFT_ATTRIBUTE,
    END_AT_ATTRIBUTE,
    START_AT_ATTRIBUTE,
    STATUS_ATTRIBUTE,
    intervals_overlap,
    merge_product_ids,
)

# --- Warning and conflict vocabulary (API contract §3.2 ``AllocationWarning``) -----

#: Assigned open allocations exceed sellable stock, but never at one shared instant
#: (ALLOC-03). The save succeeds; the Kernel has to see by how much.
SEQUENTIAL_OVER_ASSIGNMENT = "SEQUENTIAL_OVER_ASSIGNMENT"

#: Assigned open allocations exceed sellable stock at a shared instant (ALLOC-02). The
#: save is refused and nothing is written.
CONCURRENT_OVER_ASSIGNMENT = "CONCURRENT_OVER_ASSIGNMENT"

#: §8.10 requires every mutation that adds products to preflight the minimum write set
#: of the finalization it is making possible. Allocation-side only, stated per allocated
#: product: the release of the allocation, its return/reconcile movement, and its return
#: line. The event-side rows are counted once, and the participant-side rows are counted
#: by the mutations that write them (§3.4) and by finalization's own plan (§5.2).
FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT = 3
FINALIZATION_OVERHEAD_ACTIONS = 4

#: The movement type a target change of this sign is audited as (§5.8): an increase is an
#: assignment, a decrease is a manual reduction. A zero delta writes nothing, so it has
#: no type.
MOVEMENT_TYPE_BY_SIGN: dict[bool, str] = {True: EVENT_ASSIGN, False: EVENT_MANUAL_REDUCE}


def _invalid(field: str, rule: str) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


# --- Input shape ------------------------------------------------------------------


@dataclass(frozen=True)
class AllocationTarget:
    """One product's requested target quantity (``AllocationTargetInput``)."""

    product_id: str
    quantity: int


def normalize_allocation_targets(value: Any) -> List[AllocationTarget]:
    """Validate an ``items`` batch of target quantities (§3.1 ``AllocationTargetInput``).

    Three rules, each with a failure it prevents:

    - non-empty — an empty batch is a save that would write a marker, move the event
      version, and change no allocation, then tell the Kernel its assignment was saved;
    - quantity 0..1,000,000 — zero is meaningful here (it is how a target is released),
      so the floor is 0 rather than 1 like a receipt or a return;
    - no repeated product — one allocation row per (campaign, product, event), so two
      entries for one product are two writes to one row, which DynamoDB refuses inside a
      transaction anyway. Answering ``INVALID_INPUT`` names the real mistake.

    The batch is not capped by a product count (§5.10: no event-wide cap). Its ceiling is
    the computed write plan, which is where the 90-action budget is counted.
    """
    if not isinstance(value, (list, tuple)) or not value:
        raise _invalid("items", "must contain at least one product target")
    targets: List[AllocationTarget] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise _invalid("items", "each item needs a productId and a quantity")
        product_id = normalize_inventory_id(entry.get("productId"), "productId")
        quantity = normalize_quantity(entry.get("quantity"), "quantity", minimum=0)
        targets.append(AllocationTarget(product_id=product_id, quantity=quantity))
    if len({target.product_id for target in targets}) != len(targets):
        raise _invalid("items", "must not repeat a product")
    return targets


# --- The plan ---------------------------------------------------------------------


@dataclass(frozen=True)
class AllocationChange:
    """One product's allocation row as this request would write it.

    The quantities are absolute — what the row should say — except ``assigned_delta``,
    which is what this request moves and is the only quantity a movement may carry
    (§5.8: ``assignedDelta`` explains one change; the row stays authoritative).
    ``creates_row`` says whether the row exists yet, which is what decides between a
    conditional ``Put`` and a versioned ``Update``, and whether the product joins the
    event's cumulative ``productIds``.
    """

    product_id: str
    show_and_sell_id: str
    unit_campaign_id: str
    start_at: str
    end_at: str
    status: str
    allocated_qty: int
    sold_qty: int
    released_qty: int
    remaining_qty: int
    assigned_delta: int
    movement_type: str
    creates_row: bool
    expected_version: Optional[int]


def allocation_floor(row: Mapping[str, Any]) -> int:
    """The lowest target a row may be moved to: what it has already sold and released.

    ``allocatedQty >= soldQty`` and ``remainingQty = allocatedQty - soldQty -
    releasedQty >= 0`` (§5.11) together mean a target below ``soldQty + releasedQty``
    cannot be stated at all. Sold and released quantities are history — an immediate
    sale at the event, and a remainder already put back on the shelf — so a request
    under the floor is refused rather than clamped up.
    """
    return int(row.get(SOLD_QTY) or 0) + int(row.get(RELEASED_QTY) or 0)


def _require_open_row(row: Mapping[str, Any], product_id: str) -> None:
    """Refuse to re-state the target of an allocation that is no longer open.

    ``RELEASED`` and ``CANCELLED`` are terminal (§9.2): the stock they report went back
    on the shelf through a cancellation or a finalization, and re-opening the same row
    would count that stock twice. A reopened event's new targets are written by
    re-finalization (§5.3.3), which owns that arithmetic.
    """
    status = str(row.get(STATUS_ATTRIBUTE) or "")
    if status != ALLOCATION_OPEN:
        raise AppError(
            ErrorCode.CONFLICT,
            f"{product_id} is no longer assigned to this event ({status}); a released or cancelled allocation is not re-opened",
            details={"subcode": "ALLOCATION_CLOSED", "productId": product_id, "status": status},
        )


def plan_allocation_target(
    event: Mapping[str, Any],
    target: AllocationTarget,
    existing: Optional[Mapping[str, Any]],
) -> Optional[AllocationChange]:
    """One product's planned row, or ``None`` when this request changes nothing.

    Four cases, in the order the Kernel's editor produces them:

    - no row yet and a positive target — create the row at that target (``EVENT_ASSIGN``);
    - no row and a zero target — nothing to release, so nothing is written. An explicit
      zero for a product the event never held is not a state change;
    - a row and the same target — no write. Restating a target the row already carries
      would spend a transaction action, a movement, and a version bump on nothing;
    - a row and a different target — re-state it (``EVENT_ASSIGN`` upward,
      ``EVENT_MANUAL_REDUCE`` downward), keeping the row's sold and released quantities
      and re-deriving ``remainingQty`` from the target.
    """
    event_id = str(event["showAndSellId"])
    start_at = str(event[START_AT_ATTRIBUTE])
    end_at = str(event[END_AT_ATTRIBUTE])
    if existing is None:
        if target.quantity == 0:
            return None
        return AllocationChange(
            product_id=target.product_id,
            show_and_sell_id=event_id,
            unit_campaign_id=str(event["unitCampaignId"]),
            start_at=start_at,
            end_at=end_at,
            status=ALLOCATION_OPEN,
            allocated_qty=target.quantity,
            sold_qty=0,
            released_qty=0,
            remaining_qty=target.quantity,
            assigned_delta=target.quantity,
            movement_type=EVENT_ASSIGN,
            creates_row=True,
            expected_version=None,
        )

    _require_open_row(existing, target.product_id)
    sold = int(existing.get(SOLD_QTY) or 0)
    released = int(existing.get(RELEASED_QTY) or 0)
    current = int(existing.get(ALLOCATED_QTY) or 0)
    if target.quantity < allocation_floor(existing):
        floor = allocation_floor(existing)
        raise _invalid(
            "quantity",
            (
                f"cannot take {target.product_id} below the {floor} Kernels this event has already "
                f"sold and released (soldQty + releasedQty)"
            ),
        )
    if target.quantity == current:
        return None
    delta = target.quantity - current
    return AllocationChange(
        product_id=target.product_id,
        show_and_sell_id=event_id,
        unit_campaign_id=str(event["unitCampaignId"]),
        start_at=start_at,
        end_at=end_at,
        status=str(existing.get(STATUS_ATTRIBUTE) or ALLOCATION_OPEN),
        allocated_qty=target.quantity,
        sold_qty=sold,
        released_qty=released,
        remaining_qty=target.quantity - sold - released,
        assigned_delta=delta,
        movement_type=MOVEMENT_TYPE_BY_SIGN[delta > 0],
        creates_row=False,
        expected_version=int(existing.get("version") or 1),
    )


def plan_allocation_targets(
    event: Mapping[str, Any],
    targets: Iterable[AllocationTarget],
    existing_by_product: Mapping[str, Optional[Mapping[str, Any]]],
) -> List[AllocationChange]:
    """Plan every product in this batch, in the order the caller sent them.

    ``existing_by_product`` carries this event's allocation row for each product the
    caller addressed (``None`` when there is none). A product absent from ``targets`` is
    never planned, which is what makes the omitted-product rule structural rather than a
    special case: the plan is keyed by the batch, not by the union of the batch and what
    is stored.
    """
    changes: List[AllocationChange] = []
    for target in targets:
        change = plan_allocation_target(event, target, existing_by_product.get(target.product_id))
        if change is not None:
            changes.append(change)
    return changes


def planned_product_ids(event: Mapping[str, Any], changes: Iterable[AllocationChange]) -> List[str]:
    """The event's ``productIds`` after this write: cumulative, ordered, uncapped (§5.10).

    Only a product whose row this commit creates joins the list — every other entry was
    already there, because the list is written in the same transaction as the allocation
    it points at (§8.4). Dropping an entry whose allocation was later released would
    strand the inventory rows finalization has to find, so nothing here removes one.
    """
    additions = [change.product_id for change in changes if change.creates_row]
    return merge_product_ids(event.get("productIds"), additions)


# --- The reopened draft (§3.2.3: "only draft inputs while REOPENED") ---------------


def draft_allocation_targets(event: Mapping[str, Any], targets: Iterable[AllocationTarget]) -> dict[str, int]:
    """The event's draft target map after this batch, product by product.

    A reopened event's approved stock answer is the finalization that was suspended, so a
    target entered now is an input, not a state: it is stored on the event aggregate and
    validated again by re-finalization (§8.6, §5.3.2). The map is merged rather than
    replaced — a batch that addresses two products does not erase the draft target a
    previous batch entered for a third — and a product's own entry is replaced whole,
    because a target is a target.
    """
    stored = event.get(ALLOCATION_DRAFT_ATTRIBUTE)
    draft: dict[str, int] = {}
    if stored is not None:
        if not isinstance(stored, Mapping):
            raise _invalid(ALLOCATION_DRAFT_ATTRIBUTE, "must be a map of product id to quantity")
        draft = {str(name): int(value) for name, value in stored.items()}
    for target in targets:
        draft[target.product_id] = target.quantity
    return draft


def draft_product_ids(event: Mapping[str, Any], targets: Iterable[AllocationTarget]) -> List[str]:
    """The event's cumulative ``productIds`` once this batch's drafts are recorded.

    Only a product the Kernel is asking to stock joins the list. A zero target for a
    product the event never held references nothing, and finalization's product walk
    requires every listed product to have an allocation — so a phantom entry would make
    the event un-finalizable by a typo (§8.10).
    """
    return merge_product_ids(event.get("productIds"), [target.product_id for target in targets if target.quantity > 0])


# --- The interval rule (ALLOC-02, ALLOC-03) ---------------------------------------


@dataclass(frozen=True)
class ConcurrentConflict:
    """Why one product's targets cannot all be held at once, and the instant they fail at."""

    product_id: str
    current_stock_qty: int
    assigned_qty: int
    overage_qty: int
    at: str


def allocation_interval(row: Mapping[str, Any]) -> Tuple[str, str]:
    """The interval an allocation competes on: the row's own, never the event's now.

    §5.11 denormalizes ``startAt``/``endAt`` onto the allocation for exactly this
    question, and reading it off the row is what keeps the check honest when the row is
    read on a page that never loaded the event.
    """
    return str(row[START_AT_ATTRIBUTE]), str(row[END_AT_ATTRIBUTE])


def overlapping_assigned_qty(at: str, allocations: Iterable[Mapping[str, Any]]) -> int:
    """Open allocations of ``at``: the stock committed at one instant (§7 ``assignedOpenQty`` scoped in time).

    Only ``OPEN`` rows count: a released or cancelled allocation's stock is back on the
    shelf, and counting it again is how an event that has been cancelled would keep
    appearing to hold Kernels.
    """
    total = 0
    for row in allocations:
        if str(row.get(STATUS_ATTRIBUTE) or "") != ALLOCATION_OPEN:
            continue
        start_at, end_at = allocation_interval(row)
        if intervals_overlap(start_at, end_at, at, at) or start_at <= at < end_at:
            total += int(row.get(REMAINING_QTY) or 0)
    return total


def peak_concurrent_assignment(allocations: Iterable[Mapping[str, Any]]) -> Tuple[int, str]:
    """The largest number of Kernels any one instant carries, and that instant.

    The concurrent total changes only at interval boundaries and only ever increases at a
    ``startAt``, so the maximum over the whole timeline is one of the ``startAt``
    instants — checking each of those checks every instant between them too. Ties return
    the earliest instant, which is the one a Kernel can act on.
    """
    rows = list(allocations)
    peak, peak_at = 0, ""
    for row in rows:
        at = allocation_interval(row)[0]
        total = overlapping_assigned_qty(at, rows)
        if total > peak or (peak_at and total == peak and at < peak_at):
            peak, peak_at = total, at
    return peak, peak_at


def conflict_message(conflict: ConcurrentConflict) -> str:
    """The concurrent refusal in the words the screen shows, naming the four numbers."""
    return (
        f"{conflict.product_id} cannot be assigned this way: {conflict.assigned_qty} Kernels are "
        f"committed to overlapping events at {conflict.at}, against {conflict.current_stock_qty} "
        f"sellable, an overage of {conflict.overage_qty}"
    )


def _candidate_row(start_at: str, end_at: str, remaining_qty: int) -> List[Mapping[str, Any]]:
    """The candidate as an allocation row, or nothing when it assigns nothing."""
    if remaining_qty <= 0:
        return []
    return [
        {
            "candidate": True,
            STATUS_ATTRIBUTE: ALLOCATION_OPEN,
            START_AT_ATTRIBUTE: start_at,
            END_AT_ATTRIBUTE: end_at,
            REMAINING_QTY: remaining_qty,
        }
    ]


def concurrent_conflict(
    *,
    product_id: str,
    sellable_qty: int,
    start_at: str,
    end_at: str,
    remaining_qty: int,
    other_allocations: Iterable[Mapping[str, Any]],
    current_remaining_qty: int = 0,
) -> Optional[ConcurrentConflict]:
    """Whether this write creates or worsens an over-assignment at a shared instant (ALLOC-02).

    The candidate is compared against the campaign's other open allocations for that
    product — every event of that Unit Campaign, read from the same product prefix as the
    balance — because "at every point in time" is a question about the whole campaign's
    commitments and not about the one event being edited.

    The ceiling is ``max(sellable, the peak as it is already stored)``. Two things follow,
    and both are the rule rather than a loophole:

    - a campaign that is inside its stock cannot be taken outside it — an increase past
      what the campaign holds is refused at the instant it fails;
    - a campaign that is already outside it (stock left the campaign after the assignments
      were made) can still be corrected. Refusing a reduction because the state it leaves
      is still over-assigned would strand the only remedy §8.10 names, so an improvement
      is never blocked even when the ceiling it stays under is the stored peak.

    A zero remainder therefore never conflicts: it adds nothing to any instant, and the
    peak it leaves is below the one it replaced.
    """
    rows = [
        row
        for row in other_allocations
        if str(row.get(STATUS_ATTRIBUTE) or "") == ALLOCATION_OPEN and int(row.get(REMAINING_QTY) or 0) > 0
    ]
    stored_peak, _ = peak_concurrent_assignment(rows + _candidate_row(start_at, end_at, current_remaining_qty))
    ceiling = max(sellable_qty, stored_peak)
    peak, peak_at = peak_concurrent_assignment(rows + _candidate_row(start_at, end_at, remaining_qty))
    if peak <= ceiling:
        return None
    return ConcurrentConflict(
        product_id=product_id,
        current_stock_qty=sellable_qty,
        assigned_qty=peak,
        overage_qty=peak - sellable_qty,
        at=peak_at,
    )


def sequential_warning(
    *,
    product_id: str,
    sellable_qty: int,
    allocations: Iterable[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """The ALLOC-03 warning for one product, or ``None`` when stock still covers it.

    ``assignedOpenQty`` and ``assignmentOverageQty`` are the §7 quantities, computed from
    the rows as this write leaves them. They are reported rather than clamped:
    the Kernel is allowed to hold a morning and an afternoon event against four boxes, and
    the warning has to carry the actual current stock, the assigned total, and the overage
    so the tooltip can state them and name the product (AC-10 asks for a
    keyboard/touch-accessible warning, which needs the numbers, not a sentence).
    """
    assigned = assigned_open_qty(allocations)
    if assigned <= sellable_qty:
        return None
    overage = assigned - sellable_qty
    return {
        "code": SEQUENTIAL_OVER_ASSIGNMENT,
        "productId": product_id,
        "currentStockQty": sellable_qty,
        "assignedQty": assigned,
        "overageQty": overage,
        "message": (
            f"{product_id}: {assigned} Kernels are assigned to Show & Sells of this campaign, but only "
            f"{sellable_qty} are sellable right now — {overage} more are assigned than the campaign holds."
        ),
    }


# --- Finalization feasibility (§8.10) ---------------------------------------------


def minimum_finalization_action_count(allocated_product_count: int) -> int:
    """The smallest write set the finalization of this event will need (§8.10).

    One release, one return/reconcile movement, and one return line per allocated
    product, plus the marker, the event row, the finalization row, and its cash
    reconciliation. Participant and credit rows are counted by the mutations that create
    them, so this is the floor the allocation side commits the event to — which is exactly
    what a mutation that adds products has to preflight: an event must stay legally
    finalizable, and the remedy (reduce allocations) is in the same screen.
    """
    return FINALIZATION_OVERHEAD_ACTIONS + FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT * allocated_product_count


def require_finalization_feasible(allocated_product_count: int, max_actions: int) -> None:
    """Refuse a write that would leave an event no longer finalizable inside the budget.

    Same verdict and subcode as the plan-size guard, and the same remedy named in the
    message, because a Kernel who is refused for this reason has to know which lever to
    pull: remove allocations for enough products that finalization fits again.
    """
    planned = minimum_finalization_action_count(allocated_product_count)
    if planned <= max_actions:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        (
            f"{allocated_product_count} allocated products would need {planned} actions to finalize, "
            f"over the {max_actions} a single transaction allows. Reduce this event's allocations."
        ),
        details={
            "subcode": ErrorCode.OPERATION_TOO_LARGE,
            "plannedActions": planned,
            "maxActions": max_actions,
            "reduction": "remove allocated products from this event until finalization fits",
        },
    )


def assigned_delta_of(action: Mapping[str, Any]) -> int:
    """The ``assignedDelta`` of a staged movement action or of a stored movement row.

    Both shapes are in hand while reconciling an audit trail: the write plan holds the
    wire form (``{"N": "-6"}``) and the table hands back a ``Decimal``. Reading the number
    out of whichever row is in front of the reader is what lets a test prove the movements
    sum to the allocation instead of re-doing the arithmetic the plan already did.
    """
    row: Mapping[str, Any] = action
    staged = action.get("Item")
    if isinstance(staged, Mapping):
        row = staged
    value = row.get(ASSIGNED_DELTA)
    if isinstance(value, Mapping):
        value = value.get("N")
    return int(value or 0)
