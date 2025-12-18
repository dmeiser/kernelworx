"""Unit tests for account operations Lambda handler.

Updated for multi-table design (accounts table).
"""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import boto3
import pytest

from src.handlers.account_operations import update_my_account
from src.utils.errors import AppError, ErrorCode


def get_accounts_table() -> Any:
    """Get the accounts table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-accounts-ue1-dev")


class TestUpdateMyAccount:
    """Tests for update_my_account handler."""

    def test_update_given_name(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating givenName."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "John"
        assert result["accountId"] == account_id_key

    def test_update_multiple_fields(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating multiple fields at once."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "givenName": "John",
                    "familyName": "Doe",
                    "city": "Seattle",
                    "state": "WA",
                    "unitNumber": "123",
                }
            },
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "John"
        assert result["accountId"] == account_id_key

    def test_update_no_fields_raises_error(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty input raises error."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **appsync_event,
            "arguments": {"input": {}},
        }

        with pytest.raises(AppError) as exc_info:
            update_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_update_nonexistent_account(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating non-existent account raises error."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with pytest.raises(AppError) as exc_info:
            update_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    @patch("src.handlers.account_operations.get_accounts_table")
    def test_database_error_propagates(
        self,
        mock_get_accounts_table: MagicMock,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that database errors propagate."""
        mock_table = MagicMock()
        mock_table.update_item.side_effect = Exception("Database error")
        mock_get_accounts_table.return_value = mock_table

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with pytest.raises(Exception, match="Database error"):
            update_my_account(event, lambda_context)

    @patch("src.handlers.account_operations.get_accounts_table")
    def test_client_error_not_found(
        self,
        mock_get_accounts_table: MagicMock,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that ClientError with other code propagates."""
        from botocore.exceptions import ClientError

        mock_table = MagicMock()
        error_response = {"Error": {"Code": "SomeOtherError", "Message": "Access Denied"}}
        mock_table.update_item.side_effect = ClientError(error_response, "UpdateItem")
        mock_get_accounts_table.return_value = mock_table

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with pytest.raises(ClientError):
            update_my_account(event, lambda_context)
