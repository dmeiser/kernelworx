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


def test_pre_signup_handle_signup_exception():
    from botocore.exceptions import ClientError

    from src.handlers import pre_signup

    event = {"response": {}}

    # Unexpected errors are re-raised to prevent duplicate account creation.
    with pytest.raises(Exception, match="unexpected"):
        pre_signup._handle_signup_exception(Exception("unexpected"), "user@example.com", event)

    client_error = ClientError(
        {"Error": {"Code": "InvalidParameterException", "Message": "Link already exists"}},
        "AdminLinkProviderForUser",
    )
    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(client_error, "user@example.com", event)

    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(
            pre_signup.FederatedIdentityLinkedException("Cannot link federated identity: invalid username format"),
            "user@example.com",
            event,
        )


def test_payment_methods_delete_qr_uuid_fallback(monkeypatch):
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    from src.utils import payment_methods

    monkeypatch.setenv("EXPORTS_BUCKET", "test-exports-bucket")
    mock_s3 = MagicMock()
    # First 3 calls (slug-based) raise NoSuchKey, next 3 (UUID) succeed
    no_such_key = ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "DeleteObject")
    mock_s3.delete_object.side_effect = [no_such_key, no_such_key, no_such_key, None, None, None]
    monkeypatch.setattr(payment_methods, "_get_s3_client", lambda: mock_s3)

    # UUID fallback success path
    payment_methods.delete_qr_from_s3("ACCOUNT#test", "test-method")
    assert mock_s3.delete_object.call_count == 6


def test_payment_methods_delete_qr_uuid_fallback_error(monkeypatch):
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    from src.utils import payment_methods

    monkeypatch.setenv("EXPORTS_BUCKET", "test-exports-bucket")
    mock_s3 = MagicMock()
    no_such_key = ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "DeleteObject")
    access_denied = ClientError({"Error": {"Code": "AccessDenied", "Message": "Access denied"}}, "DeleteObject")
    # Slug deletes: NoSuchKey, NoSuchKey, NoSuchKey
    # UUID deletes: NoSuchKey, AccessDenied
    mock_s3.delete_object.side_effect = [no_such_key, no_such_key, no_such_key, no_such_key, access_denied]
    monkeypatch.setattr(payment_methods, "_get_s3_client", lambda: mock_s3)

    # UUID fallback with non-NoSuchKey error surfaces a typed AppError
    from src.utils.errors import AppError, ErrorCode

    with pytest.raises(AppError) as exc_info:
        payment_methods.delete_qr_from_s3("ACCOUNT#test", "test-method")
    assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
    assert mock_s3.delete_object.call_count == 5


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
    from src.utils.dynamodb import reset_dynamodb_resource

    reset_dynamodb_resource()
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


def test_campaign_reporting_propagates_batch_access_error(monkeypatch):
    from src.handlers import campaign_reporting
    from src.utils.errors import AppError, ErrorCode

    def mock_batch_check_profile_access(*args, **kwargs):
        raise AppError(ErrorCode.INTERNAL_ERROR, "DynamoDB is unavailable")

    monkeypatch.setattr(campaign_reporting, "batch_check_profile_access", mock_batch_check_profile_access)

    with pytest.raises(AppError) as exc_info:
        campaign_reporting._get_accessible_profiles(["PROFILE#1"], "ACCOUNT#caller")

    assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
