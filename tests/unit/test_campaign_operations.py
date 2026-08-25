"""Unit tests for campaign_operations Lambda handler."""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.campaign_operations import (
    _build_unit_campaign_key,
    _to_dynamo_value,
    create_campaign,
)
from src.utils.errors import AppError, ErrorCode


class TestBuildUnitCampaignKey:
    """Tests for _build_unit_campaign_key helper function."""

    def test_build_unit_campaign_key_basic(self) -> None:
        """Test building a standard unit campaign key."""
        result = _build_unit_campaign_key(
            unit_type="Pack",
            unit_number=158,
            city="Springfield",
            state="IL",
            campaign_name="Fall",
            campaign_year=2024,
        )
        assert result == "Pack#158#Springfield#IL#Fall#2024"

    def test_build_unit_campaign_key_troop(self) -> None:
        """Test building unit campaign key for Troop."""
        result = _build_unit_campaign_key(
            unit_type="Troop",
            unit_number=42,
            city="Denver",
            state="CO",
            campaign_name="Spring",
            campaign_year=2025,
        )
        assert result == "Troop#42#Denver#CO#Spring#2025"


class TestToDynamoValue:
    """Tests for _to_dynamo_value helper function."""

    def test_to_dynamo_value_string(self) -> None:
        """Test converting a string."""
        result = _to_dynamo_value("test")
        assert result == {"S": "test"}

    def test_to_dynamo_value_int(self) -> None:
        """Test converting an integer."""
        result = _to_dynamo_value(42)
        assert result == {"N": "42"}

    def test_to_dynamo_value_float(self) -> None:
        """Test converting a float."""
        result = _to_dynamo_value(3.14)
        assert result == {"N": "3.14"}

    def test_to_dynamo_value_decimal(self) -> None:
        """Test converting a Decimal to a DynamoDB number (not a string)."""
        result = _to_dynamo_value(Decimal("2024"))
        assert result == {"N": "2024"}

    def test_to_dynamo_value_bool_true(self) -> None:
        """Test converting boolean true."""
        result = _to_dynamo_value(True)
        assert result == {"BOOL": True}

    def test_to_dynamo_value_bool_false(self) -> None:
        """Test converting boolean false."""
        result = _to_dynamo_value(False)
        assert result == {"BOOL": False}

    def test_to_dynamo_value_none(self) -> None:
        """Test converting None."""
        result = _to_dynamo_value(None)
        assert result == {"NULL": True}

    def test_to_dynamo_value_string_list(self) -> None:
        """Test converting a list of strings to DynamoDB L type to preserve order/duplicates."""
        result = _to_dynamo_value(["a", "b", "c"])
        assert result == {"L": [{"S": "a"}, {"S": "b"}, {"S": "c"}]}

    def test_to_dynamo_value_empty_list(self) -> None:
        """Test converting an empty list to DynamoDB L type (not invalid SS)."""
        result = _to_dynamo_value([])
        assert result == {"L": []}

    def test_to_dynamo_value_mixed_list(self) -> None:
        """Test converting a list of mixed types."""
        result = _to_dynamo_value(["a", 1, True])
        assert result == {"L": [{"S": "a"}, {"N": "1"}, {"BOOL": True}]}

    def test_to_dynamo_value_dict(self) -> None:
        """Test converting a dictionary."""
        result = _to_dynamo_value({"key": "value", "count": 5})
        assert result == {"M": {"key": {"S": "value"}, "count": {"N": "5"}}}

    def test_to_dynamo_value_custom_object(self) -> None:
        """Test converting a custom object falls back to string."""

        class CustomObj:
            def __str__(self) -> str:
                return "custom_string"

        result = _to_dynamo_value(CustomObj())
        assert result == {"S": "custom_string"}


