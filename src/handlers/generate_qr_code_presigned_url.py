"""
Lambda handler for PaymentMethod.qrCodeUrl field resolver.

Generates a single presigned URL for a payment method QR code.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from utils.logging import get_logger
    from utils.payment_methods import generate_presigned_get_url
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.logging import get_logger
    from ..utils.payment_methods import generate_presigned_get_url
    from ..utils.errors import AppError, ErrorCode


def generate_qr_code_presigned_url(event: Dict[str, Any], context: Any) -> str | None:
    """
    Generate a presigned URL for a single payment method QR code.
    
    Args:
        event: Contains qrCodeUrl, ownerAccountId, methodName, and s3Key
        context: Lambda context
    
    Returns:
        Presigned URL string, or None if no QR code
    """
    logger = get_logger(__name__)
    
    try:
        qr_code_url = event.get("qrCodeUrl")
        owner_account_id = event.get("ownerAccountId")
        method_name = event.get("methodName", "")
        s3_key = event.get("s3Key")
        
        # If no QR code URL, return None
        if not qr_code_url:
            return None
        
        # If already a presigned URL (has query parameters), return as-is
        if "X-Amz-Algorithm" in qr_code_url or "X-Amz-Signature" in qr_code_url:
            return qr_code_url
        
        # Validate owner account ID for authorization
        if not owner_account_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Owner account ID required")
        
        # Generate presigned URL (15 minutes expiry)
        presigned_url = generate_presigned_get_url(
            owner_account_id,
            method_name,
            s3_key,
            expiry_seconds=900
        )
        
        logger.info(
            "Generated QR code presigned URL",
            owner_account_id=owner_account_id,
            method_name=method_name
        )
        
        return presigned_url
        
    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to generate presigned URL", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to generate QR code URL")
