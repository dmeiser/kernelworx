"""
Allocation planning and overlap evaluation (Show & Sell wave 4, checklist
3.2.1/3.2.2; carries ADR 0003's per-campaign semantics record).

The server is authoritative on overlap math — the client never pre-computes
it. Two legal answers:

- Sequential over-assignment (non-overlapping events may exceed current
  stock): allowed, returns a SEQUENTIAL_OVER_ASSIGNMENT warning naming
  product, current stock, total assigned, and overage.
- Concurrent over-assignment (overlapping events exceeding sellable stock
  at ANY instant): hard-blocked; the whole batch is rejected with no
  partial write.

Planner semantics are TARGETS, never deltas: omitted products are not
written, target zero releases the remaining allocation, and a target below
the sold quantity is rejected (sold-stock protection).

Ported from the gate-proven clean-room build (design 16: the client never
pre-computes overlap; warnings/blocks carry the 16.3A/16.3B shapes).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SEQUENTIAL_OVER_ASSIGNMENT = "SEQUENTIAL_OVER_ASSIGNMENT"
CONCURRENT_OVER_ASSIGNMENT = "CONCURRENT_OVER_ASSIGNMENT"


@dataclass(slots=True)
class OpenAllocationView:
    """What the evaluator needs from one OPEN allocation row."""

    show_and_sell_id: str
    event_start_at: datetime
    event_end_at: datetime
    allocated_qty: int


@dataclass(slots=True)
class AllocationPlanLine:
    product_id: str
    current_allocated: int  # current allocation on the target event (0 if none)
    target: int
    sold: int
    released: int


def plan_targets(
    items: List[Dict[str, Any]],
    current_by_product: Dict[str, Dict[str, int]],
) -> List[AllocationPlanLine]:
    """3.2.1: map AllocationTargetInput[] to per-product target lines.

    ``current_by_product`` maps productId -> {allocated, sold, released} on
    the TARGET event. Duplicate products in one batch are rejected by the
    caller (INVALID_INPUT) before planning.
    """
    lines = []
    for item in items:
        product_id = item["productId"]
        target = item["quantity"]
        current = current_by_product.get(product_id, {"allocated": 0, "sold": 0, "released": 0})
        lines.append(
            AllocationPlanLine(
                product_id=product_id,
                current_allocated=current["allocated"],
                target=target,
                sold=current["sold"],
                released=current["released"],
            )
        )
    return lines


def validate_plan_line(line: AllocationPlanLine) -> Optional[str]:
    """Sold-stock protection: an event can never be assigned below what it
    already sold (5.11 invariant allocatedQty >= soldQty)."""
    if line.target < line.sold:
        return "sold-stock protection"
    return None


def max_concurrent_assigned(
    target_start: datetime,
    target_end: datetime,
    target_qty: int,
    open_allocations: List[OpenAllocationView],
    own_show_and_sell_id: str,
) -> Tuple[int, Optional[str]]:
    """The maximum, over every instant COVERED BY A COMPETITOR, of the sum
    of OPEN allocations covering that instant (other events) plus the new
    target. Instants with no competing allocation are sequential-only
    territory — over-assignment there warns, never hard-blocks.

    Whole-event allocations mean each competing event contributes its full
    allocatedQty to every instant it covers, so the peak is attained at some
    event boundary — evaluating at the target start and competitor start
    boundaries is exact.
    """
    competitors = [a for a in open_allocations if a.show_and_sell_id != own_show_and_sell_id]
    covering_competitors = [a for a in competitors if a.event_start_at < target_end and a.event_end_at > target_start]
    if not covering_competitors:
        return 0, None
    points = {target_start}
    for allocation in covering_competitors:
        if target_start < allocation.event_start_at < target_end:
            points.add(allocation.event_start_at)
    return _peak_at(points, competitors, target_qty)


def _peak_at(
    points: set[datetime], competitors: List[OpenAllocationView], target_qty: int
) -> Tuple[int, Optional[str]]:
    peak = 0
    peak_competitor: Optional[str] = None
    for point in points:
        covering = [a for a in competitors if a.event_start_at <= point < a.event_end_at]
        total = sum(a.allocated_qty for a in covering) + target_qty
        if total > peak:
            peak = total
            heavy = max(covering, key=lambda a: a.allocated_qty, default=None)
            peak_competitor = heavy.show_and_sell_id if heavy else None
    return peak, peak_competitor


def evaluate_assignment(
    lines: List[AllocationPlanLine],
    *,
    sellable_by_product: Dict[str, int],
    open_by_product: Dict[str, List[OpenAllocationView]],
    target_start: datetime,
    target_end: datetime,
    target_show_and_sell_id: str,
    event_location_name: str,
    product_names: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (warnings, hard_blocks). Warnings name product/current stock/
    assigned/overage (design 16.3A shape); blocks name the product, the
    competing event, and the numbers (design 16.3B shape)."""
    warnings: List[Dict[str, Any]] = []
    hard_blocks: List[Dict[str, Any]] = []
    for line in lines:
        sellable = sellable_by_product.get(line.product_id, 0)
        competitors = open_by_product.get(line.product_id, [])
        peak, competitor_id = max_concurrent_assigned(
            target_start, target_end, line.target, competitors, target_show_and_sell_id
        )
        if peak > sellable:
            hard_blocks.append(
                {
                    "code": CONCURRENT_OVER_ASSIGNMENT,
                    "productId": line.product_id,
                    "competingShowAndSellId": competitor_id,
                    "availableQty": sellable,
                    "concurrentAssignedQty": peak,
                    "locationName": event_location_name,
                }
            )
            continue
        other_total = sum(a.allocated_qty for a in competitors if a.show_and_sell_id != target_show_and_sell_id)
        total_assigned = other_total + line.target
        if total_assigned > sellable:
            product_name = (product_names or {}).get(line.product_id, line.product_id)
            warnings.append(
                {
                    "code": SEQUENTIAL_OVER_ASSIGNMENT,
                    "productId": line.product_id,
                    "currentStockQty": sellable,
                    "assignedQty": total_assigned,
                    "overageQty": total_assigned - sellable,
                    "message": (
                        f"Only {sellable} {product_name} are currently available. "
                        f"Assigned across upcoming events: {total_assigned}. "
                        f"Assignment overage: {total_assigned - sellable}."
                    ),
                }
            )
    return warnings, hard_blocks
