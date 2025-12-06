"""
Tests for season operations Lambda handlers.

Tests season update and delete functionality:
- updateSeason
- deleteSeason
"""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.handlers.season_operations import delete_season, update_season
from src.utils.errors import AppError, ErrorCode


class TestUpdateSeason:
    """Tests for update_season handler."""

    def test_owner_can_update_season(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_season: Dict[str, Any],
        sample_season_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile owner can update season."""
        # Arrange
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": sample_season_id,
                "name": "Updated Season Name",
            },
        }

        # Act
        result = update_season(event, lambda_context)

        # Assert
        assert result["name"] == "Updated Season Name"
        assert result["seasonId"] == sample_season_id
        assert "updatedAt" in result

        # Verify update in DynamoDB
        response = dynamodb_table.get_item(
            Key={"PK": sample_season["PK"], "SK": sample_season["SK"]}
        )
        assert response["Item"]["name"] == "Updated Season Name"

    def test_update_start_and_end_dates(
        self,
        dynamodb_table: Any,
        sample_season: Dict[str, Any],
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test updating season dates."""
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": sample_season_id,
                "startDate": "2026-01-01",
                "endDate": "2026-03-31",
            },
        }

        result = update_season(event, lambda_context)

        assert result["startDate"] == "2026-01-01"
        assert result["endDate"] == "2026-03-31"

    def test_can_remove_end_date(
        self,
        dynamodb_table: Any,
        sample_season: Dict[str, Any],
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that endDate can be set to null."""
        # First add an endDate
        dynamodb_table.update_item(
            Key={"PK": sample_season["PK"], "SK": sample_season["SK"]},
            UpdateExpression="SET endDate = :endDate",
            ExpressionAttributeValues={":endDate": "2026-03-31"},
        )

        # Now remove it
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": sample_season_id,
                "endDate": None,
            },
        }

        result = update_season(event, lambda_context)

        assert "endDate" not in result

    def test_contributor_with_write_can_update(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_season: Dict[str, Any],
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with WRITE permission can update season."""
        # Create share with WRITE permission
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ", "WRITE"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "seasonId": sample_season_id,
                "name": "Updated by Contributor",
            },
        }

        result = update_season(event, lambda_context)

        assert result["name"] == "Updated by Contributor"

    def test_contributor_with_read_only_cannot_update(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with only READ permission cannot update."""
        # Create share with READ permission only
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "seasonId": sample_season_id,
                "name": "Should Fail",
            },
        }

        result = update_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "FORBIDDEN"

    def test_non_existent_season_returns_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that updating non-existent season returns error."""
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": "SEASON#nonexistent",
                "name": "Should Fail",
            },
        }

        result = update_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "NOT_FOUND"

    def test_empty_name_returns_validation_error(
        self,
        dynamodb_table: Any,
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that empty name returns validation error."""
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": sample_season_id,
                "name": "",
            },
        }

        result = update_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "INVALID_INPUT"

    def test_update_catalog_id(
        self,
        dynamodb_table: Any,
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test updating catalogId."""
        event = {
            **appsync_event,
            "arguments": {
                "seasonId": sample_season_id,
                "catalogId": "CATALOG#new-catalog",
            },
        }

        result = update_season(event, lambda_context)

        assert result["catalogId"] == "CATALOG#new-catalog"


class TestDeleteSeason:
    """Tests for delete_season handler."""

    def test_owner_can_delete_season(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_season: Dict[str, Any],
        sample_season_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile owner can delete season."""
        # Arrange
        event = {
            **appsync_event,
            "arguments": {"seasonId": sample_season_id},
        }

        # Act
        result = delete_season(event, lambda_context)

        # Assert
        assert result["success"] is True

        # Verify soft delete in DynamoDB
        response = dynamodb_table.get_item(
            Key={"PK": sample_season["PK"], "SK": sample_season["SK"]}
        )
        assert response["Item"]["deleted"] is True
        assert "deletedAt" in response["Item"]

    def test_cannot_delete_season_with_orders(
        self,
        dynamodb_table: Any,
        sample_season: Dict[str, Any],
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that season with orders cannot be deleted."""
        # Create an order for this season
        dynamodb_table.put_item(
            Item={
                "PK": sample_season["PK"],
                "SK": "ORDER#test-order",
                "orderId": "ORDER#test-order",
                "seasonId": sample_season_id,
                "customerName": "Test Customer",
            }
        )

        event = {
            **appsync_event,
            "arguments": {"seasonId": sample_season_id},
        }

        result = delete_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "CONFLICT"
        assert "orders" in result["message"].lower()

    def test_contributor_with_write_can_delete(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_season: Dict[str, Any],
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with WRITE permission can delete season."""
        # Create share with WRITE permission
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ", "WRITE"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"seasonId": sample_season_id},
        }

        result = delete_season(event, lambda_context)

        assert result["success"] is True

    def test_contributor_with_read_only_cannot_delete(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_season_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with only READ permission cannot delete."""
        # Create share with READ permission only
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"seasonId": sample_season_id},
        }

        result = delete_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "FORBIDDEN"

    def test_non_existent_season_returns_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that deleting non-existent season returns error."""
        event = {
            **appsync_event,
            "arguments": {"seasonId": "SEASON#nonexistent"},
        }

        result = delete_season(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "NOT_FOUND"
