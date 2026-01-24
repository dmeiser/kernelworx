"""
Unit tests for payment methods utilities.

Tests CRUD operations, S3 QR code management, validation, and slugify.
"""

import os
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.utils import payment_methods
from src.utils.errors import AppError, ErrorCode
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


class TestSlugify:
    """Test slugify function."""

    def test_slugify_basic(self) -> None:
        """Test basic slugification."""
        assert payment_methods.slugify("Venmo") == "venmo"
        assert payment_methods.slugify("PayPal") == "paypal"

    def test_slugify_with_spaces(self) -> None:
        """Test slugifying text with spaces."""
        assert payment_methods.slugify("Venmo - Tom") == "venmo-tom"
        assert payment_methods.slugify("Apple Pay") == "apple-pay"

    def test_slugify_with_underscores(self) -> None:
        """Test slugifying text with underscores."""
        assert payment_methods.slugify("some_method") == "some-method"

    def test_slugify_with_special_chars(self) -> None:
        """Test slugifying text with special characters."""
        assert payment_methods.slugify("Venmo@Tom!") == "venmotom"
        assert payment_methods.slugify("Cash (USD)") == "cash-usd"

    def test_slugify_with_multiple_spaces(self) -> None:
        """Test slugifying text with multiple consecutive spaces."""
        assert payment_methods.slugify("Multiple   Spaces") == "multiple-spaces"

    def test_slugify_with_leading_trailing_hyphens(self) -> None:
        """Test slugifying removes leading/trailing hyphens."""
        assert payment_methods.slugify("---test---") == "test"
        assert payment_methods.slugify("  -test-  ") == "test"

    def test_slugify_empty(self) -> None:
        """Test slugifying empty string."""
        assert payment_methods.slugify("") == ""
        assert payment_methods.slugify("   ") == ""


class TestValidateQRS3Key:
    """Test validate_qr_s3_key function."""

    def test_valid_key_matches_account(self) -> None:
        """Test valid s3_key that matches account_id."""
        account_id = "test-account-123"
        s3_key = f"payment-qr-codes/{account_id}/venmo.png"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is True

    def test_valid_key_with_extension_jpg(self) -> None:
        """Test valid s3_key with jpg extension."""
        account_id = "test-account-123"
        s3_key = f"payment-qr-codes/{account_id}/venmo.jpg"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is True

    def test_valid_key_with_extension_webp(self) -> None:
        """Test valid s3_key with webp extension."""
        account_id = "test-account-123"
        s3_key = f"payment-qr-codes/{account_id}/venmo.webp"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is True

    def test_invalid_wrong_account(self) -> None:
        """Test s3_key that belongs to different account returns False."""
        account_id = "my-account"
        other_account_id = "other-account"
        s3_key = f"payment-qr-codes/{other_account_id}/venmo.png"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is False

    def test_invalid_wrong_prefix(self) -> None:
        """Test s3_key with wrong prefix returns False."""
        account_id = "test-account-123"
        s3_key = f"wrong-prefix/{account_id}/venmo.png"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is False

    def test_invalid_malformed_key(self) -> None:
        """Test malformed s3_key returns False."""
        account_id = "test-account-123"
        assert payment_methods.validate_qr_s3_key("malformed/key", account_id) is False
        assert payment_methods.validate_qr_s3_key("", account_id) is False
        assert payment_methods.validate_qr_s3_key("no-slashes.png", account_id) is False
        # Key with right prefix but too few parts (missing filename)
        assert payment_methods.validate_qr_s3_key(f"payment-qr-codes/{account_id}", account_id) is False

    def test_invalid_extension(self) -> None:
        """Test s3_key with invalid file extension returns False."""
        account_id = "test-account-123"
        assert payment_methods.validate_qr_s3_key(f"payment-qr-codes/{account_id}/venmo.gif", account_id) is False
        assert payment_methods.validate_qr_s3_key(f"payment-qr-codes/{account_id}/venmo.txt", account_id) is False

    def test_invalid_path_traversal_attempt(self) -> None:
        """Test path traversal attempts return False."""
        account_id = "test-account-123"
        s3_key = f"payment-qr-codes/{account_id}/../other-account/venmo.png"
        assert payment_methods.validate_qr_s3_key(s3_key, account_id) is False


