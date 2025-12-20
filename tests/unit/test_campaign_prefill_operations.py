"""Unit tests for campaign prefill operations Lambda handlers."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.handlers.campaign_prefill_operations import (
    _count_user_prefills,
    _generate_prefill_code,
    create_campaign_prefill,
    delete_campaign_prefill,
    find_campaign_prefills,
    get_campaign_prefill,
    list_my_campaign_prefills,
    update_campaign_prefill,
)
from src.utils.errors import AuthorizationError, ValidationError


class TestGeneratePrefillCode:
    """Tests for _generate_prefill_code helper function."""

    def test_generate_prefill_code_pack(self) -> None:
        """Test prefill code generation for Pack."""
        code = _generate_prefill_code("Pack", 123, "Spring", "IL", 2025)
        assert code == "PACK123-SPRI-IL-25"

    def test_generate_prefill_code_troop(self) -> None:
        """Test prefill code generation for Troop."""
        code = _generate_prefill_code("Troop", 456, "Fall", "CA", 2025)
        assert code == "TROO456-FALL-CA-25"

    def test_generate_prefill_code_crew(self) -> None:
        """Test prefill code generation for Crew."""
        code = _generate_prefill_code("Crew", 789, "Winter", "TX", 2026)
        assert code == "CREW789-WINT-TX-26"

    def test_generate_prefill_code_ship(self) -> None:
        """Test prefill code generation for Ship."""
        code = _generate_prefill_code("Ship", 111, "Summer", "NY", 2024)
        assert code == "SHIP111-SUMM-NY-24"

    def test_generate_prefill_code_short_season_name(self) -> None:
        """Test prefill code with season name shorter than 4 chars."""
        code = _generate_prefill_code("Pack", 123, "Fal", "IL", 2025)
        assert code == "PACK123-FAL-IL-25"

    def test_generate_prefill_code_lowercase_inputs(self) -> None:
        """Test that lowercase inputs are uppercased."""
        code = _generate_prefill_code("pack", 123, "spring", "il", 2025)
        assert code == "PACK123-SPRI-IL-25"


class TestCountUserPrefills:
    """Tests for _count_user_prefills helper function."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_count_user_prefills_zero(self, mock_table: MagicMock) -> None:
        """Test counting prefills when user has none."""
        mock_table.query.return_value = {"Count": 0}
        count = _count_user_prefills("account-123")
        assert count == 0
        mock_table.query.assert_called_once()

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_count_user_prefills_some(self, mock_table: MagicMock) -> None:
        """Test counting prefills when user has some."""
        mock_table.query.return_value = {"Count": 15}
        count = _count_user_prefills("account-123")
        assert count == 15

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_count_user_prefills_max(self, mock_table: MagicMock) -> None:
        """Test counting prefills at rate limit."""
        mock_table.query.return_value = {"Count": 50}
        count = _count_user_prefills("account-123")
        assert count == 50


