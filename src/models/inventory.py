from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class InventoryMovementType(str, Enum):
    RECEIPT = "RECEIPT"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    COUNCIL_ON_ORDER_ADJUST = "COUNCIL_ON_ORDER_ADJUST"
    EVENT_ASSIGN = "EVENT_ASSIGN"
    EVENT_MANUAL_REDUCE = "EVENT_MANUAL_REDUCE"
    EVENT_AUTO_REDUCE = "EVENT_AUTO_REDUCE"
    EVENT_IMMEDIATE_SALE = "EVENT_IMMEDIATE_SALE"
    EVENT_RELEASE = "EVENT_RELEASE"
    EVENT_RETURN_RECONCILE = "EVENT_RETURN_RECONCILE"
    EVENT_RE_FINALIZE_ADJUST = "EVENT_RE_FINALIZE_ADJUST"
    SCOUT_ISSUE = "SCOUT_ISSUE"
    SCOUT_SALE_CONSUME = "SCOUT_SALE_CONSUME"
    SCOUT_RETURN = "SCOUT_RETURN"
    INDIVIDUAL_FULFILL = "INDIVIDUAL_FULFILL"
    WE_OWE_RESERVE = "WE_OWE_RESERVE"
    WE_OWE_RELEASE = "WE_OWE_RELEASE"
    WE_OWE_FULFILL = "WE_OWE_FULFILL"
    REVERSAL = "REVERSAL"


@dataclass
class InventoryBalance:
    unit_campaign_id: str
    product_id: str
    kernel_physical_qty: int
    sold_in_possession_qty: int = 0
    council_on_order_qty: int = 0
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.kernel_physical_qty < 0:
            raise ValueError("kernel_physical_qty must be non-negative")
        if self.sold_in_possession_qty < 0:
            raise ValueError("sold_in_possession_qty must be non-negative")
        if self.kernel_physical_qty < self.sold_in_possession_qty:
            raise ValueError("kernel_physical_qty must be >= sold_in_possession_qty")
        if self.council_on_order_qty < 0:
            raise ValueError("council_on_order_qty must be non-negative")

    @property
    def sellable_kernel_qty(self) -> int:
        return self.kernel_physical_qty - self.sold_in_possession_qty


@dataclass
class ScoutCustodyBalance:
    unit_campaign_id: str
    product_id: str
    profile_id: str
    campaign_id: str
    with_scout_qty: int
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.with_scout_qty < 0:
            raise ValueError("with_scout_qty must be non-negative")


@dataclass
class EventInventoryAllocation:
    unit_campaign_id: str
    product_id: str
    show_and_sell_id: str
    start_at: datetime
    end_at: datetime
    status: AllocationStatus = AllocationStatus.OPEN
    allocated_qty: int = 0
    sold_qty: int = 0
    released_qty: int = 0
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.allocated_qty < 0 or self.sold_qty < 0 or self.released_qty < 0:
            raise ValueError("quantities must be non-negative")
        if self.allocated_qty < self.sold_qty:
            raise ValueError("allocated_qty must be >= sold_qty")
        if self.allocated_qty < self.sold_qty + self.released_qty:
            raise ValueError("allocated_qty must be >= sold_qty + released_qty")

    @property
    def remaining_qty(self) -> int:
        return self.allocated_qty - self.sold_qty - self.released_qty


@dataclass
class InventoryMovement:
    movement_id: str
    unit_campaign_id: str
    product_id: str
    movement_type: InventoryMovementType
    actor_account_id: str
    occurred_at: datetime
    kernel_physical_delta: int = 0
    sold_possession_delta: int = 0
    with_scout_delta: int = 0
    assigned_delta: int = 0
    council_on_order_delta: int = 0
    profile_id: Optional[str] = None
    show_and_sell_id: Optional[str] = None
    sale_id: Optional[str] = None
    order_id: Optional[str] = None
    we_owe_id: Optional[str] = None
    fulfillment_id: Optional[str] = None
    finalization_id: Optional[str] = None
    reason: Optional[str] = None
    inventory_version: int = 1
    idempotency_key: str = ""
    _append_only: bool = field(default=True, init=False, repr=False)
