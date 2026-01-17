"""
Payment methods Lambda handlers for AppSync resolvers.

These handlers provide S3 pre-signed URL generation for QR code uploads
and confirmations. They integrate with AppSync pipeline resolvers.
"""

import json
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
        generate_presigned_get_url,
        generate_qr_code_s3_key,
        get_payment_methods,
        get_qr_code_s3_key,
        is_reserved_name,
        slugify,
        update_payment_method,
        validate_qr_s3_key,
    )
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import get_required_env, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.payment_methods import (
        delete_qr_by_key,
        delete_qr_from_s3,
        generate_presigned_get_url,
        generate_qr_code_s3_key,
        get_payment_methods,
        get_qr_code_s3_key,
        is_reserved_name,
        slugify,
        update_payment_method,
        validate_qr_s3_key,
    )


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
        # Extract caller identity
        identity = event.get("identity", {})
        caller_id = identity.get("sub")

        if not caller_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

        # Extract arguments
        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()

        if not payment_method_name:
            raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")

        # Validate not reserved
        if is_reserved_name(payment_method_name):
            raise AppError(
                ErrorCode.INVALID_INPUT, f"Cannot upload QR code for reserved method '{payment_method_name}'"
            )

        # Verify payment method exists
        methods = get_payment_methods(caller_id)
        method_exists = any(m.get("name") == payment_method_name for m in methods)

        if not method_exists:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

        # Generate UUID-based S3 key to avoid collisions from similar payment method names
        s3_key = generate_qr_code_s3_key(caller_id, "png")

        # Generate pre-signed POST URL (must use direct S3, not CloudFront)
        # CloudFront vanity domain is only used for downloads (GET), not uploads (POST)
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


def confirm_qr_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:  # noqa: C901
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
        # Extract caller identity
        identity = event.get("identity", {})
        caller_id = identity.get("sub")

        if not caller_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

        # Extract arguments
        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()
        s3_key = arguments.get("s3Key", "").strip()

        if not payment_method_name or not s3_key:
            raise AppError(ErrorCode.INVALID_INPUT, "Payment method name and s3Key are required")

        # Security: Validate s3_key belongs to this caller's account
        # Prevents users from claiming QR codes they don't own
        if not validate_qr_s3_key(s3_key, caller_id):
            raise AppError(ErrorCode.FORBIDDEN, "Invalid S3 key - access denied")

        # Validate S3 object exists
        bucket_name = get_required_env("EXPORTS_BUCKET")
        s3_client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))

        try:
            s3_client.head_object(Bucket=bucket_name, Key=s3_key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                raise AppError(ErrorCode.NOT_FOUND, "Upload not found. Please upload the file first.")
            raise

        # Update DynamoDB with s3_key (store in qrCodeUrl field temporarily)
        # Note: The actual pre-signed URL will be generated on read
        # For now, we'll update the payment method record to indicate QR exists
        account_id_key = f"ACCOUNT#{caller_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

        if "Item" not in response:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

        existing_methods = response["Item"].get("preferences", {}).get("paymentMethods", [])

        # Find and update method
        method_updated = None
        for method in existing_methods:
            if method.get("name") == payment_method_name:
                method["qrCodeUrl"] = s3_key  # Store S3 key, not URL
                method_updated = method
                break

        if not method_updated:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

        # Save updated methods
        preferences = response.get("Item", {}).get("preferences", {})
        preferences["paymentMethods"] = existing_methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Generate pre-signed GET URL
        presigned_url = generate_presigned_get_url(caller_id, payment_method_name, s3_key, expiry_seconds=900)

        logger.info(
            "Confirmed QR code upload",
            account_id=caller_id,
            payment_method=payment_method_name,
            s3_key=s3_key,
        )

        return {"name": payment_method_name, "qrCodeUrl": presigned_url}

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to confirm QR code upload", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to confirm upload")


def delete_qr_code(event: Dict[str, Any], context: Any) -> bool:  # noqa: C901
    """
    Delete QR code from S3 and clear qrCodeUrl in DynamoDB for a payment method.
    """
    logger = get_logger(__name__)

    try:
        identity = event.get("identity", {})
        caller_id = identity.get("sub")
        if not caller_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

        arguments = event.get("arguments", {})
        payment_method_name = arguments.get("paymentMethodName", "").strip()
        if not payment_method_name:
            raise AppError(ErrorCode.INVALID_INPUT, "Payment method name is required")

        if is_reserved_name(payment_method_name):
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete QR for reserved methods")

        methods = get_payment_methods(caller_id)
        target = next((m for m in methods if m.get("name") == payment_method_name), None)
        if not target:
            raise AppError(ErrorCode.NOT_FOUND, f"Payment method '{payment_method_name}' not found")

        # Get the stored s3_key from the payment method (if it exists)
        stored_qr_key = target.get("qrCodeUrl")

        # Delete QR from S3 using the stored key (if it's a valid s3 path, not a URL)
        if stored_qr_key and stored_qr_key.startswith("payment-qr-codes/"):
            try:
                delete_qr_by_key(stored_qr_key)
            except Exception as e:
                # S3 delete is idempotent - if object doesn't exist, that's fine
                logger.info("S3 delete completed (object may not have existed)", error=str(e))
        elif stored_qr_key:
            # Fallback: Legacy slug-based key or HTTP URL - try the old method
            try:
                delete_qr_from_s3(caller_id, payment_method_name)
            except Exception as e:
                logger.info("S3 delete completed (object may not have existed)", error=str(e))

        # Update payment method to clear QR code URL
        account_id_key = f"ACCOUNT#{caller_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})

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

        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = updated_methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        logger.info("Deleted QR code", account_id=caller_id, payment_method=payment_method_name)
        return True

    except AppError:
        raise
    except Exception as e:  # pragma: no cover - generic catch
        logger.error("Failed to delete QR code", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete QR code")
