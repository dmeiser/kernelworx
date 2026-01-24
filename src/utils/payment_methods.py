"""
Payment methods utilities.

Handles CRUD operations for custom payment methods (user preferences)
and S3 QR code management.
"""

import os
import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from .dynamodb import get_required_env, tables
    from .errors import AppError, ErrorCode
    from .logging import get_logger


# Module-level S3 client proxy for testing
s3_client: "S3Client | None" = None

# Reserved payment method names (case-insensitive)
RESERVED_NAMES = {"cash", "check"}

# Maximum payment method name length
MAX_NAME_LENGTH = 50

# Maximum QR code file size (5MB)
MAX_QR_FILE_SIZE = 5 * 1024 * 1024

# Allowed QR code MIME types
ALLOWED_QR_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}

# QR code S3 path prefix
QR_CODE_S3_PREFIX = "payment-qr-codes"


def get_qr_code_s3_key(account_id: str, payment_method_name: str, extension: str = "png") -> str:
    """Generate S3 key for a payment method QR code.

    DEPRECATED: Use generate_qr_code_s3_key() for new uploads.
    This function remains for compatibility with tests that rely on predictable keys.

    Args:
        account_id: Account ID
        payment_method_name: Payment method name
        extension: File extension (png, jpg, webp)

    Returns:
        S3 key in format: payment-qr-codes/{account_id}/{slug}.{extension}
    """
    slug = slugify(payment_method_name)
    return f"{QR_CODE_S3_PREFIX}/{account_id}/{slug}.{extension}"


def generate_qr_code_s3_key(account_id: str, extension: str = "png") -> str:
    """Generate a new UUID-based S3 key for QR code upload.

    Uses UUID to avoid collisions when payment methods have similar names.
    The generated key should be stored in the payment method record.

    Args:
        account_id: Account ID
        extension: File extension (png, jpg, webp)

    Returns:
        S3 key in format: payment-qr-codes/{account_id}/{uuid}.{extension}
    """
    file_id = uuid.uuid4().hex
    return f"{QR_CODE_S3_PREFIX}/{account_id}/{file_id}.{extension}"


def validate_qr_s3_key(s3_key: str, account_id: str) -> bool:
    """Validate that an S3 key belongs to the given account.

    Security check to prevent users from claiming QR codes they don't own.

    Args:
        s3_key: S3 key to validate
        account_id: Account ID that should own the key

    Returns:
        True if key is valid and belongs to account, False otherwise
    """
    # Key must start with the QR code prefix
    if not s3_key.startswith(f"{QR_CODE_S3_PREFIX}/"):
        return False

    # Key must contain the account ID as the second path segment
    parts = s3_key.split("/")
    if len(parts) < 3:
        return False

    # parts[0] = "payment-qr-codes", parts[1] = account_id, parts[2] = filename
    if parts[1] != account_id:
        return False

    # Filename must have allowed extension
    filename = parts[2]
    allowed_extensions = (".png", ".jpg", ".jpeg", ".webp")
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        return False

    return True


def _get_s3_client() -> "S3Client":
    """Return the S3 client (module-level override for tests, otherwise a fresh boto3 client)."""
    global s3_client
    if s3_client is not None:
        return s3_client
    return boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))


def slugify(text: str) -> str:
    """
    Convert text to URL-safe slug for S3 keys.

    Converts to lowercase, replaces spaces/underscores with hyphens,
    and removes unsafe characters.

    Args:
        text: Text to slugify

    Returns:
        Slugified text (e.g., "Venmo - Tom" -> "venmo-tom")
    """
    # Convert to lowercase
    slug = text.lower()

    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)

    # Remove all characters except alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Remove leading/trailing hyphens and collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug).strip("-")

    return slug


def is_reserved_name(name: str) -> bool:
    """
    Check if a payment method name is reserved (Cash or Check).

    Args:
        name: Payment method name to check

    Returns:
        True if name is reserved (case-insensitive)
    """
    return name.lower() in RESERVED_NAMES


