"""Unit tests for campaign_operations Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from src.handlers.campaign_operations import (
    _build_unit_campaign_key,
    _to_dynamo_value,
    create_campaign,
)


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
        """Test converting a list of strings (converted to set for DynamoDB SS type)."""
        result = _to_dynamo_value(["a", "b", "c"])
        # boto3 expects a set for the SS (String Set) DynamoDB type
        assert result == {"SS": {"a", "b", "c"}}

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
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_shared_campaign_success(
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
        """Test campaign creation from shared campaign with share creation."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

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

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_with_shared_campaign_no_share_if_owner_is_creator(
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
        """Test no share created when profile owner is shared campaign creator."""
        # Arrange - Profile owner is the same as Shared Campaign creator
        # ownerAccountId is stored with ACCOUNT# prefix, but createdBy is just the account ID
        owner_account_id_normalized = sample_profile["ownerAccountId"].replace("ACCOUNT#", "")
        sample_shared_campaign["createdBy"] = owner_account_id_normalized
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

        # Act
        _ = create_campaign(event_with_shared_campaign, lambda_context)

        # Assert - Transaction only includes campaign, no share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 1  # Only campaign

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
        with pytest.raises(ValueError, match="Shared Campaign .* not found"):
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
        with pytest.raises(ValueError, match="Shared Campaign .* is no longer active"):
            create_campaign(event_with_shared_campaign, lambda_context)

    @patch("src.handlers.campaign_operations.dynamodb_client")
    @patch("src.handlers.campaign_operations.check_profile_access")
    @patch("src.handlers.campaign_operations._get_shared_campaign")
    @patch("src.handlers.campaign_operations._get_profile")
    def test_create_campaign_shared_campaign_duplicate_share_retry(
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
        """Test that duplicate share creation is handled by retrying without share."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_shared_campaign.return_value = sample_shared_campaign

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
        with pytest.raises(PermissionError, match="You do not have permission"):
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
        with pytest.raises(ValueError, match="Profile .* not found"):
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
        with pytest.raises(ValueError, match="campaignName is required"):
            create_campaign(event, lambda_context)

        # Test missing campaignYear
        event["arguments"]["input"]["campaignName"] = "Fall"
        with pytest.raises(ValueError, match="campaignYear is required"):
            create_campaign(event, lambda_context)

        # Test missing catalogId
        event["arguments"]["input"]["campaignYear"] = 2024
        with pytest.raises(ValueError, match="catalogId is required"):
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
        with pytest.raises(ValueError, match="unitNumber is required"):
            create_campaign(base_event, lambda_context)

        # Test with unitNumber but without city
        base_event["arguments"]["input"]["unitNumber"] = 158
        with pytest.raises(ValueError, match="city is required"):
            create_campaign(base_event, lambda_context)

        # Test with city but without state
        base_event["arguments"]["input"]["city"] = "Springfield"
        with pytest.raises(ValueError, match="state is required"):
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
        with pytest.raises(ValueError, match="unitNumber must be a valid integer"):
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

    @patch("src.handlers.campaign_operations.shared_campaigns_table")
    def test_get_shared_campaign_success(self, mock_shared_campaigns_table: MagicMock) -> None:
        """Test successful shared campaign retrieval."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_shared_campaigns_table.get_item.return_value = {
            "Item": {"sharedCampaignCode": "TEST123", "campaignName": "Fall"}
        }

        result = _get_shared_campaign("TEST123")

        assert result is not None
        assert result["sharedCampaignCode"] == "TEST123"

    @patch("src.handlers.campaign_operations.shared_campaigns_table")
    def test_get_shared_campaign_not_found(self, mock_shared_campaigns_table: MagicMock) -> None:
        """Test shared campaign not found returns None."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_shared_campaigns_table.get_item.return_value = {}

        result = _get_shared_campaign("NONEXISTENT")

        assert result is None

    @patch("src.handlers.campaign_operations.shared_campaigns_table")
    def test_get_shared_campaign_error(self, mock_shared_campaigns_table: MagicMock) -> None:
        """Test shared campaign error returns None."""
        from src.handlers.campaign_operations import _get_shared_campaign

        mock_shared_campaigns_table.get_item.side_effect = Exception("DynamoDB error")

        result = _get_shared_campaign("TEST123")

        assert result is None


class TestGetProfile:
    """Tests for _get_profile helper function."""

    @patch("src.handlers.campaign_operations.profiles_table")
    def test_get_profile_success(self, mock_profiles_table: MagicMock) -> None:
        """Test successful profile retrieval."""
        from src.handlers.campaign_operations import _get_profile

        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#123", "sellerName": "Test"}]}

        result = _get_profile("PROFILE#123")

        assert result is not None
        assert result["profileId"] == "PROFILE#123"

    @patch("src.handlers.campaign_operations.profiles_table")
    def test_get_profile_not_found(self, mock_profiles_table: MagicMock) -> None:
        """Test profile not found returns None."""
        from src.handlers.campaign_operations import _get_profile

        mock_profiles_table.query.return_value = {"Items": []}

        result = _get_profile("NONEXISTENT")

        assert result is None

    @patch("src.handlers.campaign_operations.profiles_table")
    def test_get_profile_error(self, mock_profiles_table: MagicMock) -> None:
        """Test profile error returns None."""
        from src.handlers.campaign_operations import _get_profile

        mock_profiles_table.query.side_effect = Exception("DynamoDB error")

        result = _get_profile("PROFILE#123")

        assert result is None
