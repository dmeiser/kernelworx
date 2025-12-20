"""Unit tests for season_operations Lambda handler."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.season_operations import (
    _build_unit_season_key,
    _to_dynamo_value,
    create_season,
)


class TestBuildUnitSeasonKey:
    """Tests for _build_unit_season_key helper function."""

    def test_build_unit_season_key_basic(self) -> None:
        """Test building a standard unit season key."""
        result = _build_unit_season_key(
            unit_type="Pack",
            unit_number=158,
            city="Springfield",
            state="IL",
            season_name="Fall",
            season_year=2024,
        )
        assert result == "Pack#158#Springfield#IL#Fall#2024"

    def test_build_unit_season_key_troop(self) -> None:
        """Test building unit season key for Troop."""
        result = _build_unit_season_key(
            unit_type="Troop",
            unit_number=42,
            city="Denver",
            state="CO",
            season_name="Spring",
            season_year=2025,
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
        """Test converting a list of strings."""
        result = _to_dynamo_value(["a", "b", "c"])
        assert result == {"SS": ["a", "b", "c"]}

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


class TestCreateSeason:
    """Tests for create_season Lambda handler."""

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for create season request."""
        return {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "seasonName": "Fall",
                    "seasonYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "catalogId": "catalog-abc",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def event_with_prefill(self) -> Dict[str, Any]:
        """Sample AppSync event with prefill code."""
        return {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "prefillCode": "PACK158FALL2024",
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
                    "seasonName": "Fall",
                    "seasonYear": 2024,
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
        context.function_name = "season_operations"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def sample_profile(self) -> Dict[str, Any]:
        """Sample profile."""
        return {
            "profileId": "PROFILE#profile-123",
            "ownerAccountId": "test-account-123",
            "sellerName": "Test Scout",
            "unitType": "Pack",
            "unitNumber": 158,
        }

    @pytest.fixture
    def sample_prefill(self) -> Dict[str, Any]:
        """Sample campaign prefill."""
        return {
            "prefillCode": "PACK158FALL2024",
            "seasonName": "Fall",
            "seasonYear": 2024,
            "catalogId": "catalog-prefill",
            "unitType": "Pack",
            "unitNumber": 158,
            "city": "Springfield",
            "state": "IL",
            "startDate": "2024-09-01T00:00:00Z",
            "endDate": "2024-12-31T00:00:00Z",
            "createdBy": "leader-account-456",
            "isActive": True,
        }

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_success_basic(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test successful season creation with basic fields."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Act
        result = create_season(event, lambda_context)

        # Assert
        assert result["profileId"] == "PROFILE#profile-123"
        assert result["seasonName"] == "Fall"
        assert result["seasonYear"] == 2024
        assert result["catalogId"] == "catalog-abc"
        assert result["seasonId"].startswith("SEASON#")
        mock_dynamodb_client.transact_write_items.assert_called_once()

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_with_unit_fields_creates_gsi3_key(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_unit_fields: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test season creation with unit fields populates GSI3 key."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        # Act
        result = create_season(event_with_unit_fields, lambda_context)

        # Assert
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 158
        assert result["city"] == "Springfield"
        assert result["state"] == "IL"
        assert result["unitSeasonKey"] == "Pack#158#Springfield#IL#Fall#2024"

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_with_prefill_success(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_prefill: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_prefill: Dict[str, Any],
    ) -> None:
        """Test season creation from prefill with share creation."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = sample_prefill

        # Act
        result = create_season(event_with_prefill, lambda_context)

        # Assert - Season uses prefill data
        assert result["seasonName"] == "Fall"
        assert result["seasonYear"] == 2024
        assert result["catalogId"] == "catalog-prefill"
        assert result["unitSeasonKey"] == "Pack#158#Springfield#IL#Fall#2024"
        assert result["prefillCode"] == "PACK158FALL2024"

        # Assert - Transaction includes both season and share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 2  # Season + Share

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_with_prefill_no_share_if_owner_is_creator(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_prefill: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_prefill: Dict[str, Any],
    ) -> None:
        """Test no share created when profile owner is prefill creator."""
        # Arrange - Profile owner is the same as prefill creator
        sample_prefill["createdBy"] = sample_profile["ownerAccountId"]
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = sample_prefill

        # Act
        result = create_season(event_with_prefill, lambda_context)

        # Assert - Transaction only includes season, no share
        call_args = mock_dynamodb_client.transact_write_items.call_args
        transact_items = call_args.kwargs.get("TransactItems") or call_args[1].get("TransactItems")
        assert len(transact_items) == 1  # Only season

    @patch("src.handlers.season_operations.check_profile_access")
    def test_create_season_no_access(
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
            create_season(event, lambda_context)

    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_profile_not_found(
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
            create_season(event, lambda_context)

    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_prefill_not_found(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        event_with_prefill: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test error when prefill code doesn't exist."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = None

        # Act & Assert
        with pytest.raises(ValueError, match="Campaign prefill .* not found"):
            create_season(event_with_prefill, lambda_context)

    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_prefill_inactive(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        event_with_prefill: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_prefill: Dict[str, Any],
    ) -> None:
        """Test error when prefill is inactive."""
        # Arrange
        sample_prefill["isActive"] = False
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = sample_prefill

        # Act & Assert
        with pytest.raises(ValueError, match="no longer active"):
            create_season(event_with_prefill, lambda_context)

    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_missing_required_fields(
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

        # Test missing seasonName
        event = {
            "arguments": {"input": {"profileId": "PROFILE#123"}},
            "identity": {"sub": "test-account-123"},
        }
        with pytest.raises(ValueError, match="seasonName is required"):
            create_season(event, lambda_context)

        # Test missing seasonYear
        event["arguments"]["input"]["seasonName"] = "Fall"
        with pytest.raises(ValueError, match="seasonYear is required"):
            create_season(event, lambda_context)

        # Test missing catalogId
        event["arguments"]["input"]["seasonYear"] = 2024
        with pytest.raises(ValueError, match="catalogId is required"):
            create_season(event, lambda_context)

        # Test missing startDate
        event["arguments"]["input"]["catalogId"] = "catalog-123"
        with pytest.raises(ValueError, match="startDate is required"):
            create_season(event, lambda_context)

    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_unit_field_validation(
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
                    "seasonName": "Fall",
                    "seasonYear": 2024,
                    "catalogId": "catalog-123",
                    "startDate": "2024-09-01T00:00:00Z",
                    "unitType": "Pack",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Test unitType without unitNumber
        with pytest.raises(ValueError, match="unitNumber is required"):
            create_season(base_event, lambda_context)

        # Test with unitNumber but without city
        base_event["arguments"]["input"]["unitNumber"] = 158
        with pytest.raises(ValueError, match="city is required"):
            create_season(base_event, lambda_context)

        # Test with city but without state
        base_event["arguments"]["input"]["city"] = "Springfield"
        with pytest.raises(ValueError, match="state is required"):
            create_season(base_event, lambda_context)

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_share_already_exists_retries(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        event_with_prefill: Dict[str, Any],
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_prefill: Dict[str, Any],
    ) -> None:
        """Test that transaction retries without share when share already exists."""
        from botocore.exceptions import ClientError

        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = sample_prefill

        # Create a proper TransactionCanceledException mock
        transaction_exception = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
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
        result = create_season(event_with_prefill, lambda_context)

        # Assert - Transaction was retried
        assert mock_dynamodb_client.transact_write_items.call_count == 2
        # Second call should have only 1 item (season only)
        second_call = mock_dynamodb_client.transact_write_items.call_args_list[1]
        transact_items = second_call.kwargs.get("TransactItems") or second_call[1].get(
            "TransactItems"
        )
        assert len(transact_items) == 1

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_transaction_error_propagates(
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
                "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
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
            create_season(event, lambda_context)

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_with_end_date(
        self,
        mock_get_profile: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
    ) -> None:
        """Test season creation with optional end date."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile

        event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "seasonName": "Fall",
                    "seasonYear": 2024,
                    "startDate": "2024-09-01T00:00:00Z",
                    "endDate": "2024-12-31T00:00:00Z",
                    "catalogId": "catalog-abc",
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Act
        result = create_season(event, lambda_context)

        # Assert
        assert result["endDate"] == "2024-12-31T00:00:00Z"

    @patch("src.handlers.season_operations.dynamodb_client")
    @patch("src.handlers.season_operations.check_profile_access")
    @patch("src.handlers.season_operations._get_prefill")
    @patch("src.handlers.season_operations._get_profile")
    def test_create_season_prefill_dates_can_be_overridden(
        self,
        mock_get_profile: MagicMock,
        mock_get_prefill: MagicMock,
        mock_check_access: MagicMock,
        mock_dynamodb_client: MagicMock,
        lambda_context: MagicMock,
        sample_profile: Dict[str, Any],
        sample_prefill: Dict[str, Any],
    ) -> None:
        """Test that input dates can override prefill dates."""
        # Arrange
        mock_check_access.return_value = True
        mock_get_profile.return_value = sample_profile
        mock_get_prefill.return_value = sample_prefill

        event = {
            "arguments": {
                "input": {
                    "profileId": "PROFILE#profile-123",
                    "prefillCode": "PACK158FALL2024",
                    "startDate": "2024-10-01T00:00:00Z",  # Override prefill date
                    "endDate": "2024-11-30T00:00:00Z",  # Override prefill date
                }
            },
            "identity": {"sub": "test-account-123"},
        }

        # Act
        result = create_season(event, lambda_context)

        # Assert - Input dates used instead of prefill dates
        assert result["startDate"] == "2024-10-01T00:00:00Z"
        assert result["endDate"] == "2024-11-30T00:00:00Z"


class TestGetPrefill:
    """Tests for _get_prefill helper function."""

    @patch("src.handlers.season_operations.prefills_table")
    def test_get_prefill_success(self, mock_prefills_table: MagicMock) -> None:
        """Test successful prefill retrieval."""
        from src.handlers.season_operations import _get_prefill

        mock_prefills_table.get_item.return_value = {
            "Item": {"prefillCode": "TEST123", "seasonName": "Fall"}
        }

        result = _get_prefill("TEST123")

        assert result is not None
        assert result["prefillCode"] == "TEST123"

    @patch("src.handlers.season_operations.prefills_table")
    def test_get_prefill_not_found(self, mock_prefills_table: MagicMock) -> None:
        """Test prefill not found returns None."""
        from src.handlers.season_operations import _get_prefill

        mock_prefills_table.get_item.return_value = {}

        result = _get_prefill("NONEXISTENT")

        assert result is None

    @patch("src.handlers.season_operations.prefills_table")
    def test_get_prefill_error(self, mock_prefills_table: MagicMock) -> None:
        """Test prefill error returns None."""
        from src.handlers.season_operations import _get_prefill

        mock_prefills_table.get_item.side_effect = Exception("DynamoDB error")

        result = _get_prefill("TEST123")

        assert result is None


class TestGetProfile:
    """Tests for _get_profile helper function."""

    @patch("src.handlers.season_operations.profiles_table")
    def test_get_profile_success(self, mock_profiles_table: MagicMock) -> None:
        """Test successful profile retrieval."""
        from src.handlers.season_operations import _get_profile

        mock_profiles_table.get_item.return_value = {
            "Item": {"profileId": "PROFILE#123", "sellerName": "Test"}
        }

        result = _get_profile("PROFILE#123")

        assert result is not None
        assert result["profileId"] == "PROFILE#123"

    @patch("src.handlers.season_operations.profiles_table")
    def test_get_profile_not_found(self, mock_profiles_table: MagicMock) -> None:
        """Test profile not found returns None."""
        from src.handlers.season_operations import _get_profile

        mock_profiles_table.get_item.return_value = {}

        result = _get_profile("NONEXISTENT")

        assert result is None

    @patch("src.handlers.season_operations.profiles_table")
    def test_get_profile_error(self, mock_profiles_table: MagicMock) -> None:
        """Test profile error returns None."""
        from src.handlers.season_operations import _get_profile

        mock_profiles_table.get_item.side_effect = Exception("DynamoDB error")

        result = _get_profile("PROFILE#123")

        assert result is None
