from __future__ import annotations

from typing import Any, Iterable


def _status(a: Any) -> str:
    s = getattr(a, "status", None)
    if s is None and isinstance(a, dict):
        s = a.get("status")
    return str(s).split(".")[-1]


def _get(a: Any, key: str) -> Any:
    v = getattr(a, key, None)
    if v is None and isinstance(a, dict):
        v = a.get(key)
    return v


def sellable_kernel_qty(kernel_physical_qty: int, sold_in_possession_qty: int) -> int:
    return kernel_physical_qty - sold_in_possession_qty


def assigned_open_qty(allocations: Iterable[Any]) -> int:
    total = 0
    for a in allocations:
        if _status(a) == "OPEN":
            total += int(_get(a, "remaining_qty") or 0)
    return total


def unassigned_kernel_qty(sellable: int, assigned: int) -> int:
    return max(0, sellable - assigned)


def assignment_overage_qty(assigned: int, sellable: int) -> int:
    return max(0, assigned - sellable)


def with_scout_qty(custody_rows: Iterable[Any]) -> int:
    total = 0
    for r in custody_rows:
        v = _get(r, "with_scout_qty")
        total += int(v or 0)
    return total


def total_unit_owned_qty(kernel_physical_qty: int, with_scout: int) -> int:
    return kernel_physical_qty + with_scout
