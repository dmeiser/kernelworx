"""
Generate a presigned URL for a payment method QR code (API Gateway proxy event shape).

Restored from the AppSync-shaped ``main`` version. Reads the caller id from
``requestContext.authorizer.claims.sub`` and inputs (ownerAccountId, methodName,
s3Key, qrCodeUrl) from the request body. Route: POST /api/payment-methods/{id}/qr-presigned-url.
"""

import json
from typing import Any, Dict, Optional

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import generate_presigned_get_url
    from utils.proxy_event import get_caller_id, parse_body
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.errors import AppError, ErrorCode
    from src.utils.logging import get_logger
    from src.utils.payment_methods import generate_presigned_get_url
    from src.utils.proxy_event import get_caller_id, parse_body

logger = get_logger(__name__)


def _is_already_presigned(qr_code_url: str) -> bool:
    return "X-Amz-Algorithm" in qr_code_url or "X-Amz-Signature" in qr_code_url


def _validate_and_extract_params(event: Dict[str, Any]) -> tuple:
    caller_id = get_caller_id(event)
    body = parse_body(event)
    owner_account_id: Optional[str] = body.get("ownerAccountId") or (event.get("pathParameters") or {}).get("id")
    if not owner_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Owner account ID required")
    if caller_id != owner_account_id and caller_id != (
        owner_account_id[8:] if owner_account_id.startswith("ACCOUNT#") else owner_account_id
    ):
        raise AppError(ErrorCode.FORBIDDEN, "Access denied")
    method_name: str = body.get("methodName") or body.get("name") or ""
    s3_key: Optional[str] = body.get("s3Key")
    return owner_account_id, method_name, s3_key


def generate_qr_code_presigned_url(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Generate a presigned URL for a single payment method QR code."""
    logger.info("generate_qr_code_presigned_url invoked")
    try:
        body = parse_body(event)
        qr_code_url: Optional[str] = body.get("qrCodeUrl")
        if qr_code_url:
            if _is_already_presigned(qr_code_url):
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"url": qr_code_url}),
                }
        owner_account_id, method_name, s3_key = _validate_and_extract_params(event)
        normalized_owner = owner_account_id[8:] if owner_account_id.startswith("ACCOUNT#") else owner_account_id
        presigned_url = generate_presigned_get_url(normalized_owner, method_name, s3_key, expiry_seconds=900)
        logger.info("Generated QR code presigned URL", owner_account_id=normalized_owner, method_name=method_name)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"url": presigned_url}),
        }
    except AppError as e:
        status = {ErrorCode.UNAUTHORIZED: 401, ErrorCode.FORBIDDEN: 403}.get(e.error_code, 400)
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": e.message}),
        }
    except Exception as e:
        logger.error("Failed to generate presigned URL", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to generate QR code URL"}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint. Route POST /api/payment-methods/{id}/qr-presigned-url."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "POST")
    path = event.get("path") or "/"
    if path.startswith("/api/payment-methods/") and path.endswith("/qr-presigned-url") and method == "POST":
        middle = path[len("/api/payment-methods/") : -len("/qr-presigned-url")]
        event["pathParameters"] = {"id": unquote(middle)}
        return generate_qr_code_presigned_url(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