class TestCreateCampaignPrefill:
    """Tests for create_campaign_prefill Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    @patch("src.handlers.campaign_prefill_operations._count_user_prefills")
    def test_create_campaign_prefill_success(
        self,
        mock_count: MagicMock,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful campaign prefill creation."""
        # Arrange
        mock_count.return_value = 5  # User has 5 prefills
        mock_table.put_item.return_value = {}

        event = {
            **appsync_event,
            "arguments": {
                "catalogId": "CATALOG#test-catalog",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "creatorMessage": "Join our Pack 123 Fall campaign!",
                "description": "Internal: Fall 2025 campaign",
            },
        }

        # Act
        result = create_campaign_prefill(event, lambda_context)

        # Assert
        assert result["prefillCode"] == "PACK123-FALL-IL-25"
        assert result["catalogId"] == "CATALOG#test-catalog"
        assert result["seasonName"] == "Fall"
        assert result["seasonYear"] == 2025
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 123
        assert result["city"] == "Springfield"
        assert result["state"] == "IL"
        assert result["creatorMessage"] == "Join our Pack 123 Fall campaign!"
        assert result["description"] == "Internal: Fall 2025 campaign"
        assert result["isActive"] is True
        assert "createdAt" in result

        # Verify put_item called with conditional expression
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args
        assert "ConditionExpression" in call_args.kwargs
        assert call_args.kwargs["Item"]["PK"] == "PREFILL#PACK123-FALL-IL-25"

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    @patch("src.handlers.campaign_prefill_operations._count_user_prefills")
    def test_create_campaign_prefill_with_optional_dates(
        self,
        mock_count: MagicMock,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test campaign prefill creation with optional start/end dates."""
        # Arrange
        mock_count.return_value = 0
        mock_table.put_item.return_value = {}

        event = {
            **appsync_event,
            "arguments": {
                "catalogId": "CATALOG#test-catalog",
                "seasonName": "Spring",
                "seasonYear": 2026,
                "unitType": "Troop",
                "unitNumber": 456,
                "city": "Chicago",
                "state": "IL",
                "startDate": "2026-02-01",
                "endDate": "2026-05-31",
            },
        }

        # Act
        result = create_campaign_prefill(event, lambda_context)

        # Assert
        assert result["startDate"] == "2026-02-01"
        assert result["endDate"] == "2026-05-31"

    @patch("src.handlers.campaign_prefill_operations._count_user_prefills")
    def test_create_campaign_prefill_rate_limit_exceeded(
        self,
        mock_count: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that rate limit of 50 prefills is enforced."""
        # Arrange
        mock_count.return_value = 50  # User already has 50 prefills

        event = {
            **appsync_event,
            "arguments": {
                "catalogId": "CATALOG#test-catalog",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
            },
        }

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            create_campaign_prefill(event, lambda_context)

        assert "Rate limit exceeded" in str(exc_info.value)
        assert "50" in str(exc_info.value)

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    @patch("src.handlers.campaign_prefill_operations._count_user_prefills")
    def test_create_campaign_prefill_creator_message_too_long(
        self,
        mock_count: MagicMock,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that creator message exceeding 300 chars is rejected."""
        # Arrange
        mock_count.return_value = 0

        event = {
            **appsync_event,
            "arguments": {
                "catalogId": "CATALOG#test-catalog",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "creatorMessage": "A" * 301,  # 301 characters
            },
        }

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            create_campaign_prefill(event, lambda_context)

        assert "300 characters" in str(exc_info.value)

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    @patch("src.handlers.campaign_prefill_operations._count_user_prefills")
    def test_create_campaign_prefill_code_collision(
        self,
        mock_count: MagicMock,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test handling of prefill code collision."""
        # Arrange
        mock_count.return_value = 0

        # Simulate conditional check failure (code already exists)
        error_response = {"Error": {"Code": "ConditionalCheckFailedException"}}
        mock_table.put_item.side_effect = ClientError(error_response, "PutItem")
        mock_table.meta.client.exceptions.ConditionalCheckFailedException = ClientError

        event = {
            **appsync_event,
            "arguments": {
                "catalogId": "CATALOG#test-catalog",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
            },
        }

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            create_campaign_prefill(event, lambda_context)

        assert "already exists" in str(exc_info.value)


class TestGetCampaignPrefill:
    """Tests for get_campaign_prefill Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_get_campaign_prefill_success(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful retrieval of campaign prefill."""
        # Arrange
        mock_table.get_item.return_value = {
            "Item": {
                "PK": "PREFILL#PACK123-FALL-IL-25",
                "SK": "METADATA",
                "prefillCode": "PACK123-FALL-IL-25",
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdBy": "account-123",
                "createdByName": "Test User",
                "creatorMessage": "Join us!",
                "description": "Test campaign",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }

        event = {
            **appsync_event,
            "arguments": {"prefillCode": "PACK123-FALL-IL-25"},
        }

        # Act
        result = get_campaign_prefill(event, lambda_context)

        # Assert
        assert result is not None
        assert result["prefillCode"] == "PACK123-FALL-IL-25"
        assert result["catalogId"] == "CATALOG#test"
        assert result["isActive"] is True
        # Verify PK/SK not in response
        assert "PK" not in result
        assert "SK" not in result

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_get_campaign_prefill_not_found(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test retrieval of non-existent prefill returns None."""
        # Arrange
        mock_table.get_item.return_value = {}

        event = {
            **appsync_event,
            "arguments": {"prefillCode": "NONEXISTENT"},
        }

        # Act
        result = get_campaign_prefill(event, lambda_context)

        # Assert
        assert result is None


class TestListMyCampaignPrefills:
    """Tests for list_my_campaign_prefills Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_list_my_campaign_prefills_success(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful listing of user's prefills."""
        # Arrange
        mock_table.query.return_value = {
            "Items": [
                {
                    "PK": "PREFILL#PACK123-FALL-IL-25",
                    "SK": "METADATA",
                    "prefillCode": "PACK123-FALL-IL-25",
                    "catalogId": "CATALOG#test1",
                    "seasonName": "Fall",
                    "seasonYear": 2025,
                    "unitType": "Pack",
                    "unitNumber": 123,
                    "city": "Springfield",
                    "state": "IL",
                    "createdBy": "test-account-id",
                    "createdByName": "Test User",
                    "creatorMessage": "",
                    "description": "",
                    "createdAt": "2025-01-01T00:00:00Z",
                    "isActive": True,
                },
                {
                    "PK": "PREFILL#TROO456-SPRI-IL-26",
                    "SK": "METADATA",
                    "prefillCode": "TROO456-SPRI-IL-26",
                    "catalogId": "CATALOG#test2",
                    "seasonName": "Spring",
                    "seasonYear": 2026,
                    "unitType": "Troop",
                    "unitNumber": 456,
                    "city": "Chicago",
                    "state": "IL",
                    "createdBy": "test-account-id",
                    "createdByName": "Test User",
                    "creatorMessage": "",
                    "description": "",
                    "createdAt": "2025-02-01T00:00:00Z",
                    "isActive": True,
                },
            ]
        }

        event = {
            **appsync_event,
            "identity": {"sub": "test-account-id"},
        }

        # Act
        result = list_my_campaign_prefills(event, lambda_context)

        # Assert
        assert len(result) == 2
        assert result[0]["prefillCode"] == "PACK123-FALL-IL-25"
        assert result[1]["prefillCode"] == "TROO456-SPRI-IL-26"
        # Verify GSI query was used
        mock_table.query.assert_called_once()
        assert mock_table.query.call_args.kwargs["IndexName"] == "GSI1"

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_list_my_campaign_prefills_empty(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test listing when user has no prefills."""
        # Arrange
        mock_table.query.return_value = {"Items": []}

        # Act
        result = list_my_campaign_prefills(appsync_event, lambda_context)

        # Assert
        assert result == []


class TestFindCampaignPrefills:
    """Tests for find_campaign_prefills Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_find_campaign_prefills_success(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful discovery of prefills by unit+season."""
        # Arrange
        mock_table.query.return_value = {
            "Items": [
                {
                    "PK": "PREFILL#PACK123-FALL-IL-25",
                    "SK": "METADATA",
                    "prefillCode": "PACK123-FALL-IL-25",
                    "catalogId": "CATALOG#test",
                    "seasonName": "Fall",
                    "seasonYear": 2025,
                    "unitType": "Pack",
                    "unitNumber": 123,
                    "city": "Springfield",
                    "state": "IL",
                    "createdBy": "account-123",
                    "createdByName": "Leader",
                    "creatorMessage": "Join us!",
                    "description": "",
                    "createdAt": "2025-01-01T00:00:00Z",
                    "isActive": True,
                }
            ]
        }

        event = {
            **appsync_event,
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "seasonName": "Fall",
                "seasonYear": 2025,
            },
        }

        # Act
        result = find_campaign_prefills(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["prefillCode"] == "PACK123-FALL-IL-25"
        # Verify GSI2 query was used
        mock_table.query.assert_called_once()
        assert mock_table.query.call_args.kwargs["IndexName"] == "GSI2"

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_find_campaign_prefills_filters_inactive(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that inactive prefills are filtered out."""
        # Arrange
        mock_table.query.return_value = {
            "Items": [
                {
                    "prefillCode": "PACK123-FALL-IL-25",
                    "catalogId": "CATALOG#test1",
                    "seasonName": "Fall",
                    "seasonYear": 2025,
                    "unitType": "Pack",
                    "unitNumber": 123,
                    "city": "Springfield",
                    "state": "IL",
                    "createdBy": "account-123",
                    "createdByName": "Leader",
                    "creatorMessage": "",
                    "description": "",
                    "createdAt": "2025-01-01T00:00:00Z",
                    "isActive": True,
                },
                {
                    "prefillCode": "PACK123-FALL-IL-25-OLD",
                    "catalogId": "CATALOG#test2",
                    "seasonName": "Fall",
                    "seasonYear": 2025,
                    "unitType": "Pack",
                    "unitNumber": 123,
                    "city": "Springfield",
                    "state": "IL",
                    "createdBy": "account-456",
                    "createdByName": "Old Leader",
                    "creatorMessage": "",
                    "description": "",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "isActive": False,
                },
            ]
        }

        event = {
            **appsync_event,
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "seasonName": "Fall",
                "seasonYear": 2025,
            },
        }

        # Act
        result = find_campaign_prefills(event, lambda_context)

        # Assert - only active prefill returned
        assert len(result) == 1
        assert result[0]["isActive"] is True


class TestUpdateCampaignPrefill:
    """Tests for update_campaign_prefill Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_update_campaign_prefill_success(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful update of campaign prefill."""
        # Arrange
        existing_item = {
            "Item": {
                "PK": "PREFILL#PACK123-FALL-IL-25",
                "SK": "METADATA",
                "prefillCode": "PACK123-FALL-IL-25",
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdBy": "user-123-456",  # Match test account ID
                "createdByName": "Test User",
                "creatorMessage": "Old message",
                "description": "Old description",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }

        updated_item = {
            **existing_item["Item"],
            "creatorMessage": "New message",
            "description": "New description",
        }

        mock_table.get_item.return_value = existing_item
        mock_table.update_item.return_value = {"Attributes": updated_item}

        event = {
            **appsync_event,
            "arguments": {
                "prefillCode": "PACK123-FALL-IL-25",
                "creatorMessage": "New message",
                "description": "New description",
            },
        }

        # Act
        result = update_campaign_prefill(event, lambda_context)

        # Assert
        assert result["creatorMessage"] == "New message"
        assert result["description"] == "New description"
        mock_table.update_item.assert_called_once()

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_update_campaign_prefill_authorization_failure(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-creator cannot update prefill."""
        # Arrange
        mock_table.get_item.return_value = {
            "Item": {
                "prefillCode": "PACK123-FALL-IL-25",
                "createdBy": "different-account-id",  # Different from caller
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdByName": "Other User",
                "creatorMessage": "",
                "description": "",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }

        event = {
            **appsync_event,
            "arguments": {
                "prefillCode": "PACK123-FALL-IL-25",
                "creatorMessage": "Trying to hijack",
            },
        }

        # Act & Assert
        with pytest.raises(AuthorizationError) as exc_info:
            update_campaign_prefill(event, lambda_context)

        assert "permission" in str(exc_info.value).lower()

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_update_campaign_prefill_message_too_long(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that update with message >300 chars is rejected."""
        # Arrange
        mock_table.get_item.return_value = {
            "Item": {
                "prefillCode": "PACK123-FALL-IL-25",
                "createdBy": "user-123-456",  # Match test account ID
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdByName": "Test User",
                "creatorMessage": "Old",
                "description": "",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }

        event = {
            **appsync_event,
            "arguments": {
                "prefillCode": "PACK123-FALL-IL-25",
                "creatorMessage": "A" * 301,
            },
        }

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            update_campaign_prefill(event, lambda_context)

        assert "300 characters" in str(exc_info.value)


class TestDeleteCampaignPrefill:
    """Tests for delete_campaign_prefill Lambda handler."""

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_delete_campaign_prefill_success(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test successful soft delete of campaign prefill."""
        # Arrange
        mock_table.get_item.return_value = {
            "Item": {
                "prefillCode": "PACK123-FALL-IL-25",
                "createdBy": "user-123-456",  # Match test account ID
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdByName": "Test User",
                "creatorMessage": "",
                "description": "",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }
        mock_table.update_item.return_value = {}

        event = {
            **appsync_event,
            "arguments": {"prefillCode": "PACK123-FALL-IL-25"},
        }

        # Act
        result = delete_campaign_prefill(event, lambda_context)

        # Assert
        assert result is True
        # Verify soft delete (update, not delete)
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args
        assert "isActive" in call_args.kwargs["UpdateExpression"]

    @patch("src.handlers.campaign_prefill_operations.prefills_table")
    def test_delete_campaign_prefill_authorization_failure(
        self,
        mock_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-creator cannot delete prefill."""
        # Arrange
        mock_table.get_item.return_value = {
            "Item": {
                "prefillCode": "PACK123-FALL-IL-25",
                "createdBy": "different-account-id",
                "catalogId": "CATALOG#test",
                "seasonName": "Fall",
                "seasonYear": 2025,
                "unitType": "Pack",
                "unitNumber": 123,
                "city": "Springfield",
                "state": "IL",
                "createdByName": "Other User",
                "creatorMessage": "",
                "description": "",
                "createdAt": "2025-01-01T00:00:00Z",
                "isActive": True,
            }
        }

        event = {
            **appsync_event,
            "arguments": {"prefillCode": "PACK123-FALL-IL-25"},
        }

        # Act & Assert
        with pytest.raises(AuthorizationError) as exc_info:
            delete_campaign_prefill(event, lambda_context)

        assert "permission" in str(exc_info.value).lower()
