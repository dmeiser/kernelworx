"""Targeted coverage tests for unhit branches and helpers."""

import importlib
import sys
from typing import Any

import boto3
import pytest
from moto import mock_aws

from tests.unit.table_schemas import TABLE_NAMES, create_all_tables, get_all_table_schemas


def _transfer_test_tables() -> Any:
    """Create the moto tables the transfer-ownership handler binds to.

    Schema ownership stays in ``tests/unit/table_schemas.py``: this creates the
    shared tables under their canonical names, which are the same names
    ``conftest.py`` exports through ``PROFILES_TABLE_NAME`` /
    ``SHARES_TABLE_NAME``, so the handler resolves to exactly these tables.
    """
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_all_tables(dynamodb)
    return dynamodb


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

    # Unexpected errors are re-raised to prevent duplicate account creation.
    with pytest.raises(Exception, match="unexpected"):
        pre_signup._handle_signup_exception(Exception("unexpected"), "user@example.com")

    client_error = ClientError(
        {"Error": {"Code": "InvalidParameterException", "Message": "Link already exists"}},
        "AdminLinkProviderForUser",
    )
    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(client_error, "user@example.com")

    with pytest.raises(pre_signup.FederatedIdentityLinkedException):
        pre_signup._handle_signup_exception(
            pre_signup.FederatedIdentityLinkedException("Cannot link federated identity: invalid username format"),
            "user@example.com",
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
    monkeypatch.setattr(payment_methods, "get_s3_client", lambda _override=None: mock_s3)

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
    monkeypatch.setattr(payment_methods, "get_s3_client", lambda _override=None: mock_s3)

    # UUID fallback with non-NoSuchKey error surfaces a typed AppError
    from src.utils.errors import AppError, ErrorCode

    with pytest.raises(AppError) as exc_info:
        payment_methods.delete_qr_from_s3("ACCOUNT#test", "test-method")
    assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
    assert mock_s3.delete_object.call_count == 5


def test_report_generation_uses_shared_s3_factory():
    """report_generation routes S3 construction through the shared factory (#575)."""
    from src.handlers import report_generation
    from src.utils import boto

    assert not hasattr(report_generation, "_get_s3_client")
    assert report_generation.get_s3_client is boto.get_s3_client


@mock_aws
def test_transfer_profile_ownership_success():
    dynamodb = _transfer_test_tables()

    # Reload handler so it binds to the moto tables via the current env vars.
    from src.utils.dynamodb import reset_dynamodb_resource

    reset_dynamodb_resource()
    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table(TABLE_NAMES["profiles"])
    shares_table = dynamodb.Table(TABLE_NAMES["shares"])

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
    dynamodb = _transfer_test_tables()

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table(TABLE_NAMES["profiles"])
    shares_table = dynamodb.Table(TABLE_NAMES["shares"])

    profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#owner123", "profileId": "PROFILE#abc"})

    event_base = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    # Missing share returns an error payload
    result = transfer_module.lambda_handler(event_base, None)
    assert result["__isError"] is True

    # Seed share but wrong caller triggers AppError
    shares_table.put_item(Item={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456"})
    event_bad_owner = {
        "identity": {"sub": "someoneelse"},
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }
    result = transfer_module.lambda_handler(event_bad_owner, None)
    assert result["__isError"] is True

    # Missing profile triggers AppError
    event_missing_profile = {
        "identity": {"sub": "owner123"},
        "arguments": {"input": {"profileId": "PROFILE#missing", "newOwnerAccountId": "new456"}},
    }
    result = transfer_module.lambda_handler(event_missing_profile, None)
    assert result["__isError"] is True


@mock_aws
def test_transfer_profile_ownership_admin_transfer():
    """Test admin can transfer profile without share requirement."""
    dynamodb = _transfer_test_tables()

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table(TABLE_NAMES["profiles"])

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
            "claims": {"cognito:groups": ["ADMIN"], "mfa": True},
        },
        "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
    }

    updated_profile = transfer_module.lambda_handler(event, None)

    assert updated_profile["ownerAccountId"] == "ACCOUNT#new456"


@mock_aws
def test_transfer_profile_ownership_share_delete_fails():
    """An unexpected (non-DynamoDB) failure repairing shares is not swallowed.

    Only client errors are translated into the retryable RESOURCE_BUSY path; a bug
    raises and surfaces as INTERNAL_ERROR, so the two are distinguishable (#549).
    """
    from unittest.mock import MagicMock

    dynamodb = _transfer_test_tables()

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table(TABLE_NAMES["profiles"])
    shares_table = dynamodb.Table(TABLE_NAMES["shares"])

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
        result = transfer_module.lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == "INTERNAL_ERROR"
    finally:
        # Clean up override
        db_module._table_overrides.pop("shares", None)


@mock_aws
def test_transfer_profile_ownership_source_deleted_race():
    """Transfer must fail if the source profile is deleted between read and transaction."""
    _transfer_test_tables()

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
    dynamodb = _transfer_test_tables()

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    profiles_table = dynamodb.Table(TABLE_NAMES["profiles"])
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


def test_transfer_tests_derive_tables_from_shared_schema_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every transfer test must build its moto tables via table_schemas.create_all_tables.

    Regression guard for the hand-rolled ``dynamodb.create_table`` copies this
    module used to repeat: a private copy would create tables the rest of the
    suite's shared schema owner knows nothing about, so the transfer tests would
    silently drift from ``tests/unit/table_schemas.py``. The tests are discovered
    rather than listed, so adding or removing one neither breaks this guard nor
    leaves a new transfer test unchecked.
    """
    created: list[Any] = []
    real_create_all_tables = create_all_tables

    def spy(resource: Any) -> dict[str, Any]:
        created.append(resource)
        return real_create_all_tables(resource)

    monkeypatch.setattr(sys.modules[__name__], "create_all_tables", spy)

    module_globals = vars(sys.modules[__name__])
    transfer_tests = [
        value
        for name, value in sorted(module_globals.items())
        if name.startswith("test_transfer_profile_ownership_") and callable(value)
    ]
    assert transfer_tests, "no transfer-ownership tests were found to check"

    for transfer_test in transfer_tests:
        before = len(created)
        transfer_test()
        assert len(created) > before, f"{transfer_test.__name__} built its tables without the shared schema owner"


@mock_aws
def test_shared_tables_expose_canonical_schema_and_bind_the_handler() -> None:
    """The shared schema owner is what the handler actually reads and writes.

    Asserts the tables that exist are exactly the shared schema set, and that a
    profile seeded in the shared profiles table is the row the transfer handler
    mutates - a private table copy would satisfy neither.
    """
    dynamodb = _transfer_test_tables()
    client = boto3.client("dynamodb", region_name="us-east-1")

    assert set(client.list_tables()["TableNames"]) == {schema["TableName"] for schema in get_all_table_schemas()}

    profiles = dynamodb.Table(TABLE_NAMES["profiles"])
    shares = dynamodb.Table(TABLE_NAMES["shares"])
    profiles.put_item(Item={"ownerAccountId": "ACCOUNT#owner123", "profileId": "PROFILE#abc", "sellerName": "Scout"})
    shares.put_item(Item={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456", "permissions": ["READ"]})

    module_name = "src.handlers.transfer_profile_ownership"
    if module_name in sys.modules:
        del sys.modules[module_name]
    transfer_module = importlib.import_module(module_name)

    updated = transfer_module.lambda_handler(
        {
            "identity": {"sub": "owner123"},
            "arguments": {"input": {"profileId": "PROFILE#abc", "newOwnerAccountId": "new456"}},
        },
        None,
    )

    assert updated["ownerAccountId"] == "ACCOUNT#new456"
    assert (
        profiles.get_item(Key={"ownerAccountId": "ACCOUNT#new456", "profileId": "PROFILE#abc"})["Item"]["sellerName"]
        == "Scout"
    )
    assert "Item" not in shares.get_item(Key={"profileId": "PROFILE#abc", "targetAccountId": "ACCOUNT#new456"})


def test_campaign_reporting_propagates_batch_access_error(monkeypatch):
    from src.handlers import campaign_reporting
    from src.utils.errors import AppError, ErrorCode

    def mock_batch_check_profile_access(*args, **kwargs):
        raise AppError(ErrorCode.INTERNAL_ERROR, "DynamoDB is unavailable")

    monkeypatch.setattr(campaign_reporting, "batch_check_profile_access", mock_batch_check_profile_access)

    with pytest.raises(AppError) as exc_info:
        campaign_reporting._get_accessible_profiles(["PROFILE#1"], "ACCOUNT#caller")

    assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
