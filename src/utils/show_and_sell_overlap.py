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


def _instantaneous_hard_block(ivs_sorted: List[Interval], common_stock: int) -> bool:
    events = []
    for iv in ivs_sorted:
        events.append((iv.start, 1, iv.assigned_qty))
        events.append((iv.end, 0, -iv.assigned_qty))
    events.sort(key=lambda e: (e[0], e[1]))
    running = 0
    for _time, kind, delta in events:
        running += delta
        if kind == 1 and running > common_stock:
            return True
    return False


def _sequential_warnings(pid: str, ivs_sorted: List[Interval]) -> List[OverlapWarning]:
    warnings: List[OverlapWarning] = []
    cumulative = 0
    last_end = None
    for iv in ivs_sorted:
        if last_end is None or iv.start >= last_end:
            cumulative += iv.assigned_qty
            last_end = iv.end
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
        else:
            last_end = max(last_end, iv.end)
    return warnings


def evaluate_overlaps(intervals: List[Interval]) -> Tuple[bool, List[OverlapWarning]]:
    """Hard-block concurrent over-assignment at every instant; warn on sequential."""
    by_product: dict[str, list[Interval]] = {}
    for iv in intervals:
        by_product.setdefault(iv.product_id, []).append(iv)

    warnings: List[OverlapWarning] = []
    hard_block = False

    for pid, ivs in by_product.items():
        ivs_sorted = sorted(ivs, key=lambda x: x.start)
        common_stock = ivs_sorted[0].stock_qty if ivs_sorted else 0
        if _instantaneous_hard_block(ivs_sorted, common_stock):
            hard_block = True
        warnings.extend(_sequential_warnings(pid, ivs_sorted))

    return hard_block, warnings