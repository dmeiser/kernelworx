"""Show & Sell Stage 3 wave 1 - ShowAndSell model (leaf 3.1.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class ShowAndSell:
    show_and_sell_id: str
    scope_type: str  # "UNIT" or "CAMPAIGN"
    scope_id: str
    location: str
    address: Optional[str] = None
    start_utc: datetime = None  # type: ignore
    end_utc: datetime = None  # type: ignore
    state: str = "SCHEDULED"
    split_override: Optional[str] = None
    we_owe_enabled: bool = False
    product_ids: List[str] = field(default_factory=list)
    finalization_pointers: List[str] = field(default_factory=list)
    version: int = 1
    cancellation_audit: Optional[dict[str, Any]] = None
