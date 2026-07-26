"""
Validate a payment method (API Gateway proxy event shape).

Restored from the AppSync pipeline-shaped ``main`` version. In the HTMX app the
validation endpoint is invoked when creating/editing a payment method to ensure
the name is well-formed and (when validating against an existing order context)
that the method exists for the account. Reads the caller id from
``requestContext.authorizer.claims.sub`` and inputs from the request body.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import validate_payment_method_exists
    from utils.proxy_event import get_caller_id, parse_body
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.errors import AppError, ErrorCode
    from src.utils.logging import get_logger
    from src.utils.payment_methods import validate_payment_method_exists
    from src.utils.proxy_event import get_caller_id, parse_body

logger = get_logger(__name__)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Validate a payment method name (and existence when an owner context is provided)."""
    import json

    logger.info("validate_payment_method invoked")
    body = parse_body(event)
    payment_method = (body.get("paymentMethod") or body.get("name") or "").strip()
    owner_account_id = body.get("ownerAccountId")

    if not payment_method:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Payment method is required"}),
        }

    caller_id = get_caller_id(event)
    if owner_account_id and owner_account_id != caller_id:
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Access denied"}),
        }

    try:
        if owner_account_id:
            normalized = owner_account_id[8:] if owner_account_id.startswith("ACCOUNT#") else owner_account_id
            validate_payment_method_exists(normalized, payment_method)
            logger.info("Payment method validated", owner_account_id=normalized, payment_method=payment_method)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"valid": True, "paymentMethod": payment_method}),
        }
    except AppError as e:
        status = {ErrorCode.INVALID_INPUT: 400, ErrorCode.FORBIDDEN: 403, ErrorCode.UNAUTHORIZED: 401}.get(
            e.error_code, 400
        )
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"valid": False, "error": e.message}),
        }
    except Exception as e:
        logger.error("Unexpected error validating payment method", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"valid": False, "error": "Failed to validate payment method"}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint. Route POST /api/payment-methods/validate."""
    method = event.get("httpMethod", "POST")
    path = event.get("path") or "/"
    if path == "/api/payment-methods/validate" and method == "POST":
        return lambda_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
