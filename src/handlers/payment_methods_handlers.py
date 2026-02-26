"""
Payment methods Lambda handlers for AppSync resolvers.

These handlers provide S3 pre-signed URL generation for QR code uploads
and confirmations. They integrate with AppSync pipeline resolvers.
"""

import os
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.payment_methods import (
        delete_qr_by_key,
        delete_qr_from_s3,
        generate_qr_code_s3_key,
        get_payment_methods,
        is_reserved_name,
        validate_qr_s3_key,
    )
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import get_required_env, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.payment_methods import (
        delete_qr_by_key,
        delete_qr_from_s3,
        generate_qr_code_s3_key,
        get_payment_methods,
        is_reserved_name,
        validate_qr_s3_key,
    )


def _extract_and_validate_caller(event: Dict[str, Any]) -> str:
    """Extract and validate caller identity from event."""
    identity = event.get("identity", {})
    caller_id = identity.get("sub")
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller_id)


def _validate_payment_method_name(payment_method_name: str) -> None:
    """Validate payment method name is not empty or reserved."""
    if not payment_method_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")
    if is_reserved_name(payment_method_name):
        raise AppError(ErrorCode.INVALID_INPUT, f"Cannot use reserved method name '{payment_method_name}'")


def _verify_payment_method_exists(caller_id: str, payment_method_name: str) -> Dict[str, Any]:
    """Verify payment method exists and return it."""
    methods = get_payment_methods(caller_id)
    target = next((m for m in methods if m.get("name") == payment_method_name), None)
    if not target:
        raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")
    return dict(target)


def request_qr_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate pre-signed POST URL for QR code upload.

    AppSync Lambda resolver for requestPaymentMethodQRCodeUpload mutation.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        S3UploadInfo with uploadUrl, fields, and s3Key

    Raises:
        AppError: If payment method is reserved or doesn't exist
    """
    logger = get_logger(__name__)

    try:
        caller_id = _extract_and_validate_caller(event)
        
        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()
        _validate_payment_method_name(payment_method_name)
        _verify_payment_method_exists(caller_id, payment_method_name)

        # Generate UUID-based S3 key to avoid collisions from similar payment method names
        s3_key = generate_qr_code_s3_key(caller_id, "png")

        # Generate pre-signed POST URL (must use direct S3, not CloudFront)
        bucket_name = get_required_env("EXPORTS_BUCKET")
        s3_client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))

        presigned_post = s3_client.generate_presigned_post(
            Bucket=bucket_name,
            Key=s3_key,
            Fields={"Content-Type": "image/png"},
            Conditions=[
                {"Content-Type": "image/png"},
                ["content-length-range", 1, 5 * 1024 * 1024],  # 1 byte to 5MB
            ],
            ExpiresIn=900,  # 15 minutes
        )

        logger.info(
            "Generated pre-signed POST URL",
            account_id=caller_id,
            payment_method=payment_method_name,
            s3_key=s3_key,
        )

        return {"uploadUrl": presigned_post["url"], "fields": presigned_post["fields"], "s3Key": s3_key}

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to generate pre-signed POST URL", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to generate upload URL")


def _validate_s3_object_exists(bucket_name: str, s3_key: str) -> None:
    """Validate that S3 object exists at the specified key."""
    s3_client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))
    try:
        s3_client.head_object(Bucket=bucket_name, Key=s3_key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "404":
            raise AppError(ErrorCode.NOT_FOUND, "Upload not found. Please upload the file first.")
        raise


def _validate_qr_upload_inputs(payment_method_name: str, s3_key: str, caller_id: str) -> None:
    """Validate QR upload inputs (payment method name, s3_key, and s3_key ownership)."""
    if not payment_method_name or not s3_key:
        raise AppError(ErrorCode.INVALID_INPUT, "Payment method name and s3Key are required")
    
    if not validate_qr_s3_key(s3_key, caller_id):
        raise AppError(ErrorCode.FORBIDDEN, "Invalid S3 key - access denied")


def _update_payment_method_qr_url(caller_id: str, payment_method_name: str, s3_key: str) -> Dict[str, Any]:
    """Update payment method with QR code S3 key and return updated method."""
    account_id_key = f"ACCOUNT#{caller_id}"
    response = tables.accounts.get_item(Key={"accountId": account_id_key}, ConsistentRead=True)

    if "Item" not in response:
        raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

    existing_methods = response["Item"].get("preferences", {}).get("paymentMethods", [])

    method_updated = None
    for method in existing_methods:
        if method.get("name") == payment_method_name:
            method["qrCodeUrl"] = s3_key
            method_updated = method
            break

    if not method_updated:
        raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

    preferences = response.get("Item", {}).get("preferences", {})
    preferences["paymentMethods"] = existing_methods
    tables.accounts.update_item(
        Key={"accountId": account_id_key},
        UpdateExpression="SET preferences = :prefs",
        ExpressionAttributeValues={":prefs": preferences},
    )
    
    return dict(method_updated)


def confirm_qr_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Confirm QR code upload and generate pre-signed GET URL.

    AppSync Lambda resolver for confirmPaymentMethodQRCodeUpload mutation.
    Validates S3 object exists, updates DynamoDB, returns pre-signed GET URL.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        PaymentMethod with name and qrCodeUrl (pre-signed GET URL)

    Raises:
        AppError: If S3 object doesn't exist or update fails
    """
    logger = get_logger(__name__)

    try:
        caller_id = _extract_and_validate_caller(event)

        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()
        s3_key = arguments.get("s3Key", "").strip()

        _validate_qr_upload_inputs(payment_method_name, s3_key, caller_id)

        bucket_name = get_required_env("EXPORTS_BUCKET")
        _validate_s3_object_exists(bucket_name, s3_key)
        _update_payment_method_qr_url(caller_id, payment_method_name, s3_key)

        logger.info(
            "Confirmed QR code upload",
            account_id=caller_id,
            payment_method=payment_method_name,
            s3_key=s3_key,
        )

        return {"name": payment_method_name, "qrCodeUrl": s3_key}

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to confirm QR code upload", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to confirm upload")


