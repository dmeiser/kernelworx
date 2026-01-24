"""
Unit tests for validate_payment_method Lambda handler.
"""

import os
from typing import Any, Dict, Generator
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.handlers.validate_payment_method import lambda_handler
from src.utils.errors import AppError
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


@pytest.fixture
def dynamodb_tables(aws_credentials: None) -> Generator[Dict[str, Any], None, None]:
    """Create all mock DynamoDB tables."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        tables = create_all_tables(dynamodb)
        yield tables


@pytest.fixture
def sample_account_id() -> str:
    """Sample account ID."""
    return "acc-123-456"


@pytest.fixture
def sample_account(dynamodb_tables: Dict[str, Any], sample_account_id: str) -> Dict[str, Any]:
    """Create a sample account with payment methods."""

    account_id_key = f"ACCOUNT#{sample_account_id}"
    account = {
        "accountId": account_id_key,
        "email": "test@example.com",
        "givenName": "Test",
        "familyName": "User",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": None}]},
    }

    tables_dict = dynamodb_tables
    accounts_table = tables_dict["accounts"]
    accounts_table.put_item(Item=account)

    return account


class TestValidatePaymentMethodHandler:
    """Test validate_payment_method Lambda handler."""

    def test_validate_global_payment_method_cash(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation succeeds for global payment method Cash."""
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "Cash"}},
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id

    def test_validate_global_payment_method_check(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation succeeds for global payment method Check."""
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "Check"}},
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id

    def test_validate_custom_payment_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation succeeds for existing custom payment method."""
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "Venmo"}},
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id

    def test_validate_nonexistent_payment_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation fails for non-existent payment method."""
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "Zelle"}},
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)

        assert "does not exist" in str(exc_info.value)

    def test_validate_with_account_prefix(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation succeeds when ownerAccountId has ACCOUNT# prefix."""
        event = {
            "prev": {"result": {"ownerAccountId": f"ACCOUNT#{sample_account_id}"}},
            "arguments": {"input": {"paymentMethod": "Venmo"}},
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{sample_account_id}"

    def test_missing_owner_account_id(self, dynamodb_tables: Dict[str, Any]) -> None:
        """Test validation fails when ownerAccountId is missing."""
        event = {"prev": {"result": {}}, "arguments": {"input": {"paymentMethod": "Cash"}}}

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)

        assert "Owner account ID not found" in str(exc_info.value)

    def test_missing_payment_method(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation fails when paymentMethod is missing."""
        event = {"prev": {"result": {"ownerAccountId": sample_account_id}}, "arguments": {"input": {}}}

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)

        assert "Payment method is required" in str(exc_info.value)

    def test_case_insensitive_validation(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test validation is case-insensitive."""
        # Test lowercase
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "venmo"}},
        }
        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id

        # Test uppercase
        event = {
            "prev": {"result": {"ownerAccountId": sample_account_id}},
            "arguments": {"input": {"paymentMethod": "VENMO"}},
        }
        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id

    def test_passthrough_prev_result(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test that the handler returns prev.result unchanged."""
        event = {
            "prev": {
                "result": {
                    "ownerAccountId": sample_account_id,
                    "profileId": "PROFILE#123",
                    "otherData": "should be preserved",
                }
            },
            "arguments": {"input": {"paymentMethod": "Cash"}},
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == sample_account_id
        assert result["profileId"] == "PROFILE#123"
        assert result["otherData"] == "should be preserved"

    def test_unexpected_error_handling(
        self, dynamodb_tables: Dict[str, Any], sample_account: Dict[str, Any], sample_account_id: str
    ) -> None:
        """Test that unexpected errors are caught and wrapped."""
        # Mock validate_payment_method_exists to raise an unexpected exception
        with patch("src.handlers.validate_payment_method.validate_payment_method_exists") as mock_validate:
            mock_validate.side_effect = Exception("Unexpected database error")

            event = {
                "prev": {"result": {"ownerAccountId": sample_account_id}},
                "arguments": {"input": {"paymentMethod": "Cash"}},
            }

            with pytest.raises(AppError) as exc_info:
                lambda_handler(event, None)

            assert exc_info.value.error_code == "INTERNAL_ERROR"
            assert "Failed to validate payment method" in str(exc_info.value)
