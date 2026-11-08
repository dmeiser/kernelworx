"""Unit tests for inventory derived helpers (Stage 2 wave 1)."""

from src.utils.inventory_derived import (
    assigned_open_qty,
    assignment_overage_qty,
    sellable_kernel_qty,
    total_unit_owned_qty,
    unassigned_kernel_qty,
    with_scout_qty,
)


class _Alloc:
    def __init__(self, status, remaining_qty):
        self.status = status
        self.remaining_qty = remaining_qty


def test_sellable_kernel_qty():
    assert sellable_kernel_qty(10, 3) == 7


def test_assigned_open_qty_objects():
    allocs = [
        _Alloc("OPEN", 4),
        _Alloc("RELEASED", 2),
        _Alloc("OPEN", None),
    ]
    assert assigned_open_qty(allocs) == 4


def test_assigned_open_qty_dict_status_enum():
    allocs = [
        {"status": "OPEN", "remaining_qty": 5},
        {"status": "CANCELLED", "remaining_qty": 1},
    ]
    assert assigned_open_qty(allocs) == 5


def test_assigned_open_qty_empty():
    assert assigned_open_qty([]) == 0


def test_unassigned_kernel_qty_clamps():
    assert unassigned_kernel_qty(5, 3) == 2
    assert unassigned_kernel_qty(3, 5) == 0


def test_assignment_overage_qty():
    assert assignment_overage_qty(5, 3) == 2
    assert assignment_overage_qty(3, 5) == 0


def test_with_scout_qty_objects_and_dicts():
    class R:
        def __init__(self, v):
            self.with_scout_qty = v

    rows = [{"with_scout_qty": 2}, R(3), {"with_scout_qty": None}]
    assert with_scout_qty(rows) == 5


def test_total_unit_owned_qty():
    assert total_unit_owned_qty(10, 4) == 14


def test_status_fallback_object_without_status():
    # object lacking status attribute defaults to None -> "None"
    class A:
        remaining_qty = 7

    assert assigned_open_qty([A()]) == 0


def test_get_fallback_object_without_key():
    class A:
        status = "OPEN"

    # remaining_qty missing -> 0
    assert assigned_open_qty([A()]) == 0


def test_status_dict_missing_key_branch():
    # dict without status triggers the dict branch in _status
    allocs = [{"remaining_qty": 9}]
    assert assigned_open_qty(allocs) == 0


def test_get_dict_missing_key_branch():
    class A:
        pass

    # object missing remaining_qty AND not dict -> _get returns None
    a = A()
    a.status = "OPEN"
    assert assigned_open_qty([a]) == 0