def _delete_qr_from_s3_storage(stored_qr_key: str | None, caller_id: str, payment_method_name: str, logger: Any) -> None:
    """Delete QR code from S3 storage if it exists."""
    if not stored_qr_key:
        return
    
    if stored_qr_key.startswith("payment-qr-codes/"):
        try:
            delete_qr_by_key(stored_qr_key)
        except Exception as e:
            logger.info("S3 delete completed (object may not have existed)", error=str(e))
    else:
        # Fallback: Legacy slug-based key or HTTP URL - try the old method
        try:
            delete_qr_from_s3(caller_id, payment_method_name)
        except Exception as e:
            logger.info("S3 delete completed (object may not have existed)", error=str(e))


def _clear_qr_url_in_payment_method(caller_id: str, payment_method_name: str) -> None:
    """Update DynamoDB to clear qrCodeUrl for the specified payment method."""
    account_id_key = f"ACCOUNT#{caller_id}"
    response = tables.accounts.get_item(Key={"accountId": account_id_key}, ConsistentRead=True)

    if "Item" not in response:
        raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

    preferences = response["Item"].get("preferences", {})
    existing_methods = preferences.get("paymentMethods", [])
    updated_methods = []
    for m in existing_methods:
        method_copy = dict(m)
        if method_copy.get("name") == payment_method_name:
            method_copy["qrCodeUrl"] = None
        updated_methods.append(method_copy)

    preferences["paymentMethods"] = updated_methods
    tables.accounts.update_item(
        Key={"accountId": account_id_key},
        UpdateExpression="SET preferences = :prefs",
        ExpressionAttributeValues={":prefs": preferences},
    )


def delete_qr_code(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete QR code from S3 and clear qrCodeUrl in DynamoDB for a payment method.
    """
    logger = get_logger(__name__)

    try:
        caller_id = _extract_and_validate_caller(event)
        
        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()
        
        if not payment_method_name:
            raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")
        
        if is_reserved_name(payment_method_name):
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete QR for reserved methods")

        target = _verify_payment_method_exists(caller_id, payment_method_name)
        stored_qr_key = target.get("qrCodeUrl")
        
        _delete_qr_from_s3_storage(stored_qr_key, caller_id, payment_method_name, logger)
        _clear_qr_url_in_payment_method(caller_id, payment_method_name)

        logger.info("Deleted QR code", account_id=caller_id, payment_method=payment_method_name)
        return True

    except AppError:
        raise
    except Exception as e:  # pragma: no cover - generic catch
        logger.error("Failed to delete QR code", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete QR code")
