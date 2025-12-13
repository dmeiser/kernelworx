"""Unit tests for profile operations Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.profile_operations import create_seller_profile


class TestCreateSellerProfile:
    """Tests for create_seller_profile Lambda handler."""

    @patch("src.handlers.profile_operations.boto3.client")
    @patch("src.handlers.profile_operations.uuid.uuid4")
    def test_create_seller_profile_success(
        self,
        mock_uuid: MagicMock,
        mock_client: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful seller profile creation."""
        # Arrange
        mock_uuid.return_value = "test-uuid-123"
        mock_dynamodb = MagicMock()
        mock_client.return_value = mock_dynamodb

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        # Act
        result = create_seller_profile(event, lambda_context)

        # Assert
        assert result["profileId"].startswith("PROFILE#")
        assert result["sellerName"] == "Test Scout"
        assert result["ownerAccountId"] == event["identity"]["sub"]
        assert "createdAt" in result
        assert "updatedAt" in result

        # Verify transact_write_items was called
        mock_dynamodb.transact_write_items.assert_called_once()
        call_args = mock_dynamodb.transact_write_items.call_args
        assert call_args is not None
        assert "TransactItems" in call_args.kwargs
        assert len(call_args.kwargs["TransactItems"]) == 2

    @patch("src.handlers.profile_operations.boto3.client")
    def test_create_seller_profile_with_special_characters(
        self,
        mock_client: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with special characters in name."""
        # Arrange
        mock_dynamodb = MagicMock()
        mock_client.return_value = mock_dynamodb

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "José's Popcorn & Sales"}},
        }

        # Act
        result = create_seller_profile(event, lambda_context)

        # Assert
        assert result["sellerName"] == "José's Popcorn & Sales"
        mock_dynamodb.transact_write_items.assert_called_once()

    @patch("src.handlers.profile_operations.boto3.client")
    def test_create_seller_profile_has_ownership_item(
        self,
        mock_client: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that ownership item is written correctly."""
        # Arrange
        mock_dynamodb = MagicMock()
        mock_client.return_value = mock_dynamodb

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        # Act
        create_seller_profile(event, lambda_context)

        # Assert
        call_args = mock_dynamodb.transact_write_items.call_args
        assert call_args is not None
        items = call_args.kwargs["TransactItems"]

        # First item should be ownership item
        ownership_item = items[0]["Put"]["Item"]
        assert ownership_item["PK"]["S"].startswith("ACCOUNT#")
        assert ownership_item["SK"]["S"].startswith("PROFILE#")

    @patch("src.handlers.profile_operations.boto3.client")
    def test_create_seller_profile_has_metadata_item(
        self,
        mock_client: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that metadata item is written correctly."""
        # Arrange
        mock_dynamodb = MagicMock()
        mock_client.return_value = mock_dynamodb

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        # Act
        create_seller_profile(event, lambda_context)

        # Assert
        call_args = mock_dynamodb.transact_write_items.call_args
        assert call_args is not None
        items = call_args.kwargs["TransactItems"]

        # Second item should be metadata item
        metadata_item = items[1]["Put"]["Item"]
        assert metadata_item["PK"]["S"].startswith("PROFILE#")
        assert metadata_item["SK"]["S"] == "METADATA"

    @patch("src.handlers.profile_operations.boto3.client")
    def test_create_seller_profile_error_handling(
        self,
        mock_client: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error handling when transact_write_items fails."""
        # Arrange
        mock_dynamodb = MagicMock()
        mock_dynamodb.transact_write_items.side_effect = Exception("DynamoDB error")
        mock_client.return_value = mock_dynamodb

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        # Act & Assert
        with pytest.raises(RuntimeError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert "Failed to create seller profile" in str(exc_info.value)
