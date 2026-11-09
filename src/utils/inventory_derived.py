"""
Derived inventory quantities (Show & Sell, spec DATA_MODEL §7 normative
formulas). Every quantity the UI reports is computed here from raw records;
nothing is stored redundantly. Exclusions per §7: With Scout and on-order
never reduce Council need; covered We Owe is not demand; overage and
hypothetical future event sales are not demand.

Pure functions over plain ints — the handlers feed rows read from DynamoDB,
tests feed literals, and wave 4's event allocations plug in as inputs
without changing the formulas.
"""

from typing import Any, Dict, List, cast


def sellable_kernel_qty(kernel_physical_qty: int, sold_in_possession_qty: int) -> int:
    """kernelPhysicalQty - soldInPossessionQty (We Owe-reserved stock is
    physically present but unavailable)."""
    return kernel_physical_qty - sold_in_possession_qty


def assigned_open_qty(allocations: List[Dict[str, Any]]) -> int:
    """Sum of remaining quantities on OPEN event allocations (wave 4 rows)."""
    return sum(int(a.get("remainingQty", 0)) for a in allocations if a.get("status") == "OPEN")


def unassigned_kernel_qty(
    kernel_physical_qty: int, sold_in_possession_qty: int, allocations: List[Dict[str, int]]
) -> int:
    return max(0, sellable_kernel_qty(kernel_physical_qty, sold_in_possession_qty) - assigned_open_qty(allocations))


def assignment_overage_qty(
    kernel_physical_qty: int, sold_in_possession_qty: int, allocations: List[Dict[str, int]]
) -> int:
    return max(0, assigned_open_qty(allocations) - sellable_kernel_qty(kernel_physical_qty, sold_in_possession_qty))


def with_scout_qty(custody_rows: List[Dict[str, Any]]) -> int:
    return sum(int(c.get("withScoutQty", 0)) for c in custody_rows)


def total_unit_owned_undelivered_qty(kernel_physical_qty: int, custody_rows: List[Dict[str, Any]]) -> int:
    return kernel_physical_qty + with_scout_qty(custody_rows)


def actual_council_demand_qty(unfulfilled_individual_qty: int, uncovered_we_owe_qty: int) -> int:
    return unfulfilled_individual_qty + uncovered_we_owe_qty


def physical_stock_council_need_qty(
    kernel_physical_qty: int, sold_in_possession_qty: int, unfulfilled_individual_qty: int, uncovered_we_owe_qty: int
) -> int:
    return max(
        0,
        actual_council_demand_qty(unfulfilled_individual_qty, uncovered_we_owe_qty)
        - sellable_kernel_qty(kernel_physical_qty, sold_in_possession_qty),
    )


def after_assignments_council_need_qty(
    kernel_physical_qty: int,
    sold_in_possession_qty: int,
    allocations: List[Dict[str, int]],
    unfulfilled_individual_qty: int,
    uncovered_we_owe_qty: int,
) -> int:
    return max(
        0,
        actual_council_demand_qty(unfulfilled_individual_qty, uncovered_we_owe_qty)
        - unassigned_kernel_qty(kernel_physical_qty, sold_in_possession_qty, allocations),
    )


def derive_position(
    *,
    unit_campaign_id: str,
    product_id: str,
    kernel_physical_qty: int,
    sold_in_possession_qty: int,
    council_on_order_qty: int,
    balance_version: int,
    allocations: List[Dict[str, Any]],
    custody_rows: List[Dict[str, Any]],
    unfulfilled_individual_qty: int = 0,
    uncovered_we_owe_qty: int = 0,
) -> Dict[str, Any]:
    """The complete InventoryPosition vocabulary in one call."""
    return cast(
        Dict[str, Any],
        {
            "unitCampaignId": unit_campaign_id,
            "productId": product_id,
            "balance": {
                "unitCampaignId": unit_campaign_id,
                "productId": product_id,
                "kernelPhysicalQty": kernel_physical_qty,
                "soldInPossessionQty": sold_in_possession_qty,
                "councilOnOrderQty": council_on_order_qty,
                "version": balance_version,
            },
            "sellableKernelQty": sellable_kernel_qty(kernel_physical_qty, sold_in_possession_qty),
            "assignedOpenQty": assigned_open_qty(allocations),
            "unassignedKernelQty": unassigned_kernel_qty(kernel_physical_qty, sold_in_possession_qty, allocations),
            "assignmentOverageQty": assignment_overage_qty(kernel_physical_qty, sold_in_possession_qty, allocations),
            "withScoutQty": with_scout_qty(custody_rows),
            "totalUnitOwnedUndeliveredQty": total_unit_owned_undelivered_qty(kernel_physical_qty, custody_rows),
            "actualCouncilDemandQty": actual_council_demand_qty(unfulfilled_individual_qty, uncovered_we_owe_qty),
            "physicalStockCouncilNeedQty": physical_stock_council_need_qty(
                kernel_physical_qty, sold_in_possession_qty, unfulfilled_individual_qty, uncovered_we_owe_qty
            ),
            "afterAssignmentsCouncilNeedQty": after_assignments_council_need_qty(
                kernel_physical_qty,
                sold_in_possession_qty,
                allocations,
                unfulfilled_individual_qty,
                uncovered_we_owe_qty,
            ),
        },
    )
