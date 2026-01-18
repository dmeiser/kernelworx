"""
Unit tests for generate_qr_code_presigned_url Lambda handler.

Tests the QR code presigned URL generation for payment methods.
"""

import os
from typing import Any, Dict, Generator
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.handlers.generate_qr_code_presigned_url import generate_qr_code_presigned_url
from src.utils.errors import AppError, ErrorCode


@pytest.fixture
def aws_credentials() -> None:
    """Set fake AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def s3_bucket(aws_credentials: None) -> Generator[Any, None, None]:
    """Create mock S3 bucket for QR code storage."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "test-exports-bucket"
        s3.create_bucket(Bucket=bucket_name)
        os.environ["EXPORTS_BUCKET"] = bucket_name
        yield s3


class TestGenerateQrCodePresignedUrl:
    """Test generate_qr_code_presigned_url Lambda handler."""

    def test_returns_none_when_no_qr_code_url(self) -> None:
        """Test that None is returned when qrCodeUrl is not provided."""
        event: Dict[str, Any] = {
            "qrCodeUrl": None,
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is None

    def test_returns_none_when_qr_code_url_empty(self) -> None:
        """Test that None is returned when qrCodeUrl is empty string."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "",
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is None

    def test_returns_existing_presigned_url_with_algorithm(self) -> None:
        """Test that existing presigned URLs with X-Amz-Algorithm are returned as-is."""
        existing_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Algorithm=AWS4-HMAC-SHA256&other=params"
        event: Dict[str, Any] = {
            "qrCodeUrl": existing_url,
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result == existing_url

    def test_returns_existing_presigned_url_with_signature(self) -> None:
        """Test that existing presigned URLs with X-Amz-Signature are returned as-is."""
        existing_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc123&other=params"
        event: Dict[str, Any] = {
            "qrCodeUrl": existing_url,
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result == existing_url

    def test_raises_unauthorized_when_no_owner_id(self) -> None:
        """Test that UNAUTHORIZED error is raised when ownerAccountId is missing."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "s3://bucket/key",
            "ownerAccountId": None,
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        with pytest.raises(AppError) as exc_info:
            generate_qr_code_presigned_url(event, None)

        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED
        assert "Owner account ID required" in str(exc_info.value.message)

    def test_raises_unauthorized_when_owner_id_empty(self) -> None:
        """Test that UNAUTHORIZED error is raised when ownerAccountId is empty string."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "s3://bucket/key",
            "ownerAccountId": "",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        with pytest.raises(AppError) as exc_info:
            generate_qr_code_presigned_url(event, None)

        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_generates_presigned_url_success(self, s3_bucket: Any) -> None:
        """Test successful presigned URL generation."""
        owner_account_id = "account-123"
        method_name = "Venmo"
        s3_key = f"payment-qr-codes/{owner_account_id}/venmo.png"

        # Upload a test object
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "qrCodeUrl": s3_key,
            "ownerAccountId": owner_account_id,
            "methodName": method_name,
            "s3Key": s3_key,
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is not None
        assert result.startswith("https://")
        # URL should have signing parameters
        assert "Signature=" in result or "X-Amz-Signature" in result

    def test_handles_generic_exception(self) -> None:
        """Test that generic exceptions are wrapped in INTERNAL_ERROR."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "s3://bucket/key",
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "some-key",
        }

        with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url") as mock_generate:
            mock_generate.side_effect = Exception("Unexpected error")

            with pytest.raises(AppError) as exc_info:
                generate_qr_code_presigned_url(event, None)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to generate QR code URL" in str(exc_info.value.message)

    def test_default_method_name_is_empty_string(self, s3_bucket: Any) -> None:
        """Test that method_name defaults to empty string when not provided."""
        owner_account_id = "account-123"
        s3_key = f"payment-qr-codes/{owner_account_id}/default.png"

        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "qrCodeUrl": s3_key,
            "ownerAccountId": owner_account_id,
            # methodName intentionally omitted
            "s3Key": s3_key,
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is not None
        assert result.startswith("https://")
