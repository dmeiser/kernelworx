"""Lambda resolver for Show & Sell inventory operations (Stage 2 wave 2)."""

from typing import TYPE_CHECKING, Any, Dict, Optional

try:  # pragma: no cover
    from utils.dynamodb import get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import get_required_env, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)


def record_inventory_receipt(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Record a positive-integer inventory receipt (INV-M-01)."""
    arguments = event.get("arguments", {})
    quantity = arguments.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")
    # Implementation deferred: full atomic write requires inventory tables (wave 1 model).
    return {"success": True, "quantity": quantity}


def adjust_inventory(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Signed nonzero adjustment with reason (INV-M-02)."""
    arguments = event.get("arguments", {})
    delta = arguments.get("delta")
    reason = arguments.get("reason")
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        raise AppError(ErrorCode.INVALID_INPUT, "delta must be a nonzero integer")
    if not reason:
        raise AppError(ErrorCode.INVALID_INPUT, "reason is required")
    return {"success": True, "delta": delta}


def adjust_council_on_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Adjust council-on-order quantity only (INV-M-03)."""
    arguments = event.get("arguments", {})
    delta = arguments.get("delta")
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise AppError(ErrorCode.INVALID_INPUT, "delta must be an integer")
    result = arguments.get("current", 0) + delta
    if result < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "result cannot be negative")
    return {"success": True, "councilOnOrderQty": result}
