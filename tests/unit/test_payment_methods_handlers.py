"""
Unit tests for payment methods Lambda handlers.

Tests request_qr_upload, confirm_qr_upload, and generate_presigned_urls functions.
"""

import os
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.handlers.payment_methods_handlers import (
    confirm_qr_upload,
    delete_qr_code,
    request_qr_upload,
)
from src.utils.errors import AppError, ErrorCode
from src.utils.payment_methods import create_payment_method
from tests.unit.table_schemas import create_all_tables


@pytest.fixture
def aws_credentials() -> None:
    """Set fake AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["ACCOUNTS_TABLE_NAME"] = "kernelworx-accounts-ue1-dev"
    os.environ["EXPORTS_BUCKET"] = "test-exports-bucket"


@pytest.fixture
def dynamodb_tables(aws_credentials: None) -> Generator[Dict[str, Any], None, None]:
    """Create all mock DynamoDB tables."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        tables = create_all_tables(dynamodb)
        yield tables


@pytest.fixture
def s3_bucket(aws_credentials: None) -> Generator[Any, None, None]:
    """Create mock S3 bucket."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3.create_bucket(Bucket=bucket_name)
        yield s3


@pytest.fixture
def sample_account_id() -> str:
    """Sample account ID."""
    return "acc-123-456"


@pytest.fixture
def sample_account(dynamodb_tables: Dict[str, Any], sample_account_id: str) -> Dict[str, Any]:
    """Create a sample account in DynamoDB."""
    account_id_key = f"ACCOUNT#{sample_account_id}"
    account = {
        "accountId": account_id_key,
        "email": "test@example.com",
        "givenName": "Test",
        "familyName": "User",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }

    tables_dict = dynamodb_tables
    accounts_table = tables_dict["accounts"]
    accounts_table.put_item(Item=account)

    return account


class TestRequestQRUpload:
    """Test request_qr_upload Lambda handler."""

    def test_request_upload_success(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test successful pre-signed POST URL generation."""
        # Create a payment method
        create_payment_method(sample_account_id, "Venmo")

        # Create event
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo"},
        }

        # Request upload
        result = request_qr_upload(event, None)

        assert "uploadUrl" in result
        assert "fields" in result
        assert "s3Key" in result
        # UUID-based key: payment-qr-codes/{account_id}/{uuid}.png
        assert result["s3Key"].startswith(f"payment-qr-codes/{sample_account_id}/")
        assert result["s3Key"].endswith(".png")
        # Key should have a UUID component (32 hex chars)
        key_parts = result["s3Key"].split("/")
        filename = key_parts[2]  # e.g., "abc123def456.png"
        assert len(filename.replace(".png", "")) == 32  # UUID hex is 32 chars
        assert isinstance(result["fields"], dict)

    def test_request_upload_reserved_name(self, dynamodb_tables: Dict[str, Any], sample_account_id: str) -> None:
        """Test request upload for reserved name (Cash)."""
        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Cash"}}

        with pytest.raises(AppError) as exc_info:
            request_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in exc_info.value.message.lower()

    def test_request_upload_nonexistent_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test request upload for nonexistent payment method."""
        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Zelle"}}

        with pytest.raises(AppError) as exc_info:
            request_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_request_upload_unauthenticated(self) -> None:
        """Test request upload without authentication."""
        event = {"identity": {}, "arguments": {"paymentMethodName": "Venmo"}}

        with pytest.raises(AppError) as exc_info:
            request_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_request_upload_empty_name(self, sample_account_id: str) -> None:
        """Test request upload with empty name."""
        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": ""}}

        with pytest.raises(AppError) as exc_info:
            request_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestConfirmQRUpload:
    """Test confirm_qr_upload Lambda handler."""

    def test_confirm_upload_success(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test successful QR code upload confirmation."""
        # Create a payment method
        create_payment_method(sample_account_id, "Venmo")

        # Upload a file to S3
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        # Create event
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
        }

        # Confirm upload
        result = confirm_qr_upload(event, None)

        assert result["name"] == "Venmo"
        assert result["qrCodeUrl"] is not None
        assert result["qrCodeUrl"].startswith("http")  # Pre-signed URL

    def test_confirm_upload_nonexistent_s3_object(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test confirm upload with nonexistent S3 object."""
        # Create a payment method
        create_payment_method(sample_account_id, "Venmo")

        # Create event with non-existent S3 key
        s3_key = f"payment-qr-codes/{sample_account_id}/nonexistent.png"
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "upload not found" in exc_info.value.message.lower()

    def test_confirm_upload_nonexistent_method(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test confirm upload for nonexistent payment method."""
        # Upload a file to S3
        s3_key = f"payment-qr-codes/{sample_account_id}/zelle.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        # Create event
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Zelle", "s3Key": s3_key},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_confirm_upload_account_not_exists(self, dynamodb_tables: Dict[str, Any], s3_bucket: Any) -> None:
        """Test confirm upload when account doesn't exist in DynamoDB."""
        from src.handlers.payment_methods_handlers import confirm_qr_upload

        # Upload a file to S3 for a non-existent account
        fake_account_id = "nonexistent-account"
        s3_key = f"payment-qr-codes/{fake_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        # Create event
        event = {
            "identity": {"sub": fake_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_confirm_upload_unauthenticated(self) -> None:
        """Test confirm upload without authentication."""
        event = {
            "identity": {},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": "payment-qr-codes/acc/venmo.png"},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_confirm_upload_empty_parameters(self, sample_account_id: str) -> None:
        """Test confirm upload with empty parameters."""
        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "", "s3Key": ""}}

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_confirm_upload_wrong_account_s3_key(self, sample_account_id: str) -> None:
        """Test confirm upload with s3_key belonging to another account - security check."""
        # s3_key points to different account's folder
        other_account_id = "other-user-12345"
        s3_key = f"payment-qr-codes/{other_account_id}/venmo.png"

        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert "access denied" in exc_info.value.message.lower()

    def test_confirm_upload_malformed_s3_key(self, sample_account_id: str) -> None:
        """Test confirm upload with malformed s3_key - security check."""
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": "malformed/key.png"},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.FORBIDDEN


class TestGeneratePresignedURLs:
    """Test generate_presigned_urls Lambda handler."""

    def test_generate_urls_success(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test successful pre-signed URL generation for multiple methods."""
        # Create payment methods
        create_payment_method(sample_account_id, "Venmo")
        create_payment_method(sample_account_id, "PayPal")

        # Upload QR for Venmo
        s3_key_venmo = f"payment-qr-codes/{sample_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key_venmo, Body=b"fake-qr-data")

        # Update Venmo with S3 key
        from src.utils.dynamodb import tables

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = s3_key_venmo

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Create event
        event = {
            "prev": {
                "result": {
                    "paymentMethods": [
                        {"name": "Venmo", "qrCodeUrl": s3_key_venmo},
                        {"name": "PayPal", "qrCodeUrl": None},
                    ],
                    "ownerAccountId": sample_account_id,
                }
            }
        }

        # Generate URLs
        result = generate_presigned_urls(event, None)

        assert "paymentMethods" in result
        assert len(result["paymentMethods"]) == 2

        # Venmo should have pre-signed URL
        venmo = next(m for m in result["paymentMethods"] if m["name"] == "Venmo")
        assert venmo["qrCodeUrl"] is not None
        assert venmo["qrCodeUrl"].startswith("http")

        # PayPal should have None
        paypal = next(m for m in result["paymentMethods"] if m["name"] == "PayPal")
        assert paypal["qrCodeUrl"] is None

    def test_generate_urls_missing_owner_id(self) -> None:
        """Test generate URLs without owner account ID."""
        event = {"prev": {"result": {"paymentMethods": []}}}

        with pytest.raises(AppError) as exc_info:
            generate_presigned_urls(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "owner account id" in exc_info.value.message.lower()

    def test_generate_urls_empty_methods(self, sample_account_id: str) -> None:
        """Test generate URLs with empty payment methods list."""
        event = {"prev": {"result": {"paymentMethods": [], "ownerAccountId": sample_account_id}}}

        result = generate_presigned_urls(event, None)

        assert result["paymentMethods"] == []
        assert result["ownerAccountId"] == sample_account_id

    def test_generate_urls_exception_handling(self, sample_account_id: str) -> None:
        """Test generic exception handling in generate_presigned_urls."""
        # Pass invalid event structure to trigger exception
        event = {"prev": {"result": None}}

        with pytest.raises(AppError) as exc_info:
            generate_presigned_urls(event, None)
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestDeleteQRCode:
    """Test delete_qr_code Lambda handler."""

    def test_delete_qr_success(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test successful QR code deletion."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        # Create payment method
        create_payment_method(sample_account_id, "Venmo")

        # Upload QR code
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        # Update payment method with QR
        from src.utils.dynamodb import tables

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = s3_key

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Delete QR code
        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Venmo"}}

        result = delete_qr_code(event, None)

        assert result is True

        # Verify QR code was removed from S3
        with pytest.raises(ClientError):
            s3_bucket.head_object(Bucket=bucket_name, Key=s3_key)

    def test_delete_qr_no_qr_exists(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting QR when payment method has no QR code (idempotent)."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        # Create payment method without QR
        create_payment_method(sample_account_id, "Venmo")

        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Venmo"}}

        # Should succeed (idempotent) - no error even if QR doesn't exist
        result = delete_qr_code(event, None)
        assert result is True

    def test_delete_qr_reserved_name(self, sample_account_id: str) -> None:
        """Test deleting QR for reserved name."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Cash"}}

        with pytest.raises(AppError) as exc_info:
            delete_qr_code(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in exc_info.value.message.lower()

    def test_delete_qr_nonexistent_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting QR for nonexistent payment method."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Zelle"}}

        with pytest.raises(AppError) as exc_info:
            delete_qr_code(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_delete_qr_account_not_exists(self, dynamodb_tables: Dict[str, Any]) -> None:
        """Test deleting QR when account doesn't exist in DynamoDB."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        fake_account_id = "nonexistent-account"
        event = {"identity": {"sub": fake_account_id}, "arguments": {"paymentMethodName": "Venmo"}}

        with pytest.raises(AppError) as exc_info:
            delete_qr_code(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_delete_qr_unauthenticated(self) -> None:
        """Test deleting QR without authentication."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        event = {"identity": {}, "arguments": {"paymentMethodName": "Venmo"}}

        with pytest.raises(AppError) as exc_info:
            delete_qr_code(event, None)
        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_delete_qr_empty_name(self, sample_account_id: str) -> None:
        """Test deleting QR with empty name."""
        from src.handlers.payment_methods_handlers import delete_qr_code

        event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": ""}}

        with pytest.raises(AppError) as exc_info:
            delete_qr_code(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestExceptionHandling:
    """Test exception handling in all handlers."""

    def test_request_qr_upload_generic_exception(self, sample_account_id: str) -> None:
        """Test generic exception handling in request_qr_upload."""
        with patch("boto3.client") as mock_client:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_post.side_effect = Exception("Unexpected S3 error")
            mock_client.return_value = mock_s3

            with patch("src.handlers.payment_methods_handlers.get_payment_methods", return_value=[{"name": "Venmo"}]):
                event = {"identity": {"sub": sample_account_id}, "arguments": {"paymentMethodName": "Venmo"}}

                with pytest.raises(AppError) as exc_info:
                    request_qr_upload(event, None)
                assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_confirm_qr_upload_generic_exception(self, sample_account_id: str) -> None:
        """Test generic exception handling in confirm_qr_upload."""
        # Use correct s3_key format that matches the caller's account
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"

        with patch("boto3.client") as mock_client:
            mock_s3 = MagicMock()
            mock_s3.head_object.side_effect = Exception("Unexpected S3 error")
            mock_client.return_value = mock_s3

            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
            }

            with pytest.raises(AppError) as exc_info:
                confirm_qr_upload(event, None)
            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_confirm_qr_upload_s3_client_error_non_404(self, sample_account_id: str) -> None:
        """Test S3 ClientError that is not 404 (re-raise path)."""
        # Use correct s3_key format that matches the caller's account
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"

        with patch("boto3.client") as mock_client:
            mock_s3 = MagicMock()
            error_response = {"Error": {"Code": "403", "Message": "Forbidden"}}
            mock_s3.head_object.side_effect = ClientError(error_response, "HeadObject")
            mock_client.return_value = mock_s3

            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
            }

            with pytest.raises(AppError) as exc_info:
                confirm_qr_upload(event, None)
            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_delete_qr_account_deleted_after_s3_delete(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_qr_code when account is deleted after S3 deletion."""
        from src.utils.dynamodb import tables

        # Create payment method with QR
        create_payment_method(sample_account_id, "Venmo")

        # Simulate QR exists in S3
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr")

        # Update method with QR
        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = s3_key

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Mock delete_qr_by_key to succeed, then delete account (simulates race condition)
        with patch("src.handlers.payment_methods_handlers.delete_qr_by_key") as mock_delete:
            mock_delete.side_effect = lambda *args: tables.accounts.delete_item(Key={"accountId": account_id_key})

            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo"},
            }

            with pytest.raises(AppError) as exc_info:
                delete_qr_code(event, None)
            assert exc_info.value.error_code == ErrorCode.NOT_FOUND
            assert "not found" in str(exc_info.value)

    def test_generate_urls_method_without_qr_url_field(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test generate_presigned_urls with method missing qrCodeUrl field entirely."""
        # Create event with method that has no qrCodeUrl field at all
        event = {
            "prev": {
                "result": {
                    "paymentMethods": [
                        {"name": "Venmo"},  # No qrCodeUrl field
                    ],
                    "ownerAccountId": sample_account_id,
                }
            }
        }

        result = generate_presigned_urls(event, None)

        assert "paymentMethods" in result
        assert len(result["paymentMethods"]) == 1
        assert result["paymentMethods"][0]["qrCodeUrl"] is None

    def test_generate_urls_method_with_http_url(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test generate_presigned_urls with method already having http URL (passthrough)."""
        # Create event with method that already has an HTTP URL (shouldn't regenerate)
        existing_url = "https://example.com/existing-qr.png"
        event = {
            "prev": {
                "result": {
                    "paymentMethods": [
                        {"name": "Venmo", "qrCodeUrl": existing_url},
                    ],
                    "ownerAccountId": sample_account_id,
                }
            }
        }

        result = generate_presigned_urls(event, None)

        assert "paymentMethods" in result
        assert len(result["paymentMethods"]) == 1
        # Should keep existing URL unchanged
        assert result["paymentMethods"][0]["qrCodeUrl"] == existing_url

    def test_confirm_upload_method_not_found_in_loop(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test confirm_qr_upload when method name doesn't match any existing methods."""
        # Create a different payment method
        create_payment_method(sample_account_id, "PayPal")

        # Create S3 object
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        # Try to confirm upload for non-existent method
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo", "s3Key": s3_key},
        }

        with pytest.raises(AppError) as exc_info:
            confirm_qr_upload(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in str(exc_info.value)

    def test_delete_qr_method_not_found_in_loop(
        self, dynamodb_tables: Dict[str, Any], s3_bucket: Any, sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_qr_code with multiple methods (exercises else branch of name match)."""
        # Create TWO payment methods: one with QR that we'll delete, one without
        create_payment_method(sample_account_id, "Venmo")
        create_payment_method(sample_account_id, "PayPal")

        # Add QR to Venmo only
        from src.utils.dynamodb import tables

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        s3_key_venmo = f"payment-qr-codes/{sample_account_id}/venmo.png"
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = s3_key_venmo

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Create S3 object for Venmo
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key_venmo, Body=b"fake-qr-data")

        # Delete QR from Venmo - this will iterate over both Venmo and PayPal
        # Venmo matches the if condition, PayPal doesn't (exercises else branch)
        event = {
            "identity": {"sub": sample_account_id},
            "arguments": {"paymentMethodName": "Venmo"},
        }

        result = delete_qr_code(event, None)
        assert result is True

        # Verify Venmo's QR was cleared
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        venmo = next(m for m in methods if m["name"] == "Venmo")
        assert venmo.get("qrCodeUrl") is None

    def test_delete_qr_s3_delete_fails(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_qr_code when S3 delete fails (exercises exception handling)."""
        from unittest.mock import patch

        from src.handlers.payment_methods_handlers import delete_qr_code
        from src.utils.dynamodb import tables

        # Create payment method with QR
        create_payment_method(sample_account_id, "Venmo")

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = s3_key

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Mock delete_qr_by_key to fail (new UUID-based path)
        with patch("src.handlers.payment_methods_handlers.delete_qr_by_key", side_effect=Exception("S3 error")):
            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo"},
            }
            # Should still succeed despite S3 error (idempotent, logs warning)
            result = delete_qr_code(event, None)
            assert result is True

        # Verify QR was still cleared in DynamoDB
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        venmo = next(m for m in methods if m["name"] == "Venmo")
        assert venmo.get("qrCodeUrl") is None

    def test_delete_qr_legacy_http_url(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_qr_code with legacy HTTP URL (fallback to delete_qr_from_s3)."""
        from unittest.mock import patch

        from src.handlers.payment_methods_handlers import delete_qr_code
        from src.utils.dynamodb import tables

        # Create payment method with legacy HTTP URL
        create_payment_method(sample_account_id, "Venmo")

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        # Legacy format: HTTP URL instead of S3 key
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = "https://dev.kernelworx.app/payment-qr-codes/acc-123/venmo.png"

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Mock delete_qr_from_s3 (legacy fallback)
        with patch("src.handlers.payment_methods_handlers.delete_qr_from_s3") as mock_delete:
            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo"},
            }
            result = delete_qr_code(event, None)
            assert result is True
            # Verify legacy delete was called
            mock_delete.assert_called_once_with(sample_account_id, "Venmo")

    def test_delete_qr_legacy_http_url_s3_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_qr_code with legacy HTTP URL when S3 delete fails."""
        from unittest.mock import patch

        from src.handlers.payment_methods_handlers import delete_qr_code
        from src.utils.dynamodb import tables

        # Create payment method with legacy HTTP URL
        create_payment_method(sample_account_id, "Venmo")

        account_id_key = f"ACCOUNT#{sample_account_id}"
        response = tables.accounts.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        # Legacy format: HTTP URL instead of S3 key
        for m in methods:
            if m["name"] == "Venmo":
                m["qrCodeUrl"] = "https://dev.kernelworx.app/payment-qr-codes/acc-123/venmo.png"

        # Store preferences properly
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Mock delete_qr_from_s3 to raise an exception
        with patch(
            "src.handlers.payment_methods_handlers.delete_qr_from_s3", side_effect=Exception("S3 delete failed")
        ):
            event = {
                "identity": {"sub": sample_account_id},
                "arguments": {"paymentMethodName": "Venmo"},
            }
            # Should still succeed (S3 delete failure is logged but not raised)
            result = delete_qr_code(event, None)
            assert result is True