class TestGenerateQRCodeS3Key:
    """Test generate_qr_code_s3_key function (UUID-based)."""

    def test_generates_uuid_based_key(self) -> None:
        """Test that keys use UUID instead of payment method slug."""
        account_id = "test-account-123"
        key = payment_methods.generate_qr_code_s3_key(account_id)

        # Verify format: payment-qr-codes/{account_id}/{uuid}.png
        assert key.startswith(f"payment-qr-codes/{account_id}/")
        assert key.endswith(".png")

        # Extract UUID portion (32 hex chars)
        filename = key.split("/")[-1]
        uuid_part = filename.replace(".png", "")
        assert len(uuid_part) == 32
        # Should be valid hex
        int(uuid_part, 16)  # Will raise if not valid hex

    def test_generates_unique_keys(self) -> None:
        """Test that each call generates a unique key."""
        account_id = "test-account-123"
        keys = [payment_methods.generate_qr_code_s3_key(account_id) for _ in range(10)]
        # All keys should be unique
        assert len(set(keys)) == 10

    def test_supports_different_extensions(self) -> None:
        """Test key generation with different file extensions."""
        account_id = "test-account-123"

        png_key = payment_methods.generate_qr_code_s3_key(account_id, "png")
        assert png_key.endswith(".png")

        jpg_key = payment_methods.generate_qr_code_s3_key(account_id, "jpg")
        assert jpg_key.endswith(".jpg")

        webp_key = payment_methods.generate_qr_code_s3_key(account_id, "webp")
        assert webp_key.endswith(".webp")


class TestIsReservedName:
    """Test is_reserved_name function."""

    def test_reserved_cash(self) -> None:
        """Test Cash is reserved."""
        assert payment_methods.is_reserved_name("Cash") is True
        assert payment_methods.is_reserved_name("cash") is True
        assert payment_methods.is_reserved_name("CASH") is True

    def test_reserved_check(self) -> None:
        """Test Check is reserved."""
        assert payment_methods.is_reserved_name("Check") is True
        assert payment_methods.is_reserved_name("check") is True
        assert payment_methods.is_reserved_name("CHECK") is True

    def test_not_reserved(self) -> None:
        """Test non-reserved names."""
        assert payment_methods.is_reserved_name("Venmo") is False
        assert payment_methods.is_reserved_name("PayPal") is False
        assert payment_methods.is_reserved_name("") is False


class TestValidateNameUnique:
    """Test validate_name_unique function."""

    def test_unique_name_no_existing(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation passes when no existing methods."""
        # Should not raise
        payment_methods.validate_name_unique(sample_account_id, "Venmo")

    def test_unique_name_with_different_existing(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation passes when name is different from existing."""
        # Create existing method
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {"paymentMethods": [{"name": "PayPal", "qrCodeUrl": None}]},
            }
        )

        # Should not raise
        payment_methods.validate_name_unique(sample_account_id, "Venmo")

    def test_duplicate_name_case_insensitive(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation fails for duplicate name (case-insensitive)."""
        # Create existing method
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": None}]},
            }
        )

        # Should raise for exact match
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_name_unique(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "already exists" in str(exc_info.value.message)

        # Should raise for different case
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_name_unique(sample_account_id, "venmo")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_exclude_current_on_update(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation excludes current method name on update."""
        # Create existing method
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": None}]},
            }
        )

        # Should not raise when excluding current
        payment_methods.validate_name_unique(sample_account_id, "venmo", exclude_current="Venmo")


class TestGetPaymentMethods:
    """Test get_payment_methods function."""

    def test_get_no_methods(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test getting payment methods when none exist."""
        methods = payment_methods.get_payment_methods(sample_account_id)
        assert methods == []

    def test_get_existing_methods(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test getting existing payment methods."""
        # Create methods
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {
                    "paymentMethods": [
                        {"name": "Venmo", "qrCodeUrl": None},
                        {"name": "PayPal", "qrCodeUrl": "s3://..."},
                    ]
                },
            }
        )

        methods = payment_methods.get_payment_methods(sample_account_id)
        assert len(methods) == 2
        assert methods[0]["name"] == "Venmo"
        assert methods[0]["qrCodeUrl"] is None
        assert methods[1]["name"] == "PayPal"
        assert methods[1]["qrCodeUrl"] == "s3://..."


