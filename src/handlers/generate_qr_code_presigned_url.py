"""
Lambda handler for PaymentMethod.qrCodeUrl field resolver.

Generates a single presigned URL for a payment method QR code.
"""

from typing import Any, Dict, cast

try:  # pragma: no cover
    from utils.auth import check_profile_access
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import generate_presigned_get_url
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.payment_methods import generate_presigned_get_url


def _caller_can_access_qr(caller_id: str, owner_account_id: str, profile_id: str | None) -> bool:
    """Check if caller may retrieve a QR code for the owner's payment method.

    Owners may always retrieve their own QR codes. WRITE collaborators may
    retrieve QR codes for payment methods on profiles they have WRITE access to.
    """
    if caller_id == owner_account_id:
        return True

    if not profile_id:
        return False

    try:
        return cast(bool, check_profile_access(caller_id, profile_id, "WRITE"))
    except AppError as e:
        if e.error_code == ErrorCode.NOT_FOUND:
            return False
        raise


def _validate_and_extract_params(event: Dict[str, Any]) -> tuple[str, str, str | None]:
    """Validate event and extract required parameters."""
    identity = event.get("identity", {})
    caller_id = identity.get("sub")
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    owner_account_id: str | None = event.get("ownerAccountId")
    if not owner_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Owner account ID required")

    profile_id: str | None = event.get("profileId")
    if not _caller_can_access_qr(caller_id, owner_account_id, profile_id):
        raise AppError(ErrorCode.FORBIDDEN, "Access denied")

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

        # Always validate ownership and re-sign from a validated key. Never
        # short-circuit on an already-presigned stored URL: that would return
        # another user's QR code URL before the ownership check runs.
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
