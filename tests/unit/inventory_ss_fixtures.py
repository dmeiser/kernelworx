"""Deterministic inventory/custody/Order fixtures for Show & Sell Stage 2."""

from __future__ import annotations

from datetime import datetime, timezone

from src.models.inventory import (
    AllocationStatus,
    EventInventoryAllocation,
    InventoryBalance,
    InventoryMovement,
    ScoutCustodyBalance,
)


def make_balance(
    unit_campaign_id="uc-1",
    product_id="caramel",
    kernel_physical_qty=4,
    sold_in_possession_qty=0,
    council_on_order_qty=10,
    version=1,
):
    return InventoryBalance(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        kernel_physical_qty=kernel_physical_qty,
        sold_in_possession_qty=sold_in_possession_qty,
        council_on_order_qty=council_on_order_qty,
        version=version,
    )


def caramel_butter_balances():
    return [
        make_balance(product_id="caramel", kernel_physical_qty=4, council_on_order_qty=0),
        make_balance(product_id="butter", kernel_physical_qty=0, council_on_order_qty=10),
    ]


def make_allocation(
    unit_campaign_id="uc-1",
    product_id="caramel",
    show_and_sell_id="ss-1",
    allocated_qty=4,
    sold_qty=0,
    released_qty=0,
    status=AllocationStatus.OPEN,
):
    return EventInventoryAllocation(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        show_and_sell_id=show_and_sell_id,
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        status=status,
        allocated_qty=allocated_qty,
        sold_qty=sold_qty,
        released_qty=released_qty,
    )


def make_custody(
    unit_campaign_id="uc-1", product_id="caramel", profile_id="p-1", campaign_id="c-1", with_scout_qty=2, version=1
):
    return ScoutCustodyBalance(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        profile_id=profile_id,
        campaign_id=campaign_id,
        with_scout_qty=with_scout_qty,
        version=version,
    )


def make_movement(movement_id="m-1", **kw):
    defaults = dict(
        movement_id=movement_id,
        unit_campaign_id="uc-1",
        product_id="caramel",
        movement_type=__import__(
            "src.models.inventory", fromlist=["InventoryMovementType"]
        ).InventoryMovementType.RECEIPT,
        actor_account_id="acct-1",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(kw)
    return InventoryMovement(**defaults)