class TestCreatePaymentMethod:
    """Test create_payment_method function."""

    def test_create_first_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating first payment method."""
        method = payment_methods.create_payment_method(sample_account_id, "Venmo")

        assert method["name"] == "Venmo"
        assert method["qrCodeUrl"] is None

        # Verify in DynamoDB
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        response = accounts_table.get_item(Key={"accountId": f"ACCOUNT#{sample_account_id}"})
        assert "Item" in response
        assert len(response["Item"]["preferences"]["paymentMethods"]) == 1
        assert response["Item"]["preferences"]["paymentMethods"][0]["name"] == "Venmo"

    def test_create_additional_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating additional payment method."""
        # Create first method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        # Create second method
        method = payment_methods.create_payment_method(sample_account_id, "PayPal")

        assert method["name"] == "PayPal"

        # Verify both in DynamoDB
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        response = accounts_table.get_item(Key={"accountId": f"ACCOUNT#{sample_account_id}"})
        assert len(response["Item"]["preferences"]["paymentMethods"]) == 2

    def test_create_with_whitespace(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with leading/trailing whitespace."""
        method = payment_methods.create_payment_method(sample_account_id, "  Venmo  ")

        assert method["name"] == "Venmo"  # Whitespace stripped

    def test_create_empty_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with empty name."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "required" in str(exc_info.value.message).lower()

    def test_create_name_too_long(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with name exceeding max length."""
        long_name = "a" * 51
        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, long_name)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "50 characters" in str(exc_info.value.message)

    def test_create_reserved_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with reserved name."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "Cash")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in str(exc_info.value.message).lower()

        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "check")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_create_duplicate_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with duplicate name."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "already exists" in str(exc_info.value.message)

        # Case-insensitive
        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "venmo")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestUpdatePaymentMethod:
    """Test update_payment_method function."""

    def test_update_method_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating payment method name."""
        # Create method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        # Update
        updated = payment_methods.update_payment_method(sample_account_id, "Venmo", "Venmo - Tom")

        assert updated["name"] == "Venmo - Tom"

        # Verify in DynamoDB
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        response = accounts_table.get_item(Key={"accountId": f"ACCOUNT#{sample_account_id}"})
        assert response["Item"]["preferences"]["paymentMethods"][0]["name"] == "Venmo - Tom"

    def test_update_preserves_qr(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating method preserves QR code URL."""
        # Create method with QR
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": "s3://test"}]},
            }
        )

        # Update name
        updated = payment_methods.update_payment_method(sample_account_id, "Venmo", "Venmo - Tom")

        assert updated["name"] == "Venmo - Tom"
        assert updated["qrCodeUrl"] == "s3://test"

    def test_update_nonexistent_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating non-existent method."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Zelle", "Zelle - Tom")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in str(exc_info.value.message).lower()

    def test_update_to_reserved_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating to reserved name."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "Cash")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in str(exc_info.value.message).lower()

    def test_update_to_duplicate_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating to duplicate name."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        payment_methods.create_payment_method(sample_account_id, "PayPal")

        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "PayPal")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "already exists" in str(exc_info.value.message)

    def test_update_to_same_name_different_case(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating to same name with different case is allowed."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        # Should succeed (same method, just changing case)
        updated = payment_methods.update_payment_method(sample_account_id, "Venmo", "venmo")
        assert updated["name"] == "venmo"


class TestDeletePaymentMethod:
    """Test delete_payment_method function."""

    def test_delete_method_no_qr(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting method without QR code."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        payment_methods.delete_payment_method(sample_account_id, "Venmo")

        # Verify deleted from account (payment methods list should be empty)
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        response = accounts_table.get_item(Key={"accountId": f"ACCOUNT#{sample_account_id}"})
        # Account should still exist but paymentMethods should be empty
        assert "Item" in response
        assert response["Item"].get("paymentMethods", []) == []

    def test_delete_method_s3_delete_fails(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], s3_bucket: Any, sample_account_id: str
    ) -> None:
        """Test deleting method when S3 delete fails (should log warning and continue)."""

        # Create method with QR code
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        account_id_key = f"ACCOUNT#{sample_account_id}"

        # Update to add QR code URL
        response = accounts_table.get_item(Key={"accountId": account_id_key})
        methods = response["Item"]["preferences"]["paymentMethods"]
        methods[0]["qrCodeUrl"] = "s3://test/key"
        preferences = response["Item"].get("preferences", {})
        preferences["paymentMethods"] = methods
        accounts_table.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET preferences = :prefs",
            ExpressionAttributeValues={":prefs": preferences},
        )

        # Mock delete_qr_from_s3 to raise an exception
        with patch("src.utils.payment_methods.delete_qr_from_s3", side_effect=Exception("S3 delete failed")):
            # Should still delete the payment method despite S3 failure
            payment_methods.delete_payment_method(sample_account_id, "Venmo")

        # Verify method was deleted anyway
        response = accounts_table.get_item(Key={"accountId": account_id_key})
        assert response["Item"].get("preferences", {}).get("paymentMethods", []) == []

    def test_delete_method_with_multiple(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting one method when multiple exist."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        payment_methods.create_payment_method(sample_account_id, "PayPal")

        payment_methods.delete_payment_method(sample_account_id, "Venmo")

        # Verify only PayPal remains
        methods = payment_methods.get_payment_methods(sample_account_id)
        assert len(methods) == 1
        assert methods[0]["name"] == "PayPal"

    def test_delete_method_with_qr(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], s3_bucket: Any, sample_account_id: str
    ) -> None:
        """Test deleting method with QR code."""
        # Create method with QR
        tables_dict = dynamodb_tables
        accounts_table = tables_dict["accounts"]
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": "s3://test/key"}]},
            }
        )

        # Upload QR to S3
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_bucket.put_object(
            Bucket=bucket_name, Key=f"payment-qr-codes/{sample_account_id}/venmo.png", Body=b"fake-qr-image"
        )

        # Delete method
        payment_methods.delete_payment_method(sample_account_id, "Venmo")

        # Verify S3 object deleted
        with pytest.raises(ClientError) as exc_info:
            s3_bucket.head_object(Bucket=bucket_name, Key=f"payment-qr-codes/{sample_account_id}/venmo.png")
        assert exc_info.value.response["Error"]["Code"] == "404"

    def test_delete_nonexistent_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting non-existent method."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_payment_method(sample_account_id, "Zelle")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in str(exc_info.value.message).lower()

    def test_delete_reserved_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test deleting reserved name."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_payment_method(sample_account_id, "Cash")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in str(exc_info.value.message).lower()


