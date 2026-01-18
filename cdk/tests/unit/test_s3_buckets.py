"""Tests for S3 buckets module."""

from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import App, Stack

from cdk.s3_buckets import create_s3_buckets


@pytest.fixture
def mock_stack():
    """Create a mock CDK stack."""
    app = App()
    return Stack(app, "TestStack")


@pytest.fixture
def mock_rn():
    """Create a mock resource naming function."""
    return lambda name: f"{name}-ue1-test"


class TestCreateS3Buckets:
    """Tests for create_s3_buckets function."""

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_returns_dict_with_both_buckets(self, mock_bucket_class, mock_stack, mock_rn):
        """Function returns dictionary with static_assets_bucket and exports_bucket."""
        mock_static_bucket = MagicMock(name="static_bucket")
        mock_exports_bucket = MagicMock(name="exports_bucket")
        mock_bucket_class.side_effect = [mock_static_bucket, mock_exports_bucket]

        result = create_s3_buckets(mock_stack, mock_rn)

        assert "static_assets_bucket" in result
        assert "exports_bucket" in result
        assert result["static_assets_bucket"] is mock_static_bucket
        assert result["exports_bucket"] is mock_exports_bucket

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_creates_two_buckets(self, mock_bucket_class, mock_stack, mock_rn):
        """Function creates exactly 2 S3 buckets."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        assert mock_bucket_class.call_count == 2

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_static_assets_bucket_has_correct_name(self, mock_bucket_class, mock_stack, mock_rn):
        """Static assets bucket is named correctly using rn function."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        first_call = mock_bucket_class.call_args_list[0]
        assert first_call[1]["bucket_name"] == "kernelworx-static-ue1-test"

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_exports_bucket_has_correct_name(self, mock_bucket_class, mock_stack, mock_rn):
        """Exports bucket is named correctly using rn function."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        second_call = mock_bucket_class.call_args_list[1]
        assert second_call[1]["bucket_name"] == "kernelworx-exports-ue1-test"

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_static_assets_bucket_is_versioned(self, mock_bucket_class, mock_stack, mock_rn):
        """Static assets bucket has versioning enabled."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        first_call = mock_bucket_class.call_args_list[0]
        assert first_call[1]["versioned"] is True

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_exports_bucket_is_not_versioned(self, mock_bucket_class, mock_stack, mock_rn):
        """Exports bucket does not have versioning enabled."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        second_call = mock_bucket_class.call_args_list[1]
        assert second_call[1]["versioned"] is False

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_both_buckets_block_public_access(self, mock_bucket_class, mock_stack, mock_rn):
        """Both buckets have public access blocked."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        for call in mock_bucket_class.call_args_list:
            # BlockPublicAccess.BLOCK_ALL should be used
            assert "block_public_access" in call[1]

    @patch("cdk.s3_buckets.s3.Bucket")
    def test_both_buckets_use_s3_managed_encryption(self, mock_bucket_class, mock_stack, mock_rn):
        """Both buckets use S3 managed encryption."""
        mock_bucket_class.return_value = MagicMock()

        create_s3_buckets(mock_stack, mock_rn)

        for call in mock_bucket_class.call_args_list:
            assert "encryption" in call[1]
