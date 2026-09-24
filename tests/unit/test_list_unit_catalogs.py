"""Unit tests for list_unit_catalogs Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.list_unit_catalogs import _fetch_catalogs, list_unit_catalogs
from src.utils.errors import AppError, ErrorCode


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

    @pytest.fixture(autouse=True)
    def mock_dynamodb_resource(self, sample_catalogs: Dict[str, Dict[str, Any]]):
        """Mock DynamoDB resource for BatchGetItem."""
        mock_resource = MagicMock()

        def batch_get_side_effect(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems.keys()))
            keys = RequestItems[table_name].get("Keys", [])
            items = [sample_catalogs[k["catalogId"]] for k in keys if k["catalogId"] in sample_catalogs]
            return {"Responses": {table_name: items}, "UnprocessedKeys": {}}

        mock_resource.batch_get_item.side_effect = batch_get_side_effect
        with patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource):
            yield mock_resource

    def test_list_unit_catalogs_success(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test successful catalog listing with multiple profiles."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()

        # Arrange
        mock_profiles.query.return_value = {"Items": sample_profiles}

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

        mock_campaigns.query.side_effect = query_side_effect

        # Return catalogs
        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id in sample_catalogs:
                return {"Item": sample_catalogs[catalog_id]}
            return {}

        mock_catalogs.get_item.side_effect = get_item_side_effect

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 2
        # Sorted by catalog name
        assert result[0]["catalogName"] == "Alpha Catalog"
        assert result[1]["catalogName"] == "Zebra Catalog"

    def test_list_unit_catalogs_no_profiles(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test listing when no profiles found in unit."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_profiles.query.return_value = {"Items": []}

        with patch("src.handlers.list_unit_catalogs.tables") as mock_tables:
            mock_tables.profiles = mock_profiles

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_catalogs_no_access(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has no access to any profiles."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_check_access.return_value = set()

            # Act
            result = list_unit_catalogs(event, lambda_context)

            # Assert
            assert result == []
            assert mock_check_access.call_count == 1  # Called once for all profiles

    def test_list_unit_catalogs_no_campaigns(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when profiles exist but no matching campaigns."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles}
        mock_campaigns.query.return_value = {"Items": []}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_catalogs_campaign_without_catalog(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when campaigns exist but without catalog IDs."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles}
        # Campaign without catalogId
        mock_campaigns.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "profileId": "PROFILE#profile1"}]
        }

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_catalogs_duplicate_catalogs(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test that duplicate catalog IDs are deduplicated."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles}
        # Both profiles use the same catalog
        mock_campaigns.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-123"}]
        }
        mock_catalogs.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    def test_list_unit_catalogs_catalog_fetch_error(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        mock_dynamodb_resource: MagicMock,
    ) -> None:
        """Test error handling when catalog fetch fails."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles[:1]}  # Single profile
        mock_campaigns.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-123"},
                {"campaignId": "CAMPAIGN#campaign2", "catalogId": "catalog-fail"},
            ]
        }

        mock_dynamodb_resource.batch_get_item.side_effect = Exception("DynamoDB error")

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert - Should return error response
        assert result.get("__isError") is True
        assert result.get("errorCode") == "INTERNAL_ERROR"

    def test_list_unit_catalogs_catalog_not_found(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test handling when catalog doesn't exist in table."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles[:1]}
        mock_campaigns.query.return_value = {
            "Items": [{"campaignId": "CAMPAIGN#campaign1", "catalogId": "catalog-deleted"}]
        }
        mock_catalogs.get_item.return_value = {}  # No Item key = not found

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_catalogs_error_handling(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test error handling when DynamoDB operation fails."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_profiles.query.side_effect = Exception("DynamoDB error")

        with patch("src.handlers.list_unit_catalogs.tables") as mock_tables:
            mock_tables.profiles = mock_profiles

            # Act & Assert: the with_error_handling decorator converts the
            # unexpected DynamoDB error into an INTERNAL_ERROR error payload.
            result = list_unit_catalogs(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == "INTERNAL_ERROR"
            assert result["message"] == "Failed to list unit catalogs"

    def test_list_unit_catalogs_partial_access(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has access to only some profiles."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles}
        mock_campaigns.query.return_value = {"Items": []}

        # Grant access only to first profile
        def check_access_side_effect(
            caller_account_id: str, profile_ids: list[str], required_permission: str
        ) -> set[str]:
            return {pid for pid in profile_ids if pid == "PROFILE#profile1"}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_check_access.side_effect = check_access_side_effect

            # Act
            result = list_unit_catalogs(event, lambda_context)

            # Verify both profiles checked but only one accessible
            assert mock_check_access.call_count == 1  # Called once for all profiles
            assert result == []  # No campaigns found for accessible profile

    def test_list_unit_catalogs_campaign_with_non_string_catalog_id(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profiles: list[Dict[str, Any]],
    ) -> None:
        """Test handling when campaign has non-string catalog ID (edge case)."""
        # Create mock tables
        mock_profiles = MagicMock()
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_profiles.query.return_value = {"Items": sample_profiles[:1]}
        # Campaign with non-string catalogId (should be filtered out)
        mock_campaigns.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "catalogId": 12345},  # Non-string
                {"campaignId": "CAMPAIGN#campaign2", "catalogId": None},  # None
            ]
        }

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_catalogs(event, lambda_context)

        # Assert - No valid catalog IDs, so empty result
        assert result == []
        # get_item should not be called since no valid catalog IDs
        mock_catalogs.get_item.assert_not_called()


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

    @pytest.fixture(autouse=True)
    def mock_dynamodb_resource(self, sample_catalogs: Dict[str, Dict[str, Any]]):
        """Mock DynamoDB resource for BatchGetItem."""
        mock_resource = MagicMock()

        def batch_get_side_effect(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems.keys()))
            keys = RequestItems[table_name].get("Keys", [])
            items = [sample_catalogs[k["catalogId"]] for k in keys if k["catalogId"] in sample_catalogs]
            return {"Responses": {table_name: items}, "UnprocessedKeys": {}}

        mock_resource.batch_get_item.side_effect = batch_get_side_effect
        with patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource):
            yield mock_resource

    def test_list_unit_campaign_catalogs_success(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test successful catalog listing using unitCampaignKey-index."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_campaigns.query.return_value = {"Items": sample_campaigns}

        def get_item_side_effect(**kwargs: Any) -> Dict[str, Any]:
            catalog_id = kwargs["Key"]["catalogId"]
            if catalog_id in sample_catalogs:
                return {"Item": sample_catalogs[catalog_id]}
            return {}

        mock_catalogs.get_item.side_effect = get_item_side_effect

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

            # Assert
            assert len(result) == 2
            # Sorted by catalog name
            assert result[0]["catalogName"] == "Alpha Catalog"
            assert result[1]["catalogName"] == "Zebra Catalog"
            # Verify unitCampaignKey-index was queried
            mock_campaigns.query.assert_called_once()
            call_kwargs = mock_campaigns.query.call_args.kwargs
            assert call_kwargs["IndexName"] == "unitCampaignKey-index"

    def test_list_unit_campaign_catalogs_no_campaigns(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test listing when no campaigns found in unitCampaignKey-index."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_campaigns.query.return_value = {"Items": []}

        with patch("src.handlers.list_unit_catalogs.tables") as mock_tables:
            mock_tables.campaigns = mock_campaigns

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_campaign_catalogs_no_access(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
    ) -> None:
        """Test listing when caller has no access to any profiles."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_campaigns.query.return_value = {"Items": sample_campaigns}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_check_access.return_value = set()

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

            # Assert
            assert result == []
            assert mock_check_access.call_count == 1  # Called once for all profiles

    def test_list_unit_campaign_catalogs_partial_access(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test listing when caller has access to only some profiles."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_campaigns.query.return_value = {"Items": sample_campaigns}
        mock_catalogs.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        # Grant access only to first profile
        def check_access_side_effect(
            caller_account_id: str, profile_ids: list[str], required_permission: str
        ) -> set[str]:
            return {pid for pid in profile_ids if pid == "PROFILE#profile1"}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = check_access_side_effect

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - Only catalog from accessible profile
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    def test_list_unit_campaign_catalogs_duplicate_catalogs(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_catalogs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Test that duplicate catalog IDs are deduplicated."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()

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
        mock_campaigns.query.return_value = {"Items": campaigns}
        mock_catalogs.get_item.return_value = {"Item": sample_catalogs["catalog-123"]}

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"

    def test_list_unit_campaign_catalogs_catalog_fetch_error(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        mock_dynamodb_resource: MagicMock,
    ) -> None:
        """Test error handling when catalog fetch fails."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_campaigns.query.return_value = {"Items": sample_campaigns}

        mock_dynamodb_resource.batch_get_item.side_effect = Exception("DynamoDB error")

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - Should return error response
        assert result.get("__isError") is True
        assert result.get("errorCode") == "INTERNAL_ERROR"

    def test_list_unit_campaign_catalogs_error_handling(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test error handling when unitCampaignKey-index query fails."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_campaigns.query.side_effect = Exception("DynamoDB error")

        with patch("src.handlers.list_unit_catalogs.tables") as mock_tables:
            mock_tables.campaigns = mock_campaigns

            # Act & Assert: the with_error_handling decorator converts the
            # unexpected DynamoDB error into an INTERNAL_ERROR error payload.
            result = list_unit_campaign_catalogs(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == "INTERNAL_ERROR"
            assert result["message"] == "Failed to list unit campaign catalogs"

    def test_list_unit_campaign_catalogs_campaign_without_catalog(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test handling when campaigns don't have catalog IDs."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_campaigns.query.return_value = {
            "Items": [
                {"campaignId": "CAMPAIGN#campaign1", "profileId": "PROFILE#profile1"},  # No catalogId
                {"campaignId": "CAMPAIGN#campaign2", "profileId": "PROFILE#profile2", "catalogId": None},
            ]
        }

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert
        assert result == []

    def test_list_unit_campaign_catalogs_catalog_not_found(
        self,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_campaigns: list[Dict[str, Any]],
        mock_dynamodb_resource: MagicMock,
    ) -> None:
        """Test handling when catalog doesn't exist in table."""
        from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

        # Create mock tables
        mock_campaigns = MagicMock()
        mock_catalogs = MagicMock()
        mock_campaigns.query.return_value = {"Items": sample_campaigns}
        # Catalog not found - empty response without Item key
        mock_dynamodb_resource.batch_get_item.side_effect = None
        mock_dynamodb_resource.batch_get_item.return_value = {
            "Responses": {"kernelworx-catalogs-ue1-dev": []},
            "UnprocessedKeys": {},
        }

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns
            mock_tables.catalogs = mock_catalogs
            mock_check_access.side_effect = lambda caller_account_id, profile_ids, required_permission="READ": set(
                profile_ids
            )

            # Act
            result = list_unit_campaign_catalogs(event, lambda_context)

        # Assert - No catalogs returned since none found
        assert result == []


class TestFetchCatalogsBatching:
    """Dedicated tests for chunked BatchGetItem in _fetch_catalogs (#450)."""

    def test_fetch_catalogs_empty_set(self) -> None:
        """Empty catalog_ids returns empty list with zero BatchGetItem calls."""
        with patch("src.handlers.list_unit_catalogs.get_dynamodb_resource") as mock_resource:
            result = _fetch_catalogs(set())
            assert result == []
            mock_resource.assert_not_called()

    def test_fetch_catalogs_chunking_over_100(self) -> None:
        """More than 100 catalog IDs are split into 100-key chunks."""
        catalog_ids = {f"cat-{i:03d}" for i in range(150)}
        mock_resource = MagicMock()

        def batch_get_side_effect(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems.keys()))
            keys = RequestItems[table_name]["Keys"]
            items = [{"catalogId": k["catalogId"], "catalogName": f"Catalog {k['catalogId']}"} for k in keys]
            return {"Responses": {table_name: items}, "UnprocessedKeys": {}}

        mock_resource.batch_get_item.side_effect = batch_get_side_effect

        with patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource):
            result = _fetch_catalogs(catalog_ids)

        assert len(result) == 150
        assert mock_resource.batch_get_item.call_count == 2
        call_keys_0 = mock_resource.batch_get_item.call_args_list[0][1]["RequestItems"]["kernelworx-catalogs-ue1-dev"][
            "Keys"
        ]
        call_keys_1 = mock_resource.batch_get_item.call_args_list[1][1]["RequestItems"]["kernelworx-catalogs-ue1-dev"][
            "Keys"
        ]
        assert len(call_keys_0) == 100
        assert len(call_keys_1) == 50

    def test_fetch_catalogs_retry_unprocessed_keys(self) -> None:
        """Unprocessed keys are retried with backoff and successfully fetched."""
        catalog_ids = {"cat-1", "cat-2"}
        mock_resource = MagicMock()
        attempts = [0]

        def batch_get_side_effect(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems.keys()))
            attempts[0] += 1
            if attempts[0] == 1:
                return {
                    "Responses": {table_name: [{"catalogId": "cat-1", "catalogName": "Cat 1"}]},
                    "UnprocessedKeys": {table_name: {"Keys": [{"catalogId": "cat-2"}]}},
                }
            else:
                return {
                    "Responses": {table_name: [{"catalogId": "cat-2", "catalogName": "Cat 2"}]},
                    "UnprocessedKeys": {},
                }

        mock_resource.batch_get_item.side_effect = batch_get_side_effect

        with (
            patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource),
            patch("time.sleep") as mock_sleep,
        ):
            result = _fetch_catalogs(catalog_ids)

        assert len(result) == 2
        assert mock_resource.batch_get_item.call_count == 2
        mock_sleep.assert_called_once_with(0.05)

    def test_fetch_catalogs_unprocessed_keys_exhausted(self) -> None:
        """AppError(INTERNAL_ERROR) is raised if keys remain unprocessed after 3 attempts."""
        catalog_ids = {"cat-1"}
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {"kernelworx-catalogs-ue1-dev": []},
            "UnprocessedKeys": {"kernelworx-catalogs-ue1-dev": {"Keys": [{"catalogId": "cat-1"}]}},
        }

        with (
            patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource),
            patch("time.sleep"),
            pytest.raises(AppError) as exc_info,
        ):
            _fetch_catalogs(catalog_ids)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "DynamoDB BatchGetItem failed to return 1 keys after retries" in exc_info.value.message

    def test_fetch_catalogs_throttling_error(self) -> None:
        """ClientError with ThrottlingException raises AppError(RESOURCE_BUSY)."""
        from botocore.exceptions import ClientError

        mock_resource = MagicMock()
        error_response = {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}
        mock_resource.batch_get_item.side_effect = ClientError(error_response, "BatchGetItem")

        with (
            patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource),
            pytest.raises(AppError) as exc_info,
        ):
            _fetch_catalogs({"cat-1"})

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_fetch_catalogs_generic_client_error(self) -> None:
        """Generic ClientError raises AppError(INTERNAL_ERROR)."""
        from botocore.exceptions import ClientError

        mock_resource = MagicMock()
        error_response = {"Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}}
        mock_resource.batch_get_item.side_effect = ClientError(error_response, "BatchGetItem")

        with (
            patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource),
            pytest.raises(AppError) as exc_info,
        ):
            _fetch_catalogs({"cat-1"})

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_fetch_catalogs_table_name_from_accessor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Table name falls back to tables.catalogs.table_name when env var is absent."""
        monkeypatch.delenv("CATALOGS_TABLE_NAME", raising=False)
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {"custom-catalogs-table": []},
            "UnprocessedKeys": {},
        }

        with (
            patch("src.handlers.list_unit_catalogs.tables") as mock_tables,
            patch("src.handlers.list_unit_catalogs.get_dynamodb_resource", return_value=mock_resource),
        ):
            mock_tables.catalogs.table_name = "custom-catalogs-table"
            _fetch_catalogs({"cat-1"})

        call_request_items = mock_resource.batch_get_item.call_args[1]["RequestItems"]
        assert "custom-catalogs-table" in call_request_items
