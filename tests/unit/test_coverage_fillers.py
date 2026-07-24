"""Targeted coverage tests for unhit branches and helpers."""

import importlib
import os
import sys
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws


def test_validation_validate_unit_fields_requires_unit_number():
    from src.utils.errors import AppError
    from src.utils.ids import ensure_profile_id
    from src.utils.validation import validate_unit_fields

    with pytest.raises(AppError):
        validate_unit_fields("Pack", None, "City", "ST")

    # Ensure PROFILE# prefixing path is exercised via the centralized utility
    assert ensure_profile_id("abc") == "PROFILE#abc"


def test_campaign_operations_dynamo_value_for_scalar_fallback():
    from src.handlers import campaign_operations

    class CustomObj:
        pass

    obj = CustomObj()
    result = campaign_operations._dynamo_value_for_scalar(obj)
    assert result == {"S": str(obj)}

    # Set branch for collection conversion (sets are now serialized as L, not SS)
    assert campaign_operations._dynamo_value_for_collection({"k": "v"}) == {"M": {"k": {"S": "v"}}}
    result = campaign_operations._dynamo_value_for_collection({"a", "b"})
    assert result.get("L") is not None
    assert len(result["L"]) == 2


def test_pre_signup_handle_signup_exception_returns_event():
    from botocore.exceptions import ClientError

    from src.handlers import pre_signup

    event = {"response": {}}
    returned = pre_signup._handle_signup_exception(Exception("unexpected"), "user@example.com", event)
    assert returned is event

    client_error = ClientError(
        {"Error": {"Code": "InvalidParameterException", "Message": "Link already exists"}},
        "AdminLinkProviderForUser",
    )
    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(client_error, "user@example.com", event)

    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(
            pre_signup.FederatedIdentityLinkedException(
                "Cannot link federated identity: invalid username format"
            ),
            "user@example.com",
            event,
        )


def test_profile_sharing_deduplicate_and_extract_helpers():
    from src.handlers import profile_sharing

    # Deduplicate skips invalid entries and keeps first valid share
    shares = [
        {"profileId": "P1"},
        {"profileId": "P1", "ownerAccountId": "A1"},
        {"profileId": "P1", "ownerAccountId": "A1", "extra": True},
        {"profileId": "P2", "ownerAccountId": 123},
    ]
    deduped = profile_sharing._deduplicate_shares(shares)
    assert deduped == {"P1": {"profileId": "P1", "ownerAccountId": "A1", "permissions": []}}

    # Extract fallback path aggregates responses when table name missing
    batch_response = {"Responses": {"Other": [{"profileId": "P3"}]}}
    extracted = profile_sharing._extract_batch_profiles(batch_response, "ProfilesTable")
    assert extracted == [{"profileId": "P3"}]


def test_profile_sharing_log_unprocessed_and_build_result():
    from src.handlers import profile_sharing

    class DummyLogger:
        def __init__(self) -> None:
            self.warned: list[dict[str, int]] = []

        def warning(self, message: str, **kwargs: int) -> None:
            self.warned.append(kwargs)

    logger = DummyLogger()
    profile_sharing._log_unprocessed_keys({"Profiles": {"Keys": [1, 2, 3]}}, "Profiles", logger)
    assert logger.warned == [{"count": 3}]

    share = {"profileId": "PROFILE#1", "ownerAccountId": "ACCOUNT#owner", "permissions": ["READ"]}
    shares_by_profile = {"PROFILE#1": share}
    # Profile with non-string ownerAccountId but valid required fields
    profile = {
        "profileId": "PROFILE#1",
        "ownerAccountId": 123,  # Non-string
        "sellerName": "Scout",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    }
    result = profile_sharing._build_shared_profile_result(profile, shares_by_profile, "ACCOUNT#caller")
    assert result is not None
    assert result["ownerAccountId"] == "ACCOUNT#"
    assert result["permissions"] == ["READ"]

    # Missing share returns None
    assert (
        profile_sharing._build_shared_profile_result({"profileId": "PROFILE#2"}, shares_by_profile, "ACCOUNT#x") is None
    )

    # Missing required fields returns None
    profile_missing_fields = {"profileId": "PROFILE#1", "ownerAccountId": "ACCOUNT#owner"}
    assert profile_sharing._build_shared_profile_result(profile_missing_fields, shares_by_profile, "ACCOUNT#x") is None

    # Unprocessed keys path when table missing
    logger2 = DummyLogger()
    profile_sharing._log_unprocessed_keys({"Other": {"Keys": [1]}}, "Other", logger2)
    assert logger2.warned == [{"count": 1}]


