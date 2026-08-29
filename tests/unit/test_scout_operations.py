"""Unit tests for profile operations Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.scout_operations import create_seller_profile
from src.utils.errors import AppError, ErrorCode


class TestCreateSellerProfile:
    """Tests for create_seller_profile Lambda handler."""

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    @patch("src.handlers.scout_operations.uuid.uuid4")
    def test_create_seller_profile_success(
        self,
        mock_uuid: MagicMock,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful seller profile creation."""
        mock_uuid.return_value = "test-uuid-123"

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        result = create_seller_profile(event, lambda_context)

        assert result["profileId"] == "PROFILE#test-uuid-123"
        assert result["sellerName"] == "Test Scout"
        assert result["ownerAccountId"] == f"ACCOUNT#{event['identity']['sub']}"
        assert "createdAt" in result
        assert "updatedAt" in result
        mock_put_item.assert_called_once_with(Item=result)

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_with_special_characters(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with special characters in name."""
        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "José's Popcorn & Sales"}},
        }

        result = create_seller_profile(event, lambda_context)

        assert result["sellerName"] == "José's Popcorn & Sales"
        mock_put_item.assert_called_once()

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_error_handling(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error handling when put_item fails."""
        mock_put_item.side_effect = Exception("DynamoDB error")

        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "Test Scout"}},
        }

        with pytest.raises(AppError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to create seller profile" in str(exc_info.value.message)

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_with_unit_type_and_number(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with unit type and number."""
        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "sellerName": "Pack 42 Scout",
                    "unitType": "Pack",
                    "unitNumber": "42",
                }
            },
        }

        result = create_seller_profile(event, lambda_context)

        assert result["sellerName"] == "Pack 42 Scout"
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 42
        mock_put_item.assert_called_once_with(Item=result)

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_with_invalid_unit_number(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with invalid (non-numeric) unit number raises an error."""
        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "sellerName": "Pack Invalid Scout",
                    "unitType": "Pack",
                    "unitNumber": "not-a-number",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitNumber must be a valid integer" in str(exc_info.value.message)
        mock_put_item.assert_not_called()

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_empty_seller_name(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with empty sellerName raises an error."""
        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "   "}},
        }

        with pytest.raises(AppError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in str(exc_info.value.message)
        mock_put_item.assert_not_called()

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_seller_name_too_long(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with a sellerName exceeding the length limit raises an error."""
        event = {
            **appsync_event,
            "arguments": {"input": {"sellerName": "x" * 101}},
        }

        with pytest.raises(AppError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "must not exceed" in str(exc_info.value.message)
        mock_put_item.assert_not_called()

    @patch("src.handlers.scout_operations.tables.profiles.put_item")
    def test_create_seller_profile_invalid_unit_type(
        self,
        mock_put_item: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test profile creation with an unsupported unitType raises an error."""
        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "sellerName": "Test Scout",
                    "unitType": "INVALID",
                    "unitNumber": "42",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_seller_profile(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType must be one of" in str(exc_info.value.message)
        mock_put_item.assert_not_called()