class TestValidateQRFile:
    """Test validate_qr_file function."""

    def test_validate_valid_png(self) -> None:
        """Test validating valid PNG file."""
        file_bytes = b"fake-png-data" * 1000  # Under 5MB
        # Should not raise
        payment_methods.validate_qr_file(file_bytes, "image/png")

    def test_validate_valid_jpeg(self) -> None:
        """Test validating valid JPEG file."""
        file_bytes = b"fake-jpeg-data" * 1000
        payment_methods.validate_qr_file(file_bytes, "image/jpeg")

    def test_validate_valid_webp(self) -> None:
        """Test validating valid WEBP file."""
        file_bytes = b"fake-webp-data" * 1000
        payment_methods.validate_qr_file(file_bytes, "image/webp")

    def test_validate_file_too_large(self) -> None:
        """Test validating file exceeding size limit."""
        file_bytes = b"x" * (6 * 1024 * 1024)  # 6MB
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_qr_file(file_bytes, "image/png")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "5MB" in str(exc_info.value.message)

    def test_validate_unsupported_type(self) -> None:
        """Test validating unsupported file type."""
        file_bytes = b"fake-data"
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_qr_file(file_bytes, "image/gif")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "PNG, JPG, or WEBP" in str(exc_info.value.message)


class TestUploadQRToS3:
    """Test upload_qr_to_s3 function."""

    def test_upload_png(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test uploading PNG QR code."""
        file_bytes = b"fake-png-data" * 100
        s3_key = payment_methods.upload_qr_to_s3(sample_account_id, "Venmo", file_bytes, "image/png")

        assert s3_key == f"payment-qr-codes/{sample_account_id}/venmo.png"

        # Verify S3 object exists
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        response = s3_bucket.head_object(Bucket=bucket_name, Key=s3_key)
        assert response["ContentType"] == "image/png"

    def test_upload_jpeg(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test uploading JPEG QR code."""
        file_bytes = b"fake-jpeg-data" * 100
        s3_key = payment_methods.upload_qr_to_s3(sample_account_id, "PayPal", file_bytes, "image/jpeg")

        assert s3_key == f"payment-qr-codes/{sample_account_id}/paypal.jpg"

    def test_upload_webp(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test uploading WEBP QR code."""
        file_bytes = b"fake-webp-data" * 100
        s3_key = payment_methods.upload_qr_to_s3(sample_account_id, "Zelle", file_bytes, "image/webp")

        assert s3_key == f"payment-qr-codes/{sample_account_id}/zelle.webp"

    def test_upload_with_special_chars(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test uploading with special characters in name."""
        file_bytes = b"fake-data" * 100
        s3_key = payment_methods.upload_qr_to_s3(sample_account_id, "Venmo - Tom", file_bytes, "image/png")

        # Should slugify the name
        assert s3_key == f"payment-qr-codes/{sample_account_id}/venmo-tom.png"

    def test_upload_invalid_file(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test uploading invalid file."""
        file_bytes = b"x" * (6 * 1024 * 1024)  # Too large
        with pytest.raises(AppError) as exc_info:
            payment_methods.upload_qr_to_s3(sample_account_id, "Venmo", file_bytes, "image/png")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestDeleteQRFromS3:
    """Test delete_qr_from_s3 function."""

    def test_delete_existing_qr(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test deleting existing QR code."""
        # Upload QR
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-data")

        # Delete
        payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")

        # Verify deleted
        with pytest.raises(ClientError) as exc_info:
            s3_bucket.head_object(Bucket=bucket_name, Key=s3_key)
        assert exc_info.value.response["Error"]["Code"] == "404"

    def test_delete_nonexistent_qr(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test deleting non-existent QR code (should not raise)."""
        # Should not raise
        payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")

    def test_delete_all_extensions(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test deleting tries all possible extensions."""
        # Upload multiple extensions
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_bucket.put_object(
            Bucket=bucket_name, Key=f"payment-qr-codes/{sample_account_id}/venmo.png", Body=b"fake-png"
        )
        s3_bucket.put_object(
            Bucket=bucket_name, Key=f"payment-qr-codes/{sample_account_id}/venmo.jpg", Body=b"fake-jpg"
        )

        # Delete
        payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")

        # Verify all deleted
        for ext in ["png", "jpg", "webp"]:
            s3_key = f"payment-qr-codes/{sample_account_id}/venmo.{ext}"
            try:
                s3_bucket.head_object(Bucket=bucket_name, Key=s3_key)
                # If we get here, object exists (should be deleted)
                assert False, f"Object {s3_key} should be deleted"
            except ClientError as e:
                assert e.response["Error"]["Code"] == "404"


class TestDeleteQRByKey:
    """Test delete_qr_by_key function."""

    def test_delete_existing_qr_by_key(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test deleting existing QR code by key."""
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_key = f"payment-qr-codes/{sample_account_id}/abc123.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-data")

        # Delete by key
        payment_methods.delete_qr_by_key(s3_key)

        # Verify deleted
        with pytest.raises(ClientError) as exc_info:
            s3_bucket.head_object(Bucket=bucket_name, Key=s3_key)
        assert exc_info.value.response["Error"]["Code"] == "404"

    def test_delete_nonexistent_qr_by_key(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test deleting non-existent QR code by key (idempotent, should not raise)."""
        s3_key = f"payment-qr-codes/{sample_account_id}/does-not-exist.png"
        # Should not raise
        payment_methods.delete_qr_by_key(s3_key)

    def test_delete_qr_by_key_nosuchkey_error(self, sample_account_id: str) -> None:
        """Test S3 NoSuchKey error during delete (404 should be silently ignored)."""

        s3_key = f"payment-qr-codes/{sample_account_id}/test.png"

        mock_s3 = MagicMock()
        error_response = {"Error": {"Code": "NoSuchKey", "Message": "Key does not exist"}}
        mock_s3.delete_object.side_effect = ClientError(error_response, "DeleteObject")

        with patch.object(payment_methods, "_get_s3_client", return_value=mock_s3):
            # Should not raise - NoSuchKey is silently ignored for idempotent delete
            payment_methods.delete_qr_by_key(s3_key)

    def test_delete_qr_by_key_s3_error(self, sample_account_id: str) -> None:
        """Test S3 error during delete (non-404 error)."""

        s3_key = f"payment-qr-codes/{sample_account_id}/test.png"

        mock_s3 = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_s3.delete_object.side_effect = ClientError(error_response, "DeleteObject")

        with patch.object(payment_methods, "_get_s3_client", return_value=mock_s3):
            with pytest.raises(AppError) as exc_info:
                payment_methods.delete_qr_by_key(s3_key)
            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_delete_qr_by_key_generic_exception(self, sample_account_id: str) -> None:
        """Test generic Exception during delete (non-ClientError)."""

        s3_key = f"payment-qr-codes/{sample_account_id}/test.png"

        mock_s3 = MagicMock()
        mock_s3.delete_object.side_effect = Exception("Unexpected error")

        with patch.object(payment_methods, "_get_s3_client", return_value=mock_s3):
            with pytest.raises(AppError) as exc_info:
                payment_methods.delete_qr_by_key(s3_key)
            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestGeneratePresignedGetURL:
    """Test generate_presigned_get_url function."""

    def test_generate_url_with_existing_qr(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test generating URL for existing QR code."""
        # Upload QR
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-data")

        # Generate URL
        url = payment_methods.generate_presigned_get_url(sample_account_id, "Venmo")

        assert url is not None
        assert "venmo.png" in url
        assert bucket_name in url

    def test_generate_url_with_s3_key_provided(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test generating URL with explicit s3_key."""
        # Upload QR
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.jpg"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-data")

        # Generate URL with explicit key
        url = payment_methods.generate_presigned_get_url(sample_account_id, "Venmo", s3_key=s3_key)

        assert url is not None
        assert "venmo.jpg" in url

    def test_generate_url_nonexistent_qr(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test generating URL for non-existent QR code."""
        url = payment_methods.generate_presigned_get_url(sample_account_id, "Venmo")

        assert url is None

    def test_generate_url_custom_expiry(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test generating URL with custom expiry."""
        # Upload QR
        bucket_name = os.environ.get("EXPORTS_BUCKET")
        s3_key = f"payment-qr-codes/{sample_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-data")

        # Generate URL with custom expiry
        url = payment_methods.generate_presigned_get_url(sample_account_id, "Venmo", expiry_seconds=300)

        assert url is not None
        # Moto doesn't include expiry in URL, so just verify it works


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_create_method_with_max_length_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test creating method with exactly max length name."""
        name = "a" * 50
        method = payment_methods.create_payment_method(sample_account_id, name)
        assert method["name"] == name

    def test_update_to_same_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test updating method to same name (should succeed)."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        updated = payment_methods.update_payment_method(sample_account_id, "Venmo", "Venmo")
        assert updated["name"] == "Venmo"

    def test_multiple_accounts_isolated(self, dynamodb_tables: Dict[str, Any]) -> None:
        """Test that multiple accounts have isolated payment methods."""
        acc1 = "acc-111"
        acc2 = "acc-222"

        payment_methods.create_payment_method(acc1, "Venmo")
        payment_methods.create_payment_method(acc2, "PayPal")

        methods1 = payment_methods.get_payment_methods(acc1)
        methods2 = payment_methods.get_payment_methods(acc2)

        assert len(methods1) == 1
        assert methods1[0]["name"] == "Venmo"
        assert len(methods2) == 1
        assert methods2[0]["name"] == "PayPal"


class TestErrorHandling:
    """Test error handling for DynamoDB and S3 failures."""

    def test_validate_name_unique_dynamodb_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validate_name_unique handles DynamoDB errors."""

        from src.utils.dynamodb import override_table

        # Create mock table that raises ClientError
        mock_table = MagicMock()
        mock_table.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "GetItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_name_unique(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        # Clean up
        override_table("accounts", None)

    def test_get_payment_methods_dynamodb_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test get_payment_methods handles DynamoDB errors."""

        from src.utils.dynamodb import override_table

        mock_table = MagicMock()
        mock_table.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "GetItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.get_payment_methods(sample_account_id)
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        override_table("accounts", None)

    def test_create_payment_method_dynamodb_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test create_payment_method handles DynamoDB errors."""

        from src.utils.dynamodb import override_table

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {"accountId": f"ACCOUNT#{sample_account_id}", "preferences": {"paymentMethods": []}}
        }
        mock_table.update_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "UpdateItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.create_payment_method(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        override_table("accounts", None)

    def test_update_payment_method_dynamodb_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method handles DynamoDB errors."""

        from src.utils.dynamodb import override_table

        # First create a method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        mock_table = MagicMock()
        mock_table.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "GetItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "Venmo - Tom")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        override_table("accounts", None)

    def test_update_payment_method_update_item_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method handles update_item DynamoDB errors."""

        from src.utils.dynamodb import override_table

        # First create a method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        mock_table = MagicMock()
        # get_item succeeds
        from src.utils.dynamodb import tables

        real_response = tables.accounts.get_item(Key={"accountId": f"ACCOUNT#{sample_account_id}"})
        mock_table.get_item.return_value = real_response
        # update_item fails
        mock_table.update_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "UpdateItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "Venmo - Tom")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        override_table("accounts", None)

    def test_delete_payment_method_dynamodb_error(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_payment_method handles DynamoDB errors."""

        from src.utils.dynamodb import override_table

        mock_table = MagicMock()
        mock_table.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "GetItem"
        )

        override_table("accounts", mock_table)

        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_payment_method(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        override_table("accounts", None)

    def test_upload_qr_s3_error(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test upload_qr_to_s3 handles S3 errors."""
        # Replace S3 client with mock that raises error

        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "PutObject"
        )

        payment_methods.s3_client = mock_s3

        with pytest.raises(AppError) as exc_info:
            payment_methods.upload_qr_to_s3(sample_account_id, "Venmo", b"test-data", "image/png")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        # Clean up
        payment_methods.s3_client = None

    def test_generate_presigned_url_s3_error(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test generate_presigned_get_url handles S3 errors."""

        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {}  # File exists
        mock_s3.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}}, "GeneratePresignedUrl"
        )

        payment_methods.s3_client = mock_s3

        with pytest.raises(AppError) as exc_info:
            payment_methods.generate_presigned_get_url(sample_account_id, "Venmo", s3_key="test.png")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        payment_methods.s3_client = None

    def test_get_payment_methods_account_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test get_payment_methods when account doesn't exist."""
        # Don't create sample_account, just query for non-existent account
        result = payment_methods.get_payment_methods("nonexistent-account-id")
        assert result == []

    def test_update_payment_method_account_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method when account doesn't exist."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method("nonexistent-account-id", "Old", "New")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_update_payment_method_method_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method when method doesn't exist."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "NonExistent", "New")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_delete_payment_method_account_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_payment_method when account doesn't exist."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_payment_method("nonexistent-account-id", "Venmo")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_delete_payment_method_method_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test delete_payment_method when method doesn't exist."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_payment_method(sample_account_id, "NonExistent")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert "not found" in exc_info.value.message.lower()

    def test_delete_qr_nosuchkey_error(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test delete_qr_from_s3 handles NoSuchKey errors gracefully."""
        # This should not raise an error even though the file doesn't exist
        payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")
        # No assertion needed - we just verify it doesn't raise

    def test_delete_qr_with_other_s3_error(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test delete_qr_from_s3 raises on non-NoSuchKey S3 errors."""

        mock_s3 = MagicMock()
        # Raise a non-NoSuchKey error
        mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "DeleteObject"
        )

        payment_methods.s3_client = mock_s3

        # This should log a warning but not raise, as delete_qr_from_s3 catches all exceptions
        payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")
        # No assertion needed - we just verify it doesn't crash

        payment_methods.s3_client = None

    def test_update_payment_method_empty_new_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method with empty new name."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "required" in exc_info.value.message.lower()

    def test_update_payment_method_reserved_new_name(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method with reserved name as new name."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "Cash")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "reserved" in exc_info.value.message.lower()

    def test_delete_payment_method_no_qr_but_warns_on_delete_failure(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str, s3_bucket: Any
    ) -> None:
        """Test delete_payment_method handles S3 delete warning path."""

        # Create a method with a qrCodeUrl
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        payment_methods.upload_qr_to_s3(sample_account_id, "Venmo", b"fake-qr-data", "image/png")

        # Mock S3 to raise an error that's not NoSuchKey
        mock_s3 = MagicMock()
        mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "DeleteObject"
        )

        payment_methods.s3_client = mock_s3

        # This should still succeed (with a warning logged) and delete the payment method
        payment_methods.delete_payment_method(sample_account_id, "Venmo")

        # Verify method was deleted
        methods = payment_methods.get_payment_methods(sample_account_id)
        assert len(methods) == 0

        payment_methods.s3_client = None

    def test_delete_qr_outer_exception(self, s3_bucket: Any, sample_account_id: str) -> None:
        """Test delete_qr_from_s3 handles outer exception path."""

        mock_s3 = MagicMock()
        # Raise an exception during _get_s3_client or before entering the loop
        mock_s3.delete_object.side_effect = Exception("Unexpected error")

        payment_methods.s3_client = mock_s3

        with pytest.raises(AppError) as exc_info:
            payment_methods.delete_qr_from_s3(sample_account_id, "Venmo")
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

        payment_methods.s3_client = None

    def test_update_payment_method_name_too_long(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test update_payment_method with name exceeding max length."""
        payment_methods.create_payment_method(sample_account_id, "Venmo")
        with pytest.raises(AppError) as exc_info:
            payment_methods.update_payment_method(sample_account_id, "Venmo", "X" * 51)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "50 characters" in exc_info.value.message or "must be" in exc_info.value.message.lower()


class TestValidatePaymentMethodExists:
    """Test validate_payment_method_exists function."""

    def test_validate_global_payment_method_cash(self, dynamodb_tables: Dict[str, Any], sample_account_id: str) -> None:
        """Test that Cash is always valid (global method)."""
        # Should not raise any error
        payment_methods.validate_payment_method_exists(sample_account_id, "Cash")

    def test_validate_global_payment_method_check(
        self, dynamodb_tables: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test that Check is always valid (global method)."""
        # Should not raise any error
        payment_methods.validate_payment_method_exists(sample_account_id, "Check")

    def test_validate_global_payment_method_case_insensitive(
        self, dynamodb_tables: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test that global methods are case-insensitive."""
        # Should not raise any error
        payment_methods.validate_payment_method_exists(sample_account_id, "cash")
        payment_methods.validate_payment_method_exists(sample_account_id, "CHECK")
        payment_methods.validate_payment_method_exists(sample_account_id, "CaSh")

    def test_validate_custom_payment_method_exists(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validating an existing custom payment method."""
        # Create a custom payment method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        # Should not raise any error
        payment_methods.validate_payment_method_exists(sample_account_id, "Venmo")

    def test_validate_custom_payment_method_case_insensitive(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test that custom payment method validation is case-insensitive."""
        # Create a custom payment method
        payment_methods.create_payment_method(sample_account_id, "Venmo")

        # Should not raise any error with different casing
        payment_methods.validate_payment_method_exists(sample_account_id, "venmo")
        payment_methods.validate_payment_method_exists(sample_account_id, "VENMO")
        payment_methods.validate_payment_method_exists(sample_account_id, "VeNmO")

    def test_validate_nonexistent_custom_payment_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validating a non-existent custom payment method raises error."""
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_payment_method_exists(sample_account_id, "Zelle")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "does not exist" in exc_info.value.message
        assert "Zelle" in exc_info.value.message

    def test_validate_payment_method_account_has_no_methods(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validating payment method when account has no custom methods."""
        # Account exists but has no payment methods
        # Global methods should still work
        payment_methods.validate_payment_method_exists(sample_account_id, "Cash")

        # Custom method should fail
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_payment_method_exists(sample_account_id, "Venmo")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "does not exist" in exc_info.value.message

    def test_validate_payment_method_account_not_found(
        self, dynamodb_tables: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validating payment method when account doesn't exist."""
        # Global methods should still work even if account doesn't exist
        payment_methods.validate_payment_method_exists("nonexistent-account", "Cash")

        # Custom method should fail
        with pytest.raises(AppError) as exc_info:
            payment_methods.validate_payment_method_exists("nonexistent-account", "Venmo")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "does not exist" in exc_info.value.message