def test_report_generation_get_s3_client_default(monkeypatch):
    from src.handlers import report_generation

    report_generation.s3_client = None

    created: list[tuple[str, str | None]] = []

    def fake_client(service_name: str, endpoint_url: str | None = None):
        created.append((service_name, endpoint_url))
        return SimpleNamespace()

    monkeypatch.setattr(report_generation.boto3, "client", fake_client)
    client = report_generation._get_s3_client()
    assert created == [("s3", None)]
    assert isinstance(client, SimpleNamespace)

    # When module-level client set, return it directly
    sentinel_client = object()
    report_generation.s3_client = sentinel_client  # type: ignore[assignment]
    assert report_generation._get_s3_client() is sentinel_client
    report_generation.s3_client = None


def test_validation_price_per_unit_type_error():
    from src.utils import validation

    result = validation._validate_single_line_item({"productId": "P1", "quantity": 1, "pricePerUnit": "bad"})
    assert result is not None
    assert result.get("errorCode") == "INVALID_INPUT"

    missing_quantity = validation._validate_single_line_item({"productId": "P1"})
    assert missing_quantity is not None
    assert missing_quantity.get("errorCode") == "INVALID_INPUT"

    bad_quantity = validation._validate_single_line_item({"productId": "P1", "quantity": "a"})
    assert bad_quantity is not None
    assert bad_quantity.get("errorCode") == "INVALID_INPUT"

    valid_item = validation._validate_single_line_item({"productId": "P1", "quantity": 2, "pricePerUnit": 10})
    assert valid_item is None


