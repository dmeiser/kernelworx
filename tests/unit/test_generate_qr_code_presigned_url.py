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

    def test_resigns_already_presigned_url_after_ownership_check(self, s3_bucket: Any) -> None:
        """Test that an already-presigned stored URL is re-signed only after ownership validation."""
        owner_account_id = "account-123"
        s3_key = f"payment-qr-codes/{owner_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        existing_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Algorithm=AWS4-HMAC-SHA256&other=params"
        event: Dict[str, Any] = {
            "qrCodeUrl": existing_url,
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
            "methodName": "Venmo",
            "s3Key": s3_key,
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is not None
        assert result != existing_url
        assert "X-Amz-Signature=" in result or "Signature=" in result

    def test_rejects_already_presigned_url_for_non_owner(self) -> None:
        """Test that a non-owner cannot receive an already-presigned URL (regression: #122)."""
        existing_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc123&other=params"
        event: Dict[str, Any] = {
            "qrCodeUrl": existing_url,
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_rejects_already_presigned_url_without_identity(self) -> None:
        """Test that an already-presigned URL still requires authentication (regression: #122)."""
        existing_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc123&other=params"
        event: Dict[str, Any] = {
            "qrCodeUrl": existing_url,
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_raises_unauthorized_when_no_owner_id(self) -> None:
        """Test that UNAUTHORIZED error is raised when ownerAccountId is missing."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "s3://bucket/key",
            "ownerAccountId": None,
            "identity": {"sub": "account-123"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED
        assert "Owner account ID required" in result["message"]

    def test_raises_unauthorized_when_owner_id_empty(self) -> None:
        """Test that UNAUTHORIZED error is raised when ownerAccountId is empty string."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "s3://bucket/key",
            "ownerAccountId": "",
            "identity": {"sub": "account-123"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED
        assert "Owner account ID required" in result["message"]

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
            "identity": {"sub": owner_account_id},
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
            "identity": {"sub": "account-123"},
            "methodName": "Venmo",
            "s3Key": "some-key",
        }

        with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url") as mock_generate:
            mock_generate.side_effect = Exception("Unexpected error")

            result = generate_qr_code_presigned_url(event, None)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to generate QR code URL" in result["message"]

    def test_default_method_name_is_empty_string(self, s3_bucket: Any) -> None:
        """Test that method_name defaults to empty string when not provided."""
        owner_account_id = "account-123"
        s3_key = f"payment-qr-codes/{owner_account_id}/default.png"

        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "qrCodeUrl": s3_key,
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
            # methodName intentionally omitted
            "s3Key": s3_key,
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result is not None
        assert result.startswith("https://")

    def test_raises_forbidden_when_caller_mismatches_owner(self) -> None:
        """Test that FORBIDDEN is raised when caller is not the owner."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_raises_unauthorized_when_identity_missing(self) -> None:
        """Test that UNAUTHORIZED is raised when identity is missing."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_allows_write_collaborator_with_profile_id(self, s3_bucket: Any) -> None:
        """Test that a WRITE collaborator can retrieve the owner's QR code."""
        owner_account_id = "account-123"
        collaborator_id = "account-456"
        profile_id = "profile-abc"
        s3_key = f"payment-qr-codes/{owner_account_id}/venmo.png"

        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "qrCodeUrl": s3_key,
            "ownerAccountId": owner_account_id,
            "identity": {"sub": collaborator_id},
            "methodName": "Venmo",
            "s3Key": s3_key,
            "profileId": profile_id,
        }

        with patch("src.handlers.generate_qr_code_presigned_url.check_profile_access") as mock_check_access:
            mock_check_access.return_value = True

            result = generate_qr_code_presigned_url(event, None)

        assert result is not None
        assert result.startswith("https://")
        mock_check_access.assert_called_once_with(collaborator_id, profile_id, "WRITE")

    def test_rejects_non_owner_without_profile_id(self) -> None:
        """Test that a non-owner is denied when no profileId is provided."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_rejects_collaborator_without_write_permission(self) -> None:
        """Test that a collaborator without WRITE access is denied."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
            "profileId": "profile-abc",
        }

        with patch("src.handlers.generate_qr_code_presigned_url.check_profile_access") as mock_check_access:
            mock_check_access.return_value = False

            result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        mock_check_access.assert_called_once_with("other-account", "profile-abc", "WRITE")

    def test_rejects_collaborator_when_profile_not_found(self) -> None:
        """Test that a missing profile is treated as denied for collaborators."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
            "profileId": "profile-abc",
        }

        with patch("src.handlers.generate_qr_code_presigned_url.check_profile_access") as mock_check_access:
            mock_check_access.side_effect = AppError(ErrorCode.NOT_FOUND, "Profile not found")

            result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        mock_check_access.assert_called_once_with("other-account", "profile-abc", "WRITE")

    def test_propagates_unexpected_profile_access_error(self) -> None:
        """Test that non-NotFound errors from check_profile_access propagate."""
        event: Dict[str, Any] = {
            "qrCodeUrl": "payment-qr-codes/account-123/venmo.png",
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
            "methodName": "Venmo",
            "s3Key": "payment-qr-codes/account-123/venmo.png",
            "profileId": "profile-abc",
        }

        with patch("src.handlers.generate_qr_code_presigned_url.check_profile_access") as mock_check_access:
            mock_check_access.side_effect = AppError(ErrorCode.INTERNAL_ERROR, "DynamoDB error")

            result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        mock_check_access.assert_called_once_with("other-account", "profile-abc", "WRITE")


class TestBatchGenerateQrCodePresignedUrls:
    """Test the batch payload (s3Keys list) used by the batch_qr_urls pipeline function (#330)."""

    def test_returns_map_of_presigned_urls(self, s3_bucket: Any) -> None:
        """Test that a batch payload returns one URL per owned S3 key."""
        owner_account_id = "account-123"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        keys = [
            f"payment-qr-codes/{owner_account_id}/venmo.png",
            f"payment-qr-codes/{owner_account_id}/zelle.png",
        ]
        for key in keys:
            s3_bucket.put_object(Bucket=bucket_name, Key=key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "s3Keys": keys,
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
        }

        result = generate_qr_code_presigned_url(event, None)

        assert isinstance(result, dict)
        assert set(result.keys()) == set(keys)
        for url in result.values():
            assert url.startswith("https://")
            assert "Signature=" in url or "X-Amz-Signature" in url

    def test_single_lambda_invocation_signs_all_keys(self, s3_bucket: Any) -> None:
        """Regression for #330: one invocation handles every key (no N+1)."""
        owner_account_id = "account-123"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        keys = [f"payment-qr-codes/{owner_account_id}/method-{i}.png" for i in range(20)]
        for key in keys:
            s3_bucket.put_object(Bucket=bucket_name, Key=key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "s3Keys": keys,
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
        }

        with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url") as mock_generate:
            from src.utils.payment_methods import generate_presigned_get_url

            mock_generate.side_effect = generate_presigned_get_url

            result = generate_qr_code_presigned_url(event, None)

        assert mock_generate.call_count == 20
        assert set(result.keys()) == set(keys)

    def test_skips_keys_that_fail_ownership_validation(self, s3_bucket: Any) -> None:
        """Test that keys not owned by the owner are omitted, not fatal."""
        owner_account_id = "account-123"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        owned_key = f"payment-qr-codes/{owner_account_id}/venmo.png"
        foreign_key = "payment-qr-codes/other-account/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=owned_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "s3Keys": [owned_key, foreign_key],
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
        }

        result = generate_qr_code_presigned_url(event, None)

        assert set(result.keys()) == {owned_key}

    def test_ignores_empty_and_non_string_keys(self, s3_bucket: Any) -> None:
        """Test that empty/non-string entries are ignored."""
        owner_account_id = "account-123"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        key = f"payment-qr-codes/{owner_account_id}/venmo.png"
        s3_bucket.put_object(Bucket=bucket_name, Key=key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "s3Keys": ["", None, 42, key],
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
        }

        result = generate_qr_code_presigned_url(event, None)

        assert set(result.keys()) == {key}

    def test_empty_keys_list_returns_empty_map(self, s3_bucket: Any) -> None:
        """Test that an empty batch returns an empty map without signing."""
        event: Dict[str, Any] = {
            "s3Keys": [],
            "ownerAccountId": "account-123",
            "identity": {"sub": "account-123"},
        }

        with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url") as mock_generate:
            result = generate_qr_code_presigned_url(event, None)

        assert result == {}
        mock_generate.assert_not_called()

    def test_batch_requires_authentication(self, s3_bucket: Any) -> None:
        """Test that a batch payload without identity is rejected."""
        event: Dict[str, Any] = {
            "s3Keys": ["payment-qr-codes/account-123/venmo.png"],
            "ownerAccountId": "account-123",
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_batch_rejects_non_owner_without_profile(self, s3_bucket: Any) -> None:
        """Test that a batch for another owner's methods is denied."""
        event: Dict[str, Any] = {
            "s3Keys": ["payment-qr-codes/account-123/venmo.png"],
            "ownerAccountId": "account-123",
            "identity": {"sub": "other-account"},
        }

        result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_batch_propagates_non_forbidden_signing_errors(self, s3_bucket: Any) -> None:
        """Test that non-FORBIDDEN signing errors fail the batch (not skipped)."""
        owner_account_id = "account-123"
        s3_key = f"payment-qr-codes/{owner_account_id}/venmo.png"
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3_bucket.put_object(Bucket=bucket_name, Key=s3_key, Body=b"fake-qr-data")

        event: Dict[str, Any] = {
            "s3Keys": [s3_key],
            "ownerAccountId": owner_account_id,
            "identity": {"sub": owner_account_id},
        }

        with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url") as mock_generate:
            mock_generate.side_effect = AppError(ErrorCode.INTERNAL_ERROR, "S3 unavailable")

            result = generate_qr_code_presigned_url(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