def validate_name_unique(account_id: str, name: str, exclude_current: Optional[str] = None) -> None:
    """
    Validate that a payment method name is unique for the account.

    Case-insensitive uniqueness check.

    Args:
        account_id: Account ID to check
        name: Payment method name to validate
        exclude_current: Current name to exclude from check (for updates)

    Raises:
        AppError: If name already exists (case-insensitive)
    """
    logger = get_logger(__name__)

    try:
        # Get existing payment methods from account record
        account_id_key = f"ACCOUNT#{account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        if "Item" not in response:
            return  # No account found, name is unique

        # Payment methods are stored in preferences.paymentMethods
        preferences = response["Item"].get("preferences", {})
        existing_methods = preferences.get("paymentMethods", [])

        # Check for duplicates (case-insensitive)
        name_lower = name.lower()
        for method in existing_methods:
            method_name = method.get("name", "")

            # Skip the current method if we're updating
            if exclude_current and method_name.lower() == exclude_current.lower():
                continue

            if method_name.lower() == name_lower:
                raise AppError(ErrorCode.INVALID_INPUT, f"Payment method '{name}' already exists")

    except ClientError as e:
        logger.error("Failed to check payment method uniqueness", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to validate payment method name")


def get_payment_methods(account_id: str) -> List[Dict[str, Any]]:
    """
    Get all custom payment methods for an account.

    Does NOT include global methods (Cash, Check).
    Those are injected at the GraphQL layer.

    Args:
        account_id: Account ID

    Returns:
        List of payment methods (may be empty)
    """
    logger = get_logger(__name__)

    try:
        account_id_key = f"ACCOUNT#{account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        if "Item" not in response:
            return []

        # Payment methods are stored in preferences.paymentMethods
        preferences = response["Item"].get("preferences", {})
        methods: List[Dict[str, Any]] = preferences.get("paymentMethods", [])
        return methods

    except ClientError as e:
        logger.error("Failed to get payment methods", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to retrieve payment methods")


def validate_payment_method_exists(account_id: str, payment_method_name: str) -> None:
    """
    Validate that a payment method exists for an account.

    Checks both global methods (Cash, Check) and custom payment methods.

    Args:
        account_id: Account ID to check
        payment_method_name: Name of payment method to validate

    Raises:
        AppError: If payment method does not exist for this account
    """
    # Check if it's a global method (always valid)
    if payment_method_name.lower() in {"cash", "check"}:
        return

    # Check custom payment methods
    custom_methods = get_payment_methods(account_id)
    method_names = {method["name"].lower() for method in custom_methods}

    if payment_method_name.lower() not in method_names:
        raise AppError(
            ErrorCode.INVALID_INPUT, f"Payment method '{payment_method_name}' does not exist for this account"
        )


def create_payment_method(account_id: str, name: str) -> Dict[str, Any]:
    """
    Create a new custom payment method.

    Args:
        account_id: Account ID
        name: Payment method name

    Returns:
        Created payment method

    Raises:
        AppError: If name is invalid, reserved, or already exists
    """
    logger = get_logger(__name__)

    # Validate name
    if not name or not name.strip():
        raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")

    name = name.strip()

    if len(name) > MAX_NAME_LENGTH:
        raise AppError(ErrorCode.INVALID_INPUT, f"Payment method name must be {MAX_NAME_LENGTH} characters or less")

    if is_reserved_name(name):
        raise AppError(ErrorCode.INVALID_INPUT, f"'{name}' is a reserved payment method name")

    # Check uniqueness
    validate_name_unique(account_id, name)

    try:
        # Get existing account and methods
        account_id_key = f"ACCOUNT#{account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        existing_methods = []
        if "Item" in response:
            preferences = response["Item"].get("preferences", {})
            existing_methods = preferences.get("paymentMethods", [])

        # Create new method
        new_method: Dict[str, Any] = {"name": name, "qrCodeUrl": None}

        # Append to list
        existing_methods.append(new_method)

        # Update account with new methods
        preferences = response.get("Item", {}).get("preferences", {})
        preferences["paymentMethods"] = existing_methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        logger.info("Created payment method", account_id=account_id, name=name)

        return new_method

    except ClientError as e:
        logger.error("Failed to create payment method", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create payment method")


def update_payment_method(account_id: str, old_name: str, new_name: str) -> Dict[str, Any]:
    """
    Update (rename) a payment method.

    Args:
        account_id: Account ID
        old_name: Current payment method name
        new_name: New payment method name

    Returns:
        Updated payment method

    Raises:
        AppError: If method not found, new name is invalid, reserved, or already exists
    """
    logger = get_logger(__name__)

    # Validate new name
    if not new_name or not new_name.strip():
        raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")

    new_name = new_name.strip()

    if len(new_name) > MAX_NAME_LENGTH:
        raise AppError(ErrorCode.INVALID_INPUT, f"Payment method name must be {MAX_NAME_LENGTH} characters or less")

    if is_reserved_name(new_name):  # pragma: no branch
        raise AppError(ErrorCode.INVALID_INPUT, f"'{new_name}' is a reserved payment method name")

    # Check uniqueness (exclude current method)
    validate_name_unique(account_id, new_name, exclude_current=old_name)

    try:
        # Get existing account and methods
        account_id_key = f"ACCOUNT#{account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        if "Item" not in response:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{old_name}' not found")

        preferences = response["Item"].get("preferences", {})
        existing_methods = preferences.get("paymentMethods", [])

        # Find and update method
        updated_method = None
        for method in existing_methods:  # pragma: no branch
            if method.get("name") == old_name:
                method["name"] = new_name
                updated_method = method
                break

        if not updated_method:  # pragma: no branch
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{old_name}' not found")

        # Update account with modified methods
        preferences = response.get("Item", {}).get("preferences", {})
        preferences["paymentMethods"] = existing_methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        logger.info("Updated payment method", account_id=account_id, old_name=old_name, new_name=new_name)

        # Return updated method (create a copy for type safety)
        return dict(updated_method)

    except ClientError as e:
        logger.error("Failed to update payment method", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to update payment method")


def delete_payment_method(account_id: str, name: str) -> None:
    """
    Delete a custom payment method and its QR code.

    Args:
        account_id: Account ID
        name: Payment method name to delete

    Raises:
        AppError: If method not found or deletion fails
    """
    logger = get_logger(__name__)

    # Cannot delete reserved names (they're not stored anyway)
    if is_reserved_name(name):
        raise AppError(ErrorCode.INVALID_INPUT, f"Cannot delete reserved payment method '{name}'")

    try:
        # Get existing account and methods
        account_id_key = f"ACCOUNT#{account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        if "Item" not in response:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{name}' not found")

        preferences = response["Item"].get("preferences", {})
        existing_methods = preferences.get("paymentMethods", [])

        # Find and remove method
        method_to_delete = None
        new_methods = []
        for method in existing_methods:  # pragma: no branch
            if method.get("name") == name:
                method_to_delete = method
            else:
                new_methods.append(method)

        if not method_to_delete:  # pragma: no branch
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{name}' not found")

        # Delete QR code from S3 if exists
        if method_to_delete.get("qrCodeUrl"):
            try:
                delete_qr_from_s3(account_id, name)
            except Exception as e:
                logger.warning("Failed to delete QR code, continuing with method deletion", error=str(e))

        # Update account with remaining methods (or empty list)
        preferences = response.get("Item", {}).get("preferences", {})
        preferences["paymentMethods"] = new_methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        logger.info("Deleted payment method", account_id=account_id, name=name)

    except ClientError as e:
        logger.error("Failed to delete payment method", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete payment method")


def validate_qr_file(file_bytes: bytes, content_type: str) -> None:
    """
    Validate QR code file constraints.

    Args:
        file_bytes: File content bytes
        content_type: MIME type

    Raises:
        AppError: If file exceeds size limit or has unsupported type
    """
    # Check file size
    if len(file_bytes) > MAX_QR_FILE_SIZE:
        raise AppError(ErrorCode.INVALID_INPUT, f"QR code file must be {MAX_QR_FILE_SIZE // (1024 * 1024)}MB or less")

    # Check content type
    if content_type not in ALLOWED_QR_MIME_TYPES:
        raise AppError(ErrorCode.INVALID_INPUT, "QR code must be PNG, JPG, or WEBP format")


def upload_qr_to_s3(
    account_id: str, payment_method_name: str, file_bytes: bytes, content_type: str = "image/png"
) -> str:
    """
    Upload QR code to S3.

    Args:
        account_id: Account ID
        payment_method_name: Payment method name
        file_bytes: Image file bytes
        content_type: MIME type (default: image/png)

    Returns:
        S3 key for the uploaded file

    Raises:
        AppError: If upload fails or file validation fails
    """
    logger = get_logger(__name__)

    # Validate file
    validate_qr_file(file_bytes, content_type)

    # Determine file extension from content type
    extension_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    extension = extension_map.get(content_type, "png")

    # Generate S3 key
    s3_key = get_qr_code_s3_key(account_id, payment_method_name, extension)

    bucket_name = get_required_env("EXPORTS_BUCKET")

    try:
        s3 = _get_s3_client()
        s3.put_object(Bucket=bucket_name, Key=s3_key, Body=file_bytes, ContentType=content_type)

        logger.info("Uploaded QR code to S3", account_id=account_id, payment_method=payment_method_name, s3_key=s3_key)

        return s3_key

    except ClientError as e:
        logger.error("Failed to upload QR code to S3", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to upload QR code")


def delete_qr_by_key(s3_key: str) -> None:
    """
    Delete a specific QR code from S3 by its key.

    Args:
        s3_key: The S3 key to delete

    Raises:
        AppError: If deletion fails
    """
    logger = get_logger(__name__)
    bucket_name = get_required_env("EXPORTS_BUCKET")

    try:
        s3 = _get_s3_client()
        s3.delete_object(Bucket=bucket_name, Key=s3_key)
        logger.info("Deleted QR code from S3", s3_key=s3_key)
    except ClientError as e:
        # Ignore 404 errors (file doesn't exist) - idempotent delete
        if e.response.get("Error", {}).get("Code") != "NoSuchKey":
            logger.error("Failed to delete QR code from S3", s3_key=s3_key, error=str(e))
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete QR code")
    except Exception as e:
        logger.error("Failed to delete QR code from S3", s3_key=s3_key, error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete QR code")


def delete_qr_from_s3(account_id: str, payment_method_name: str) -> None:
    """
    Delete QR code from S3.

    DEPRECATED: Use delete_qr_by_key() when you have the stored s3_key.
    This function remains for backwards compatibility with slug-based keys.

    Deletes all possible file extensions (png, jpg, webp) to ensure cleanup.

    Args:
        account_id: Account ID
        payment_method_name: Payment method name

    Raises:
        AppError: If deletion fails
    """
    logger = get_logger(__name__)

    slug = slugify(payment_method_name)
    bucket_name = get_required_env("EXPORTS_BUCKET")

    # Try all possible extensions
    extensions = ["png", "jpg", "webp"]

    try:
        s3 = _get_s3_client()

        for ext in extensions:  # pragma: no branch
            s3_key = f"payment-qr-codes/{account_id}/{slug}.{ext}"

            try:
                s3.delete_object(Bucket=bucket_name, Key=s3_key)
                logger.info(
                    "Deleted QR code from S3", account_id=account_id, payment_method=payment_method_name, s3_key=s3_key
                )
            except ClientError as e:
                # Ignore 404 errors (file doesn't exist)
                if e.response.get("Error", {}).get("Code") != "NoSuchKey":
                    logger.warning("Failed to delete QR code variant", s3_key=s3_key, error=str(e))

    except Exception as e:
        logger.error("Failed to delete QR code from S3", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete QR code")


def generate_presigned_get_url(
    account_id: str, payment_method_name: str, s3_key: Optional[str] = None, expiry_seconds: int = 900
) -> Optional[str]:
    """
    Generate pre-signed GET URL for QR code.

    Args:
        account_id: Account ID
        payment_method_name: Payment method name
        s3_key: S3 key (if None, will attempt to find existing file)
        expiry_seconds: URL expiry time in seconds (default: 900 = 15 minutes)

    Returns:
        Pre-signed URL or None if QR code doesn't exist

    Raises:
        AppError: If URL generation fails
    """
    logger = get_logger(__name__)

    bucket_name = get_required_env("EXPORTS_BUCKET")

    try:
        s3 = _get_s3_client()

        # If no s3_key provided, try to find existing file
        if not s3_key:
            extensions = ["png", "jpg", "webp"]

            for ext in extensions:
                test_key = get_qr_code_s3_key(account_id, payment_method_name, ext)
                try:
                    s3.head_object(Bucket=bucket_name, Key=test_key)
                    s3_key = test_key
                    break
                except ClientError:
                    continue

            if not s3_key:
                return None  # No QR code found

        # Always use signed S3 URLs for QR codes (no public CloudFront exposure)
        # This ensures ownership verification and prevents unauthorized access
        url = s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket_name, "Key": s3_key}, ExpiresIn=expiry_seconds
        )

        logger.info(
            "Generated GET URL",
            account_id=account_id,
            payment_method=payment_method_name,
            s3_key=s3_key,
        )

        return url

    except ClientError as e:
        logger.error("Failed to generate pre-signed URL", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to generate QR code URL")
