"""
Lambda handler for validating payment methods during order creation.

This handler is called as part of the createOrder pipeline to ensure
the payment method exists for the profile owner's account.
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


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Validate that the payment method exists for the profile owner's account.

    Args:
        event: AppSync pipeline event with:
            - prev.result.ownerAccountId: Profile owner's account ID
            - arguments.input.paymentMethod: Payment method name
        context: Lambda context (unused)

    Returns:
        The input unchanged (passthrough)

    Raises:
        AppError: If payment method does not exist for the account
    """
    logger = get_logger(__name__)

    try:
        # Extract from AppSync pipeline event
        prev_result = event.get("prev", {}).get("result", {})
        arguments = event.get("arguments", {})
        input_data = arguments.get("input", {})

        # Get owner account ID from previous pipeline step (should be set by verify_profile_write_access)
        owner_account_id = prev_result.get("ownerAccountId")
        if not owner_account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Owner account ID not found in pipeline context")

        # Get payment method from order input
        payment_method = input_data.get("paymentMethod")
        if not payment_method:
            raise AppError(ErrorCode.INVALID_INPUT, "Payment method is required")

        # Remove ACCOUNT# prefix if present
        if owner_account_id.startswith("ACCOUNT#"):
            owner_account_id = owner_account_id[8:]

        logger.info(
            "Validating payment method for order",
            owner_account_id=owner_account_id,
            payment_method=payment_method,
        )

        # Validate payment method exists
        validate_payment_method_exists(owner_account_id, payment_method)

        logger.info(
            "Payment method validated successfully",
            owner_account_id=owner_account_id,
            payment_method=payment_method,
        )

        # Return the prev.result unchanged (passthrough)
        result: Dict[str, Any] = dict(prev_result) if isinstance(prev_result, dict) else {}
        return result

    except AppError:
        # Re-raise app errors
        raise
    except Exception as e:
        logger.error("Unexpected error validating payment method", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to validate payment method")