class TestCreateCampaign:
    """Tests for create_campaign Lambda handler."""

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for create campaign request."""
        return {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "catalogId": "catalog-abc",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def event_with_shared_campaign(self) -> Dict[str, Any]:
        """Sample AppSync event with shared campaign code."""
        return {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "sharedCampaignCode": "PACK158FALL2024",
                    "shareWithCreator": True,
                }
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def event_with_unit_fields(self) -> Dict[str, Any]:
        """Sample AppSync event with explicit unit fields."""
        return {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "catalogId": "catalog-abc",
                    "unitType": "Pack",
                    "unitNumber": 158,
                    "city": "Springfield",
                    "state": "IL",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def lambda_context(self) -> MagicMock:
        """Mock Lambda context."""
        context = MagicMock()
        context.function_name = "campaign_operations"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def sample_profile(self) -> Dict[str, Any]:
        """Sample profile."""
        return {
            "profileId": "PROFILE#profile-123",
            "ownerAccountId": "ACCOUNT#test-account-123",  # Stored with ACCOUNT# prefix in DynamoDB
            "sellerName": "Test Scout",
            "unitType": "Pack",
            "unitNumber": 158,
        }

    @pytest.fixture
    def sample_shared_campaign(self) -> Dict[str, Any]:
        """Sample campaign sharedCampaign."""
        return {
            "sharedCampaignCode": "PACK158FALL2024",
            "SK": "METADATA",
            "campaignName": "Fall",
            "campaignYear": 2024,
            "catalogId": "catalog-sharedCampaign",
            "unitType": "Pack",
            "unitNumber": 158,
            "city": "Springfield",
            "state": "IL",
            "startDate": "2024-09-01T00:00:00Z",
            "endDate": "2024-12-31T00:00:00Z",
            "createdBy": "leader-account-456",
            "isActive": True,
        }

    @pytest.fixture
    def sample_catalog(self) -> Dict[str, Any]:
        """Sample catalog referenced by shared campaigns."""
        return {
            "catalogId": "CATALOG#catalog-sharedCampaign",
            "catalogName": "Shared Campaign Catalog",
            "isDeleted": False,
        }

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_success_basic(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test successful campaign creation with basic fields."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Act
        result = create_campaign(event, lambda_context)

        # Assert
        assert result["profileId"] == "PROFILE#profile-123"
        assert result["campaignName"] == "Fall"
        assert result["campaignYear"] == 2024
        assert result["catalogId"] == "CATALOG#catalog-abc"
        assert result["campaignId"].startswith("CAMPAIGN#")
        mock_dynamodb_client.transact_write_items.assert_called_once()

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_unit_fields_creates_unit_campaign_key(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_unit_fields: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test campaign creation with unit fields populates unitCampaignKey."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Act
        result = create_campaign(event_with_unit_fields, lambda_context)

        # Assert
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 158
        assert result["city"] == "Springfield"
        assert result["state"] == "IL"
        assert result["unitCampaignKey"] == "Pack#158#Springfield#IL#Fall#2024"

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_accepts_raw_profile_id(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test that create_campaign works when input profileId is a raw UUID (no PROFILE# prefix)."""
        # Arrange: event with raw profileId
        event = {
            "arguments": {
                "input": {
                    "profileId": "profile-123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "catalogId": "catalog-abc",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        mock_check_access.return_value = True
        # _get_profile should be capable of finding profile even when input is raw
        mock_get_profile.return_value = sample_profile

        # Act
        result = create_campaign(event, lambda_context)

        # Assert: campaign stored with the PROFILE# prefixed profileId in campaigns table
        assert result["profileId"] == sample_profile["profileId"]
        assert result["campaignName"] == "Fall"
        mock_dynamodb_client.transact_write_items.assert_called_once()

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_shared_campaign_success(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
        sample_catalog: Dict[str, Any],
    ) -> None:
        """Test campaign creation from shared campaign with share creation."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {"Item": sample_catalog}

        # Act
        result = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Campaign uses Shared Campaign data
        assert result["campaignName"] == "Fall"
        assert result["campaignYear"] == 2024
        assert result["catalogId"] == "CATALOG#catalog-sharedCampaign"
        assert result["unitCampaignKey"] == "Pack#158#Springfield#IL#Fall#2024"
        assert result["sharedCampaignCode"] == "PACK158FALL2024"

        # Assert - Transaction includes both campaign and share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 2  # Campaign + Share

        # Assert - The share uses the PROFILE# prefixed profileId in the shares table
        share_put = transact_items[1].get("Put")
        assert share_put is not None
        # DynamoDB item format uses {'S': '...'} for string attributes
        assert share_put["Item"]["profileId"]["S"] == sample_profile["profileId"]
        # targetAccountId and GSI1PK must be single-prefixed, never double-prefixed
        assert share_put["Item"]["targetAccountId"]["S"] == "ACCOUNT#leader-account-456"
        assert share_put["Item"]["GSI1PK"]["S"] == "ACCOUNT#leader-account-456"

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_shared_campaign_no_share_if_owner_is_creator(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
        sample_catalog: Dict[str, Any],
    ) -> None:
        """Test no share created when profile owner is shared campaign creator."""
        # Arrange - Profile owner is the same as Shared Campaign creator
        # ownerAccountId is stored with ACCOUNT# prefix, but createdBy is just the account ID
        owner_account_id_normalized = sample_profile["ownerAccountId"].replace("ACCOUNT#", "")
        sample_shared_campaign["createdBy"] = owner_account_id_normalized
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {"Item": sample_catalog}

        # Act
        _ = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Transaction only includes campaign, no share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 1  # Only campaign

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_no_share_when_created_by_has_account_prefix(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
        sample_catalog: Dict[str, Any],
    ) -> None:
        """Test share guard still fires when createdBy is stored with ACCOUNT# prefix."""
        # Arrange - createdBy uses the same prefixed form as ownerAccountId
        sample_shared_campaign["createdBy"] = sample_profile["ownerAccountId"]
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {"Item": sample_catalog}

        # Act
        _ = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Transaction only includes campaign, no self-share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 1  # Only campaign

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_share_has_single_prefix_when_created_by_prefixed(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
        sample_catalog: Dict[str, Any],
    ) -> None:
        """Test targetAccountId/GSI1PK are single-prefixed when createdBy already has ACCOUNT# prefix."""
        # Arrange - createdBy already includes ACCOUNT# prefix
        sample_shared_campaign["createdBy"] = "ACCOUNT#leader-account-456"
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {"Item": sample_catalog}

        # Act
        _ = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Transaction includes campaign and share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 2

        share_put = transact_items[1].get("Put")
        assert share_put is not None
        # Must not double-prefix
        assert share_put["Item"]["targetAccountId"]["S"] == "ACCOUNT#leader-account-456"
        assert share_put["Item"]["GSI1PK"]["S"] == "ACCOUNT#leader-account-456"
        assert "ACCOUNT#ACCOUNT#" not in share_put["Item"]["GSI1PK"]["S"]

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_not_found(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign code doesn't exist."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = None  # Shared campaign not found

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* not found"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_inactive(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign is no longer active."""
        # Arrange
        sample_shared_campaign["isActive"] = False
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* is no longer active"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_catalog_deleted(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign's catalog has been deleted."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {
            "Item": {"catalogId": "CATALOG#catalog-sharedCampaign", "isDeleted": True}
        }

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* is no longer available"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_catalog_missing(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign's catalog no longer exists."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {}

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* is no longer available"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_catalog_id_missing(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign has no catalogId."""
        # Arrange
        sample_shared_campaign.pop("catalogId", None)
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* is no longer available"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_catalog_lookup_fails(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_tables: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test error when shared campaign's catalog lookup fails."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.side_effect = Exception("DynamoDB unavailable")

        # Act & Assert
        with pytest.raises(AppError, match="Shared Campaign .* is no longer available"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations.tables")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_duplicate_share_retry(
        self,
        mock_get_profile: MagicMock,
        mock_tables: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
        sample_catalog: Dict[str, Any],
    ) -> None:
        """Test that duplicate share creation is handled by retrying without share."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign
        mock_tables.catalogs.get_item.return_value = {"Item": sample_catalog}

        # Mock the transact_write_items to fail on first call (share already exists)
        # Create a real-like exception
        mock_exception = Exception("TransactionCanceledException")
        mock_exception.response = {"CancellationReasons": [{"Code": "ConditionalCheckFailed"}]}

        # Create a proper exception type mock
        exception_type = type("TransactionCanceledException", (Exception,), {})
        mock_dynamodb_client.exceptions.TransactionCanceledException = exception_type

        # Create instance that looks like the exception
        instance = exception_type("Transaction cancelled")
        instance.response = {"CancellationReasons": [{"Code": "ConditionalCheckFailed"}]}

        # First call raises exception, second call succeeds
        mock_dynamodb_client.transact_write_items.side_effect = [instance, None]

        # Act
        result = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Campaign was created
        assert result["campaignName"] == "Fall"
        assert "campaignId" in result

        # Assert - transact_write_items was called twice (first failed, retry succeeded)
        assert mock_dynamodb_client.transact_write_items.call_count == 2

    @patch("src.handlers.campaign_operations.check_profile_access")
    def test_create_campaign_no_access(
        self,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test permission error when caller lacks write access."""
        # Arrange
        mock_check_access.return_value = False

        # Act & Assert
        with pytest.raises(AppError, match="You do not have permission"):
            create_campaign(event, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_profile_not_found(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Test error when profile doesn't exist."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = None

        # Act & Assert
        with pytest.raises(AppError, match="Profile .* not found"):
            create_campaign(event, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_missing_required_fields(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test validation errors for missing required fields."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Test missing campaignName
        event = {
            "arguments": {"input": {"profileId": "PROFILE#123"}},
            "identity": {"sub": "test-account-123"},
        }
        with pytest.raises(AppError, match="campaign_name is required"):
            create_campaign(event, lambda_context)

        # Test missing campaignYear
        event["arguments"]["input"]["campaignName"] = "Fall"
        with pytest.raises(AppError, match="campaign_year is required"):
            create_campaign(event, lambda_context)

        # Test missing catalogId
        event["arguments"]["input"]["campaignYear"] = 2024
        with pytest.raises(AppError, match="catalog_id is required"):
            create_campaign(event, lambda_context)

    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_unit_field_validation(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test validation when unit fields are incomplete."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        base_event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                    "startDate": "2024-09-01T00:00:00Z",
                    "unitType": "Pack",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Test unitType without unitNumber
        with pytest.raises(AppError, match="unitNumber is required"):
            create_campaign(base_event, lambda_context)

        # Test with unitNumber but without city
        base_event["arguments"]["input"]["unitNumber"] = 158
        with pytest.raises(AppError, match="city is required"):
            create_campaign(base_event, lambda_context)

        # Test with city but without state
        base_event["arguments"]["input"]["city"] = "Springfield"
        with pytest.raises(AppError, match="state is required"):
            create_campaign(base_event, lambda_context)

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_invalid_unit_number_format(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test validation when unitNumber is not a valid integer."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                    "startDate": "2024-09-01T00:00:00Z",
                    "unitType": "Pack",
                    "unitNumber": "not-a-number",
                    "city": "Springfield",
                    "state": "IL",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Act & Assert
        with pytest.raises(AppError, match="unitNumber must be a valid integer"):
            create_campaign(event, lambda_context)

    @pytest.mark.skip(reason="TODO: Fix mock setup for shared_campaigns_table - mocking not working as expected")
    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations.shared_campaigns_table")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_share_already_exists_retries(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_shared_campaign: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test that transaction retries without share when share already exists."""
        from botocore.exceptions import ClientError

        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

        # Create a proper TransactionCanceledException mock
        transaction_exception = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Transaction cancelled",
                },
                "CancellationReasons": [{"Code": "None"}, {"Code": "ConditionalCheckFailed"}],
            },
            "TransactWriteItems",
        )
        # Add the response attribute that the code checks
        transaction_exception.response = {  # type: ignore[attr-defined]
            "CancellationReasons": [{"Code": "None"}, {"Code": "ConditionalCheckFailed"}]
        }

        # Configure the mock to raise the exception on first call, succeed on second
        mock_dynamodb_client.transact_write_items.side_effect = [transaction_exception, None]
        # Configure the exception type so isinstance check works
        mock_dynamodb_client.exceptions.TransactionCanceledException = ClientError

        # Act
        _ = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Transaction was retried
        assert mock_dynamodb_client.transact_write_items.call_count == 2
        # Second call should have only 1 item (campaign only)
        second_call = mock_dynamodb_client.transact_write_items.call_args_list[1]
        transact_items = second_call.kwargs.get("TransactItems") or second_call[1].get("TransactItems")
        assert len(transact_items) == 1

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_transaction_error_propagates(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test that non-conditional transaction errors propagate."""
        from botocore.exceptions import ClientError

        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Simulate a different kind of transaction error (no ConditionalCheckFailed)
        transaction_exception = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Transaction cancelled",
                },
                "CancellationReasons": [{"Code": "ThrottlingError"}],
            },
            "TransactWriteItems",
        )
        transaction_exception.response = {  # type: ignore[attr-defined]
            "CancellationReasons": [{"Code": "ThrottlingError"}]
        }

        mock_dynamodb_client.transact_write_items.side_effect = transaction_exception
        mock_dynamodb_client.exceptions.TransactionCanceledException = ClientError

        # Act & Assert
        with pytest.raises(ClientError):
            create_campaign(event, lambda_context)

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_generic_error_is_wrapped(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test that unexpected errors during creation are wrapped as INTERNAL_ERROR AppError."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_dynamodb_client.transact_write_items.side_effect = TypeError("Unexpected failure")

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            create_campaign(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to create campaign" in str(exc_info.value.message)

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_end_date(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test campaign creation with optional end date."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "endDate": "2024-12-31T00:00:00Z",
                    "catalogId": "catalog-abc",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Act
        result = create_campaign(event, lambda_context)

        # Assert
        assert result["endDate"] == "2024-12-31T00:00:00Z"

    @pytest.mark.skip(reason="TODO: Fix mock setup for shared_campaigns_table - mocking not working as expected")
    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations.shared_campaigns_table")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_dates_can_be_overridden(
        self,
        mock_get_profile: MagicMock,
        mock_get_shared_campaign: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_shared_campaign: Dict[str, Any],
    ) -> None:
        """Test that input dates can override shared campaign dates."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

        event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "sharedCampaignCode": "PACK158FALL2024",
                    "startDate": "2024-10-01T00:00:00Z",  # Override Shared Campaign date
                    "endDate": "2024-11-30T00:00:00Z",  # Override Shared Campaign date
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Act
        result = create_campaign(event, lambda_context)

        # Assert - Input dates used instead of Shared Campaign dates
        assert result["startDate"] == "2024-10-01T00:00:00Z"
        assert result["endDate"] == "2024-11-30T00:00:00Z"


class TestGetSharedCampaign:
    """Tests for _get_shared_campaign helper function."""

    def test_get_shared_campaign_success(self) -> None:
        """Test successful shared campaign retrieval."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"sharedCampaignCode": "TEST123", "campaignName": "Fall"}}

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.shared_campaigns = mock_table
            result = _get_shared_campaign("TEST123")

        assert result is not None
        assert result["sharedCampaignCode"] == "TEST123"

    def test_get_shared_campaign_not_found(self) -> None:
        """Test shared campaign not found returns None."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.shared_campaigns = mock_table
            result = _get_shared_campaign("NONEXISTENT")

        assert result is None

    def test_get_shared_campaign_error(self) -> None:
        """Test shared campaign error returns None."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_table = MagicMock()
        mock_table.get_item.side_effect = Exception("DynamoDB error")

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.shared_campaigns = mock_table
            result = _get_shared_campaign("TEST123")

        assert result is None


class TestGetProfile:
    """Tests for _get_profile helper function."""

    def test_get_profile_success(self) -> None:
        """Test successful profile retrieval."""
        from src.handlers.campaign_operations import _get_profile

        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [{"profileId": "PROFILE#123", "sellerName": "Test"}]}

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.profiles = mock_table
            result = _get_profile("PROFILE#123")

        assert result is not None
        assert result["profileId"] == "PROFILE#123"

    def test_get_profile_not_found(self) -> None:
        """Test profile not found returns None."""
        from src.handlers.campaign_operations import _get_profile

        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.profiles = mock_table
            result = _get_profile("NONEXISTENT")

        assert result is None

    def test_get_profile_error(self) -> None:
        """Test profile error returns None."""
        from src.handlers.campaign_operations import _get_profile

        mock_table = MagicMock()
        mock_table.query.side_effect = Exception("DynamoDB error")

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.profiles = mock_table
            result = _get_profile("PROFILE#123")

        assert result is None


class TestDynamoDBClient:
    """Tests for the module-level DynamoDB client helper."""

    def test_get_dynamodb_client_initializes_when_none(self) -> None:
        """Test that _get_dynamodb_client creates a client when cache is empty."""
        from src.handlers import campaign_operations

        campaign_operations._dynamodb_client = None
        with patch("src.handlers.campaign_operations.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()
            result = campaign_operations._get_dynamodb_client()

        assert result is mock_client.return_value
        mock_client.assert_called_once_with("dynamodb")

    def test_get_dynamodb_client_returns_cached(self) -> None:
        """Test that _get_dynamodb_client returns the cached client if present."""
        from src.handlers import campaign_operations

        cached = MagicMock()
        campaign_operations._dynamodb_client = cached
        with patch("src.handlers.campaign_operations.boto3.client") as mock_client:
            result = campaign_operations._get_dynamodb_client()

        assert result is cached
        mock_client.assert_not_called()


class TestDeleteCampaignOrders:
    """Tests for delete_campaign_orders Lambda handler."""

    _OWNER_SUB = "owner-sub-001"

    @staticmethod
    def _seed_owned_campaign(
        profiles_table: Any,
        campaigns_table: Any,
        profile_id: str,
        campaign_id: str,
        owner_sub: str,
    ) -> None:
        """Seed a profile owned by owner_sub and a campaign on that profile."""
        profiles_table.put_item(
            Item={
                "ownerAccountId": f"ACCOUNT#{owner_sub}",
                "profileId": profile_id,
                "profileName": f"Profile {profile_id}",
            }
        )
        campaigns_table.put_item(
            Item={
                "profileId": profile_id,
                "campaignId": campaign_id,
                "campaignName": "Test Campaign",
                "campaignYear": 2024,
            }
        )

    @staticmethod
    def _event(campaign_id: str, caller_sub: str) -> Dict[str, Any]:
        return {
            "arguments": {"campaignId": campaign_id},
            "identity": {"sub": caller_sub},
        }

    def test_delete_campaign_orders_success(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting all orders for a campaign owned by the caller."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#campaign-123"
        profile_id = "PROFILE#profile-123"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        for i in range(5):
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": f"ORDER#{i}",
                    "customerName": f"Customer {i}",
                    "totalAmount": Decimal("10.0"),
                }
            )

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 5}
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 0

    def test_delete_campaign_orders_chunks_batches(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting more than 25 orders chunks deletes into batches."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#campaign-many"
        profile_id = "PROFILE#profile-many"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        for i in range(30):
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": f"ORDER#{i}",
                    "customerName": f"Customer {i}",
                    "totalAmount": Decimal("10.0"),
                }
            )

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 30}
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 0

    def test_delete_campaign_orders_empty(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting orders for a campaign with no orders."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#campaign-empty"
        profile_id = "PROFILE#profile-empty"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 0}

    def test_delete_campaign_orders_unprefixed_id(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that an unprefixed campaignId is normalized."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#campaign-raw"
        profile_id = "PROFILE#profile-raw"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer",
                "totalAmount": Decimal("10.0"),
            }
        )

        result = delete_campaign_orders(self._event("campaign-raw", self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 1}

    def test_delete_campaign_orders_missing_campaign_id(
        self,
        lambda_context: Any,
    ) -> None:
        """Test that missing campaignId raises an error."""
        from src.handlers.campaign_operations import delete_campaign_orders

        event = {"arguments": {}, "identity": {"sub": self._OWNER_SUB}}
        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_delete_campaign_orders_missing_identity(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that missing caller identity raises UNAUTHORIZED."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#no-identity"
        profile_id = "PROFILE#no-identity"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders({"arguments": {"campaignId": campaign_id}}, lambda_context)

        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_delete_campaign_orders_campaign_not_found(
        self,
        campaigns_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that deleting a nonexistent campaign raises NOT_FOUND."""
        from src.handlers.campaign_operations import delete_campaign_orders

        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(self._event("CAMPAIGN#ghost", self._OWNER_SUB), lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_delete_campaign_orders_campaign_missing_profile_id(
        self,
        lambda_context: Any,
    ) -> None:
        """Test that a campaign row with no profileId raises NOT_FOUND."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#no-profile"
        with patch(
            "src.handlers.campaign_operations._get_campaign_by_id",
            return_value={"campaignId": campaign_id, "campaignName": "Orphan"},
        ):
            with pytest.raises(AppError) as exc_info:
                delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_delete_campaign_orders_denied_non_owner(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that a non-owner caller without a WRITE share is denied."""
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#owned-by-other"
        profile_id = "PROFILE#owned-by-other"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer",
                "totalAmount": Decimal("10.0"),
            }
        )

        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(self._event(campaign_id, "intruder-sub"), lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 1

    def test_delete_campaign_orders_only_targets_requested_campaign(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that orders for other campaigns are not deleted."""
        from src.handlers.campaign_operations import delete_campaign_orders

        target_campaign = "CAMPAIGN#target"
        other_campaign = "CAMPAIGN#other"
        target_profile = "PROFILE#target"
        other_profile = "PROFILE#other"
        self._seed_owned_campaign(profiles_table, campaigns_table, target_profile, target_campaign, self._OWNER_SUB)
        self._seed_owned_campaign(profiles_table, campaigns_table, other_profile, other_campaign, self._OWNER_SUB)

        orders_table.put_item(
            Item={
                "campaignId": target_campaign,
                "orderId": "ORDER#target",
                "customerName": "Target",
                "totalAmount": Decimal("10.0"),
            }
        )
        orders_table.put_item(
            Item={
                "campaignId": other_campaign,
                "orderId": "ORDER#other",
                "customerName": "Other",
                "totalAmount": Decimal("10.0"),
            }
        )

        result = delete_campaign_orders(self._event(target_campaign, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 1}
        assert (
            orders_table.get_item(Key={"campaignId": other_campaign, "orderId": "ORDER#other"}).get("Item") is not None
        )

    def test_delete_campaign_orders_unexpected_error(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that unexpected errors are wrapped in an INTERNAL_ERROR AppError."""
        from src.handlers.admin_operations import AppError, ErrorCode
        from src.handlers.campaign_operations import delete_campaign_orders

        campaign_id = "CAMPAIGN#any"
        profile_id = "PROFILE#any"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        with patch("src.handlers.campaign_operations._delete_orders_for_campaign") as mock_delete:
            mock_delete.side_effect = RuntimeError("unexpected failure")

            with pytest.raises(AppError) as exc_info:
                delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete campaign orders" in exc_info.value.message
