"""Unit tests for list_unit_catalogs Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.list_unit_catalogs import list_unit_catalogs


class TestListUnitCatalogs:
    """Tests for list_unit_catalogs Lambda handler."""

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for list unit catalogs request."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "seasonName": "Fall",
                "seasonYear": 2024,
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def lambda_context(self) -> MagicMock:
        """Mock Lambda context."""
        context = MagicMock()
        context.function_name = "list_unit_catalogs"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def sample_profiles(self) -> list[Dict[str, Any]]:
        """Sample profiles in a unit."""
        return [
            {
                "profileId": "PROFILE#profile1",
                "ownerAccountId": "test-account-123",
                "sellerName": "Scout 1",
                "unitType": "Pack",
                "unitNumber": 158,
            },
            {
                "profileId": "PROFILE#profile2",
                "ownerAccountId": "test-account-456",
                "sellerName": "Scout 2",
                "unitType": "Pack",
                "unitNumber": 158,
            },
        ]

    @pytest.fixture
    def sample_seasons(self) -> list[Dict[str, Any]]:
        """Sample seasons for profiles."""
        return [
            {
                "seasonId": "SEASON#season1",
                "profileId": "PROFILE#profile1",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
            },
            {
                "seasonId": "SEASON#season2",
                "profileId": "PROFILE#profile2",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-456",
            },
        ]

    @pytest.fixture
    def sample_catalogs(self) -> Dict[str, Dict[str, Any]]:
        """Sample catalogs by ID."""
        return {
            "catalog-123": {
                "catalogId": "catalog-123",
                "catalogName": "Alpha Catalog",
                "isActive": True,
            },
            "catalog-456": {
                "catalogId": "catalog-456",
                "catalogName": "Zebra Catalog",
                "isActive": True,
            },
        }

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_success(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test successful catalog listing with multiple profiles."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True

        # Track which profile is being queried
        query_call_count = [0]

        def query_side_effect(**kwargs: Any) -> Dict[str, Any]:
            query_call_count[0] += 1
            if query_call_count[0] == 1:
                return {
                    "Items": [
                        {
                            "seasonId": "SEASON#season1",
                            "profileId": "PROFILE#profile1",
                            "catalogId": "catalog-123",
                        }
                    ]
                }
            else:
                return {
                    "Items": [
                        {
                            "seasonId": "SEASON#season2",
                            "profileId": "PROFILE#profile2",
                            "catalogId": "catalog-456",
                        }
                    ]
                }

        mock_seasons_table.query.side_effect = query_side_effect

        # Return catalogs
        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id in sample_catalogs:
                return {"Item": sample_catalogs[catalog_id]}
            return {}

        mock_catalogs_table.get_item.side_effect = get_item_side_effect

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 2
        # Sorted by catalog name
        assert result[0]["catalogName"] == "Alpha Catalog"
        assert result[1]["catalogName"] == "Zebra Catalog"

    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_no_profiles(
        self,
        mock_profiles_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test listing when no profiles found in unit."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": []}

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_no_access(
        self,
        mock_profiles_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has no access to any profiles."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = False

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []
        assert mock_check_access.call_count == 2  # Called for each profile

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_no_seasons(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when profiles exist but no matching seasons."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True
        mock_seasons_table.query.return_value = {"Items": []}

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_season_without_catalog(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when seasons exist but without catalog IDs."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True
        # Season without catalogId
        mock_seasons_table.query.return_value = {
            "Items": [{"seasonId": "SEASON#season1", "profileId": "PROFILE#profile1"}]
        }

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_duplicate_catalogs(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test that duplicate catalog IDs are deduplicated."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True
        # Both profiles use the same catalog
        mock_seasons_table.query.return_value = {
            "Items": [{"seasonId": "SEASON#season1", "catalogId": "catalog-123"}]
        }
        mock_catalogs_table.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_catalog_fetch_error(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test graceful handling when catalog fetch fails."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles[:1]}  # Single profile
        mock_check_access.return_value = True
        mock_seasons_table.query.return_value = {
            "Items": [
                {"seasonId": "SEASON#season1", "catalogId": "catalog-123"},
                {"seasonId": "SEASON#season2", "catalogId": "catalog-fail"},
            ]
        }

        # First catalog succeeds, second fails
        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id == "catalog-123":
                return {"Item": sample_catalogs["catalog-123"]}
            raise Exception("DynamoDB error")

        mock_catalogs_table.get_item.side_effect = get_item_side_effect

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert - Should return the successful catalog despite the error
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_catalog_not_found(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test handling when catalog doesn't exist in table."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles[:1]}
        mock_check_access.return_value = True
        mock_seasons_table.query.return_value = {
            "Items": [{"seasonId": "SEASON#season1", "catalogId": "catalog-deleted"}]
        }
        mock_catalogs_table.get_item.return_value = {}  # No Item key = not found

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_error_handling(
        self,
        mock_profiles_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test error handling when DynamoDB operation fails."""
        # Arrange
        mock_profiles_table.scan.side_effect = Exception("DynamoDB error")

        # Act & Assert
        with pytest.raises(Exception, match="DynamoDB error"):
            list_unit_catalogs(event, lambda_context)

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_partial_access(
        self,
        mock_profiles_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has access to only some profiles."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}

        # Grant access only to first profile
        def check_access_side_effect(
            caller_account_id: str, profile_id: str, required_permission: str
        ) -> bool:
            return profile_id == "PROFILE#profile1"

        mock_check_access.side_effect = check_access_side_effect

        # Act & Assert - Won't raise, will process only accessible profile
        # The function will continue to query seasons for the accessible profile
        # Since we haven't mocked seasons_table, this will raise
        # We verify check_access was called correctly
        with patch("src.handlers.list_unit_catalogs.seasons_table") as mock_seasons_table:
            mock_seasons_table.query.return_value = {"Items": []}
            result = list_unit_catalogs(event, lambda_context)

        # Verify both profiles checked but only one accessible
        assert mock_check_access.call_count == 2
        assert result == []  # No seasons found for accessible profile

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.seasons_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_season_with_non_string_catalog_id(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test handling when season has non-string catalog ID (edge case)."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles[:1]}
        mock_check_access.return_value = True
        # Season with non-string catalogId (should be filtered out)
        mock_seasons_table.query.return_value = {
            "Items": [
                {"seasonId": "SEASON#season1", "catalogId": 12345},  # Non-string
                {"seasonId": "SEASON#season2", "catalogId": None},  # None
            ]
        }

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert - No valid catalog IDs, so empty result
        assert result == []
        # get_item should not be called since no valid catalog IDs
        mock_catalogs_table.get_item.assert_not_called()
