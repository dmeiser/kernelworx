"""Tests for inventory models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.inventory import (
    AllocationStatus,
    EventInventoryAllocation,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementType,
    ScoutCustodyBalance,
)


class TestInventoryBalance:
    def test_valid_construction(self) -> None:
        b = InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=10, sold_in_possession_qty=3, council_on_order_qty=2)
        assert b.sellable_kernel_qty == 7

    def test_default_quantities(self) -> None:
        b = InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=5)
        assert b.sold_in_possession_qty == 0
        assert b.council_on_order_qty == 0
        assert b.sellable_kernel_qty == 5

    def test_negative_kernel_physical_qty(self) -> None:
        with pytest.raises(ValueError, match="kernel_physical_qty must be non-negative"):
            InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=-1)

    def test_negative_sold_in_possession_qty(self) -> None:
        with pytest.raises(ValueError, match="sold_in_possession_qty must be non-negative"):
            InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=5, sold_in_possession_qty=-1)

    def test_kernel_less_than_sold(self) -> None:
        with pytest.raises(ValueError, match="kernel_physical_qty must be >="):
            InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=2, sold_in_possession_qty=5)

    def test_negative_council_on_order_qty(self) -> None:
        with pytest.raises(ValueError, match="council_on_order_qty must be non-negative"):
            InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=5, council_on_order_qty=-1)

    def test_sellable_kernel_qty_zero(self) -> None:
        b = InventoryBalance(unit_campaign_id="uc", product_id="p", kernel_physical_qty=0)
        assert b.sellable_kernel_qty == 0


class TestScoutCustodyBalance:
    def test_valid(self) -> None:
        s = ScoutCustodyBalance(unit_campaign_id="uc", product_id="p", profile_id="pr", campaign_id="c", with_scout_qty=4)
        assert s.with_scout_qty == 4

    def test_negative_with_scout_qty(self) -> None:
        with pytest.raises(ValueError, match="with_scout_qty must be non-negative"):
            ScoutCustodyBalance(unit_campaign_id="uc", product_id="p", profile_id="pr", campaign_id="c", with_scout_qty=-1)


class TestEventInventoryAllocation:
    def test_valid_and_remaining(self) -> None:
        a = EventInventoryAllocation(
            unit_campaign_id="uc",
            product_id="p",
            show_and_sell_id="s",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            allocated_qty=5,
            sold_qty=2,
            released_qty=1,
        )
        assert a.remaining_qty == 2
        assert a.status == AllocationStatus.OPEN

    def test_negative_quantities(self) -> None:
        with pytest.raises(ValueError, match="quantities must be non-negative"):
            EventInventoryAllocation(
                unit_campaign_id="uc",
                product_id="p",
                show_and_sell_id="s",
                start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                allocated_qty=-1,
            )

    def test_allocated_less_than_sold(self) -> None:
        with pytest.raises(ValueError, match="allocated_qty must be >= sold_qty"):
            EventInventoryAllocation(
                unit_campaign_id="uc",
                product_id="p",
                show_and_sell_id="s",
                start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                allocated_qty=2,
                sold_qty=3,
            )

    def test_allocated_less_than_sold_plus_released(self) -> None:
        with pytest.raises(ValueError, match="allocated_qty must be >= sold_qty \\+ released_qty"):
            EventInventoryAllocation(
                unit_campaign_id="uc",
                product_id="p",
                show_and_sell_id="s",
                start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                allocated_qty=3,
                sold_qty=2,
                released_qty=2,
            )

    def test_released_status(self) -> None:
        a = EventInventoryAllocation(
            unit_campaign_id="uc",
            product_id="p",
            show_and_sell_id="s",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            status=AllocationStatus.RELEASED,
            allocated_qty=0,
        )
        assert a.status == AllocationStatus.RELEASED
        assert a.remaining_qty == 0

    def test_cancelled_status(self) -> None:
        a = EventInventoryAllocation(
            unit_campaign_id="uc",
            product_id="p",
            show_and_sell_id="s",
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            status=AllocationStatus.CANCELLED,
        )
        assert a.status == AllocationStatus.CANCELLED


class TestInventoryMovement:
    def test_construction(self) -> None:
        m = InventoryMovement(
            movement_id="m1",
            unit_campaign_id="uc",
            product_id="p",
            movement_type=InventoryMovementType.RECEIPT,
            actor_account_id="a",
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert m.movement_type == InventoryMovementType.RECEIPT
