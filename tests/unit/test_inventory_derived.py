"""Tests for derived inventory helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from src.models.inventory import AllocationStatus, EventInventoryAllocation
from src.utils.inventory_derived import (
    assigned_open_qty,
    assignment_overage_qty,
    sellable_kernel_qty,
    total_unit_owned_qty,
    unassigned_kernel_qty,
    with_scout_qty,
)


class _Obj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_sellable_kernel_qty() -> None:
    assert sellable_kernel_qty(10, 3) == 7
    assert sellable_kernel_qty(0, 0) == 0


def test_assigned_open_qty_objects() -> None:
    allocs = [
        EventInventoryAllocation(
            unit_campaign_id="uc",
            product_id="p",
            show_and_sell_id="s",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            status=AllocationStatus.OPEN,
            allocated_qty=5,
            sold_qty=1,
            released_qty=1,
        ),
        EventInventoryAllocation(
            unit_campaign_id="uc",
            product_id="p",
            show_and_sell_id="s2",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            status=AllocationStatus.RELEASED,
            allocated_qty=3,
            sold_qty=0,
            released_qty=3,
        ),
    ]
    assert assigned_open_qty(allocs) == 3


def test_assigned_open_qty_dicts_and_none() -> None:
    allocs = [
        {"status": "OPEN", "remaining_qty": 4},
        {"status": "OPEN"},  # missing remaining -> 0
        {"status": "CANCELLED", "remaining_qty": 2},
        _Obj(status=None),  # not dict, status None -> "None"
    ]
    assert assigned_open_qty(allocs) == 4


def test_assigned_open_qty_object_status_none_dict() -> None:
    # object with status attr None but is a dict subclass? cover _status branches
    class D(dict):
        pass

    d = D(status=None)
    # _get remaining_qty None -> 0
    assert assigned_open_qty([d]) == 0


def test_unassigned_kernel_qty() -> None:
    assert unassigned_kernel_qty(10, 3) == 7
    assert unassigned_kernel_qty(3, 10) == 0


def test_assignment_overage_qty() -> None:
    assert assignment_overage_qty(10, 3) == 7
    assert assignment_overage_qty(3, 10) == 0


def test_with_scout_qty() -> None:
    rows = [{"with_scout_qty": 2}, _Obj(with_scout_qty=3), {"with_scout_qty": None}]
    assert with_scout_qty(rows) == 5


def test_total_unit_owned_qty() -> None:
    assert total_unit_owned_qty(4, 10) == 14
    assert total_unit_owned_qty(0, 0) == 0


def test_status_object_without_status_non_dict() -> None:
    # _status: s is None and not dict -> "None"; not OPEN so excluded
    assert assigned_open_qty([_Obj()]) == 0


