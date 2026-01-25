"""
Lambda handler for PaymentMethod.qrCodeUrl field resolver.

Generates a single presigned URL for a payment method QR code.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import generate_presigned_get_url
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.payment_methods import generate_presigned_get_url


def _is_already_presigned(qr_code_url: str) -> bool:
    """Check if URL is already a presigned URL."""
    return "X-Amz-Algorithm" in qr_code_url or "X-Amz-Signature" in qr_code_url


def _validate_and_extract_params(event: Dict[str, Any]) -> tuple[str, str, str | None]:
    """Validate event and extract required parameters."""
    owner_account_id: str | None = event.get("ownerAccountId")
    if not owner_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Owner account ID required")
    
    method_name: str = event.get("methodName", "")
    s3_key: str | None = event.get("s3Key")
    return owner_account_id, method_name, s3_key


def generate_qr_code_presigned_url(event: Dict[str, Any], context: Any) -> str | None:
    """Generate a presigned URL for a single payment method QR code."""
    logger = get_logger(__name__)

    try:
        qr_code_url: str | None = event.get("qrCodeUrl")
        if not qr_code_url:
            return None

        if _is_already_presigned(qr_code_url):
            return qr_code_url

        owner_account_id, method_name, s3_key = _validate_and_extract_params(event)

        presigned_url: str | None = generate_presigned_get_url(
            owner_account_id, method_name, s3_key, expiry_seconds=900
        )

        logger.info("Generated QR code presigned URL", owner_account_id=owner_account_id, method_name=method_name)
        return presigned_url

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to generate presigned URL", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to generate QR code URL")
