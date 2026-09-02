"""
Lambda handler for validating payment methods during order creation and updates.

This handler is called as part of the createOrder and updateOrder pipelines to ensure
a supplied payment method exists for the profile owner's account. When no payment
method is supplied (e.g. updateOrder changing other fields), it passes through
without validation so historical payment methods remain valid.
"""

from typing import Any, Dict

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import validate_payment_method_exists
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.errors import AppError, ErrorCode
    from src.utils.logging import get_logger
    from src.utils.payment_methods import validate_payment_method_exists


def _extract_and_normalize_inputs(event: Dict[str, Any]) -> tuple[str, str | None]:
    """Extract and normalize owner_account_id and payment_method from event.

    Returns the payment_method as None when it is not supplied so callers can
    decide whether validation is required (e.g. updateOrder may omit it).
    """
    prev_result = event.get("prev", {}).get("result", {})
    arguments = event.get("arguments", {})
    input_data = arguments.get("input", {})

    owner_account_id = prev_result.get("ownerAccountId")
    if not owner_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Owner account ID not found in pipeline context")

    payment_method = input_data.get("paymentMethod")
    if not payment_method:
        return owner_account_id, None

    if owner_account_id.startswith("ACCOUNT#"):
        owner_account_id = owner_account_id[8:]

    return owner_account_id, payment_method


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Validate that the payment method exists for the profile owner's account.

    If arguments.input.paymentMethod is missing, empty, or None, the handler
    returns prev.result unchanged. This makes it safe to use in updateOrder,
    where paymentMethod is optional and should only be validated when supplied.

    Args:
        event: AppSync pipeline event with:
            - prev.result.ownerAccountId: Profile owner's account ID
            - arguments.input.paymentMethod: Optional payment method name
        context: Lambda context (unused)

    Returns:
        The previous pipeline result unchanged (passthrough)

    Raises:
        AppError: If payment method is supplied but does not exist for the account
    """
    logger = get_logger(__name__)

    try:
        owner_account_id, payment_method = _extract_and_normalize_inputs(event)

        prev_result = event.get("prev", {}).get("result", {})
        result: Dict[str, Any] = dict(prev_result) if isinstance(prev_result, dict) else {}

        if not payment_method:
            # Payment method not supplied; nothing to validate. This allows
            # updateOrder to modify other fields without re-validating the
            # existing payment method (including historical custom methods).
            return result

        logger.info(
            "Validating payment method for order", owner_account_id=owner_account_id, payment_method=payment_method
        )
        validate_payment_method_exists(owner_account_id, payment_method)
        logger.info(
            "Payment method validated successfully", owner_account_id=owner_account_id, payment_method=payment_method
        )

        return result

    except AppError:
        # Re-raise app errors
        raise
    except Exception as e:
        logger.error("Unexpected error validating payment method", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to validate payment method")
