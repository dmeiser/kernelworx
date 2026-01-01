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
                "campaignName": "Fall",
                "campaignYear": 2024,
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
    def sample_campaigns(self) -> list[Dict[str, Any]]:
        """Sample campaigns for profiles."""
        return [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "catalog-123",
            },
            {
                "campaignId": "CAMPAIGN#campaign2",
                "profileId": "PROFILE#profile2",
                "campaignName": "Fall",
                "campaignYear": 2024,
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
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_success(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
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
                            "campaignId": "CAMPAIGN#campaign1",
                            "profileId": "PROFILE#profile1",
                            "catalogId": "catalog-123",
                        }
                    ]
                }
            else:
                return {
                    "Items": [
                        {
                            "campaignId": "CAMPAIGN#campaign2",
                            "profileId": "PROFILE#profile2",
                            "catalogId": "catalog-456",
                        }
                    ]
                }

        mock_campaigns_table.query.side_effect = query_side_effect

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
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_no_campaigns(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when profiles exist but no matching campaigns."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True
        mock_campaigns_table.query.return_value = {"Items": []}

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_campaign_without_catalog(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when campaigns exist but without catalog IDs."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True
        # Campaign without catalogId
        mock_campaigns_table.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "profileId": "PROFILE#profile1"}]
        }

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_duplicate_catalogs(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
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
        mock_campaigns_table.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-123"}]
        }
        mock_catalogs_table.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_catalog_fetch_error(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
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
        mock_campaigns_table.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-123"},
                {"campaignId": "CAMPAIGN#campaign2", "catalogId": "catalog-fail"},
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
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_catalog_not_found(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
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
        mock_campaigns_table.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-deleted"}]
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
        def check_access_side_effect(caller_account_id: str, profile_id: str, required_permission: str) -> bool:
            return profile_id == "PROFILE#profile1"

        mock_check_access.side_effect = check_access_side_effect

        # Act & Assert - Won't raise, will process only accessible profile
        # The function will continue to query campaigns for the accessible profile
        # Since we haven't mocked campaigns_table, this will raise
        # We verify check_access was called correctly
        with patch("src.handlers.list_unit_catalogs.campaigns_table") as mock_campaigns_table:
            mock_campaigns_table.query.return_value = {"Items": []}
            result = list_unit_catalogs(event, lambda_context)

        # Verify both profiles checked but only one accessible
        assert mock_check_access.call_count == 2
        assert result == []  # No campaigns found for accessible profile

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    @patch("src.handlers.list_unit_catalogs.profiles_table")
    def test_list_unit_catalogs_campaign_with_non_string_catalog_id(
        self,
        mock_profiles_table: MagicMock,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test handling when campaign has non-string catalog ID (edge case)."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles[:1]}
        mock_check_access.return_value = True
        # Campaign with non-string catalogId (should be filtered out)
        mock_campaigns_table.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "catalogId": 12345},  # Non-string
                {"campaignId": "CAMPAIGN#campaign2", "catalogId": None},  # None
            ]
        }

        # Act
        result = list_unit_catalogs(event, lambda_context)

        # Assert - No valid catalog IDs, so empty result
        assert result == []
        # get_item should not be called since no valid catalog IDs
        mock_catalogs_table.get_item.assert_not_called()


class TestListUnitCampaignCatalogs:
    """Tests for list_unit_campaign_catalogs Lambda handler using unitCampaignKey-index."""

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for list unit campaign catalogs request."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def lambda_context(self) -> MagicMock:
        """Mock Lambda context."""
        context = MagicMock()
        context.function_name = "list_unit_campaign_catalogs"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def sample_campaigns(self) -> list[Dict[str, Any]]:
        """Sample campaigns from unitCampaignKey-index query."""
        return [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "catalogId": "catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            },
            {
                "campaignId": "CAMPAIGN#campaign2",
                "profileId": "PROFILE#profile2",
                "catalogId": "catalog-456",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
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
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_success(
        self,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test successful catalog listing using unitCampaignKey-index."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}
        mock_check_access.return_value = True

        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id in sample_catalogs:
                return {"Item": sample_catalogs[catalog_id]}
            return {}

        mock_catalogs_table.get_item.side_effect = get_item_side_effect

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 2
        # Sorted by catalog name
        assert result[0]["catalogName"] == "Alpha Catalog"
        assert result[1]["catalogName"] == "Zebra Catalog"
        # Verify unitCampaignKey-index was queried
        mock_campaigns_table.query.assert_called_once()
        call_kwargs = mock_campaigns_table.query.call_args.kwargs
        assert call_kwargs["IndexName"] == "unitCampaignKey-index"

    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_no_campaigns(
        self,
        mock_campaigns_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test listing when no campaigns found in unitCampaignKey-index."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": []}

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_no_access(
        self,
        mock_campaigns_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has no access to any profiles."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}
        mock_check_access.return_value = False

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert result == []
        assert mock_check_access.call_count == 2

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_partial_access(
        self,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test listing when caller has access to only some profiles."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        # Grant access only to first profile
        def check_access_side_effect(caller_account_id: str, profile_id: str, required_permission: str) -> bool:
            return profile_id == "PROFILE#profile1"

        mock_check_access.side_effect = check_access_side_effect
        mock_catalogs_table.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - Only catalog from accessible profile
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_duplicate_catalogs(
        self,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test that duplicate catalog IDs are deduplicated."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange - Both campaigns use the same catalog
        campaigns = [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "catalogId": "catalog-123",
            },
            {
                "campaignId": "CAMPAIGN#campaign2",
                "profileId": "PROFILE#profile2",
                "catalogId": "catalog-123",
            },
        ]
        mock_campaigns_table.query.return_value = {"Items": campaigns}
        mock_check_access.return_value = True
        mock_catalogs_table.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_catalog_fetch_error(
        self,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test graceful handling when catalog fetch fails."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}
        mock_check_access.return_value = True

        # First catalog succeeds, second fails
        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id == "catalog-123":
                return {"Item": sample_catalogs["catalog-123"]}
            raise Exception("DynamoDB error")

        mock_catalogs_table.get_item.side_effect = get_item_side_effect

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - Should return the successful catalog
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_error_handling(
        self,
        mock_campaigns_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test error handling when unitCampaignKey-index query fails."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.side_effect = Exception("DynamoDB error")

        # Act & Assert
        with pytest.raises(Exception, match="DynamoDB error"):
            list_unit_campaign_catalogs(event, lambda_context)

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_campaign_without_catalog(
        self,
        mock_campaigns_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test handling when campaigns don't have catalog IDs."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "profileId": "PROFILE#profile1"},  # No catalogId
                {"campaignId": "CAMPAIGN#campaign2", "profileId": "PROFILE#profile2", "catalogId": None},
            ]
        }
        mock_check_access.return_value = True

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert result == []

    @patch("src.handlers.list_unit_catalogs.check_profile_access")
    @patch("src.handlers.list_unit_catalogs.catalogs_table")
    @patch("src.handlers.list_unit_catalogs.campaigns_table")
    def test_list_unit_campaign_catalogs_catalog_not_found(
        self,
        mock_campaigns_table: MagicMock,
        mock_catalogs_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
    ) -> None:
        """Test handling when catalog doesn't exist in table."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}
        mock_check_access.return_value = True
        # Catalog not found - empty response without Item key
        mock_catalogs_table.get_item.return_value = {}

        # Act
        result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - No catalogs returned since none found
        assert result == []