@mock_aws
def test_transfer_profile_ownership_success(monkeypatch):
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create tables used by handler
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    dynamodb.create_table(
        TableName="SharesTable",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Reload handler so it binds to the moto tables via the current env vars.
    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table("ProfilesTable")
    shares_table = dynamodb.Table("SharesTable")

    # Seed data
    profiles_table.put_item(
        Item={
            "ownerAccountId": "ACCOUNT#owner123",
            "profileId": "PROFILE#abc",
            "sellerName": "Scout",
        }
    )
    shares_table.put_item(
        Item={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456", "permissions": ["READ"]}
    )

    event = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    updated_profile = transfer_module.lambda_handler(event, None)

    assert updated_profile["ownerAccountId"] == "ACCOUNT#new456"
    # Share removed
    assert "Item" not in shares_table.get_item(Key={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456"})


@mock_aws
def test_transfer_profile_ownership_error_paths():
    from src.utils.errors import AppError

    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    dynamodb.create_table(
        TableName="SharesTable",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table("ProfilesTable")
    shares_table = dynamodb.Table("SharesTable")

    profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#owner123", "profileId": "PROFILE#abc"})

    event_base = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    # Missing share triggers AppError
    with pytest.raises(AppError):
        transfer_module.lambda_handler(event_base, None)

    # Seed share but wrong caller triggers AppError
    shares_table.put_item(Item={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456"})
    event_bad_owner = {
        "identity": {"sub": "someoneelse"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }
    with pytest.raises(AppError):
        transfer_module.lambda_handler(event_bad_owner, None)

    # Missing profile triggers AppError
    event_missing_profile = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#missing", "newOwnerAccountId": "new456"}},
    }
    with pytest.raises(AppError):
        transfer_module.lambda_handler(event_missing_profile, None)


@mock_aws
def test_transfer_profile_ownership_admin_transfer():
    """Test admin can transfer profile without share requirement."""
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    dynamodb.create_table(
        TableName="SharesTable",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table("ProfilesTable")

    # Seed profile
    profiles_table.put_item(
        Item={
            "ownerAccountId": "ACCOUNT#owner123",
            "profileId": "PROFILE#abc",
            "sellerName": "Scout",
        }
    )
    # Note: NO share created - admin doesn't need one

    # Admin transfer event
    event = {
        "identity": {
            "sub": "admin-user",
            "claims": {"cognito:groups": ["ADMIN"]},
        },
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    updated_profile = transfer_module.lambda_handler(event, None)

    assert updated_profile["ownerAccountId"] == "ACCOUNT#new456"


@mock_aws
def test_transfer_profile_ownership_share_delete_fails():
    """Test that share deletion failure is handled gracefully."""
    from unittest.mock import MagicMock

    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    dynamodb.create_table(
        TableName="SharesTable",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table("ProfilesTable")
    shares_table = dynamodb.Table("SharesTable")

    # Seed profile and share
    profiles_table.put_item(
        Item={
            "ownerAccountId": "ACCOUNT#owner123",
            "profileId": "PROFILE#abc",
            "sellerName": "Scout",
        }
    )
    shares_table.put_item(
        Item={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456", "permissions": ["READ"]}
    )

    event = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    # Create a mock for shares table that wraps the real table
    # but makes delete_item raise an exception
    mock_shares = MagicMock(wraps=shares_table)
    mock_shares.get_item = shares_table.get_item  # Keep real get_item for validation
    mock_shares.delete_item.side_effect = RuntimeError("Simulated failure")

    # Use the _table_overrides mechanism from dynamodb module
    from src.utils import dynamodb as db_module

    db_module._table_overrides["shares"] = mock_shares

    try:
        # Should succeed despite share deletion failure
        updated_profile = transfer_module.lambda_handler(event, None)
        assert updated_profile["ownerAccountId"] == "ACCOUNT#new456"
    finally:
        # Clean up override
        db_module._table_overrides.pop("shares", None)


@mock_aws
def test_transfer_profile_ownership_source_deleted_race():
    """Transfer must fail if the source profile is deleted between read and transaction."""
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profile = {
        "ownerAccountId": "ACCOUNT#owner123",
        "profileId": "PROFILE#abc",
        "sellerName": "Scout",
    }
    # Do NOT seed the source row; the Delete condition should fail.
    with pytest.raises(Exception):
        transfer_module._transfer_ownership(profile, "PROFILE#abc", "ACCOUNT#new456")


@mock_aws
def test_transfer_profile_ownership_destination_exists_race():
    """Transfer must fail if a profile already exists at the destination key."""
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["PROFILES_TABLE_NAME"] = "ProfilesTable"
    os.environ["SHARES_TABLE_NAME"] = "SharesTable"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="ProfilesTable",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table("ProfilesTable")
    profile = {
        "ownerAccountId": "ACCOUNT#owner123",
        "profileId": "PROFILE#abc",
        "sellerName": "Scout",
    }
    profiles_table.put_item(Item=profile)
    # Seed an item at the destination key so the Put condition fails.
    profiles_table.put_item(
        Item={
            "ownerAccountId": "ACCOUNT#new456",
            "profileId": "PROFILE#abc",
            "sellerName": "Existing",
        }
    )

    with pytest.raises(Exception):
        transfer_module._transfer_ownership(profile, "PROFILE#abc", "ACCOUNT#new456")


def test_profile_sharing_fetch_batch_with_zero_retries():
    from src.handlers import profile_sharing

    class DummyLogger:
        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    result = profile_sharing._fetch_batch_with_retry([], None, DummyLogger(), retries=0)  # type: ignore[arg-type]
    assert result == []


def test_admin_operations_get_cognito_user_attributes():
    from src.handlers.admin_operations import _get_cognito_user_attributes

    account_id, email, email_verified, user_status, enabled = _get_cognito_user_attributes(
        {
            "Username": "u1",
            "Attributes": [
                {"Name": "sub", "Value": "sub-123"},
                {"Name": "email", "Value": "user@example.com"},
                {"Name": "email_verified", "Value": "true"},
            ],
            "UserStatus": "CONFIRMED",
            "Enabled": False,
        }
    )
    assert account_id == "sub-123"
    assert email == "user@example.com"
    assert email_verified is True
    assert user_status == "CONFIRMED"
    assert enabled is False


def test_campaign_operations_normalize_account_id():
    from src.handlers.campaign_operations import _normalize_account_id

    assert _normalize_account_id("ACCOUNT#abc") == "abc"
    assert _normalize_account_id("abc") == "abc"
    assert _normalize_account_id(None) == ""  # type: ignore[arg-type]
    assert _normalize_account_id("") == ""


def test_campaign_reporting_reraises_non_not_found_profile_error(monkeypatch):
    from src.handlers import campaign_reporting
    from src.utils.errors import AppError, ErrorCode

    def mock_check_profile_access(*args, **kwargs):
        raise AppError(ErrorCode.INTERNAL_ERROR, "DynamoDB is unavailable")

    monkeypatch.setattr(campaign_reporting, "check_profile_access", mock_check_profile_access)

    with pytest.raises(AppError) as exc_info:
        campaign_reporting._get_accessible_profiles(["PROFILE#1"], "ACCOUNT#caller")

    assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
