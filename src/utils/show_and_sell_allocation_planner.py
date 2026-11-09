"""Pure allocation-target planner for Show & Sell inventory (leaf 3.2.1)."""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class AllocationPlanAction:
    product_id: str
    current_qty: int
    target_qty: int
    delta: int
    released_qty: int
    protected_sold_qty: int


def plan_allocation_targets(
    current: Dict[str, int],
    targets: Dict[str, int],
    sold: Optional[Dict[str, int]] = None,
) -> List[AllocationPlanAction]:
    """Compute target-not-delta allocation actions.

    - Omitted products produce no action.
    - target 0 releases the remaining (non-sold) allocation.
    - Sold stock is protected: an allocation cannot drop below sold.
    """
    sold = sold or {}
    actions: List[AllocationPlanAction] = []
    for pid, target in targets.items():
        cur = current.get(pid, 0)
        sold_qty = sold.get(pid, 0)
        protected = min(cur, sold_qty)
        effective_target = max(target, protected)
        delta = effective_target - cur
        released = max(0, cur - effective_target)
        actions.append(
            AllocationPlanAction(
                product_id=pid,
                current_qty=cur,
                target_qty=effective_target,
                delta=delta,
                released_qty=released,
                protected_sold_qty=protected,
            )
        )
    return actions
