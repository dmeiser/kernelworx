"""Pure immutable-interval overlap/warning evaluator (leaf 3.2.2)."""

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Interval:
    start: int
    end: int
    product_id: str
    assigned_qty: int
    stock_qty: int


@dataclass(frozen=True)
class OverlapWarning:
    code: str
    product_id: str
    current_stock_qty: int
    assigned_qty: int
    overage_qty: int
    message: str


def evaluate_overlaps(intervals: List[Interval]) -> Tuple[bool, List[OverlapWarning]]:
    """Hard-block concurrent over-assignment at every instant; warn on sequential."""
    # Check instantaneous overlap per product
    by_product: dict = {}
    for iv in intervals:
        by_product.setdefault(iv.product_id, []).append(iv)

    warnings: List[OverlapWarning] = []
    hard_block = False

    for pid, ivs in by_product.items():
        # sort by start
        ivs_sorted = sorted(ivs, key=lambda x: x.start)
        # instantaneous overlap check
        for i in range(len(ivs_sorted)):
            for j in range(i + 1, len(ivs_sorted)):
                a, b = ivs_sorted[i], ivs_sorted[j]
                if a.start < b.end and b.start < a.end:
                    # concurrent: hard block if combined > stock
                    if a.assigned_qty + b.assigned_qty > a.stock_qty:
                        hard_block = True
        # sequential warnings: cumulative assigned > stock
        cumulative = 0
        for iv in ivs_sorted:
            cumulative += iv.assigned_qty
            if cumulative > iv.stock_qty and iv.stock_qty >= 0:
                overage = cumulative - iv.stock_qty
                warnings.append(
                    OverlapWarning(
                        code="SEQUENTIAL_OVER_ASSIGNMENT",
                        product_id=pid,
                        current_stock_qty=iv.stock_qty,
                        assigned_qty=cumulative,
                        overage_qty=overage,
                        message=f"Sequential over-assignment for {pid}: assigned {cumulative} > stock {iv.stock_qty}",
                    )
                )
    return hard_block, warnings
