"""
Tests for Post-Authentication Lambda trigger

Updated for multi-table design (accounts table).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from src.handlers.post_authentication import lambda_handler


@pytest.fixture
def cognito_event() -> dict[str, Any]:
    """Sample Cognito Post Authentication event"""
    return {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "region": "us-east-1",
        "userPoolId": "us-east-1_TEST123",
        "userName": "google_123456789",
        "callerContext": {
            "awsSdkVersion": "aws-sdk-js-2.1055.0",
            "clientId": "1example23456789",
        },
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "email": "user@example.com",
                "email_verified": "true",
            },
            "groupConfiguration": {
                "groupsToOverride": [],  # No groups by default (non-admin)
            },
        },
        "response": {},
    }


@pytest.fixture
def lambda_context() -> MagicMock:
    """Mock Lambda context"""
    context = MagicMock()
    context.function_name = "test-post-auth"
    context.aws_request_id = "test-request-id"
    return context


def get_accounts_table() -> Any:
    """Get the accounts table for testing (multi-table design)."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-accounts-ue1-dev")


def test_create_new_account_admin_user(
    cognito_event: dict[str, Any],
    lambda_context: MagicMock,
    dynamodb_table: Any,
    monkeypatch: Any,
) -> None:
    """Test creating account for user in ADMIN group"""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

    # Add user to ADMIN group
    cognito_event["request"]["groupConfiguration"]["groupsToOverride"] = ["ADMIN"]

    result = lambda_handler(cognito_event, lambda_context)

    # Should return event unmodified
    assert result == cognito_event

    # Check Account was created in DynamoDB (multi-table design)
    accounts_table = get_accounts_table()
    response = accounts_table.get_item(Key={"accountId": "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890"})

    assert "Item" in response
    account = response["Item"]
    assert account["accountId"] == "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert account["email"] == "user@example.com"
    # Note: isAdmin is NOT stored in DynamoDB - comes from JWT cognito:groups claim
    assert "createdAt" in account
    assert "updatedAt" in account


def test_create_new_account_regular_user(
    cognito_event: dict[str, Any],
    lambda_context: MagicMock,
    dynamodb_table: Any,
    monkeypatch: Any,
) -> None:
    """Test creating account for user not in ADMIN group"""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

    # User has no groups (or only USER group - not ADMIN)
    cognito_event["request"]["groupConfiguration"]["groupsToOverride"] = ["USER"]

    result = lambda_handler(cognito_event, lambda_context)

    # Should return event unmodified
    assert result == cognito_event

    # Check Account was created (multi-table design)
    accounts_table = get_accounts_table()
    response = accounts_table.get_item(Key={"accountId": "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890"})

    assert "Item" in response
    account = response["Item"]
    assert account["email"] == "user@example.com"
    # Note: isAdmin is NOT stored in DynamoDB - comes from JWT cognito:groups claim


def test_update_existing_account(
    cognito_event: dict[str, Any],
    lambda_context: MagicMock,
    dynamodb_table: Any,
    monkeypatch: Any,
) -> None:
    """Test updating existing account on subsequent login"""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

    # Add user to ADMIN group (this is just for event context, not stored)
    cognito_event["request"]["groupConfiguration"]["groupsToOverride"] = ["ADMIN"]

    # Create existing account with old email (multi-table design)
    original_timestamp = "2024-01-01T00:00:00+00:00"
    accounts_table = get_accounts_table()
    accounts_table.put_item(
        Item={
            "accountId": "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "email": "old@example.com",
            "createdAt": original_timestamp,
            "updatedAt": original_timestamp,
        }
    )

    result = lambda_handler(cognito_event, lambda_context)

    # Should return event unmodified
    assert result == cognito_event

    # Check Account was updated
    response = accounts_table.get_item(Key={"accountId": "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890"})

    account = response["Item"]
    assert account["email"] == "user@example.com"  # Updated email
    assert account["updatedAt"] > original_timestamp  # Updated timestamp
    assert account["createdAt"] == original_timestamp  # Created unchanged


def test_missing_sub_in_event(lambda_context: MagicMock, dynamodb_table: Any, monkeypatch: Any) -> None:
    """Test graceful handling of malformed event"""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    bad_event: dict[str, Any] = {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "request": {"userAttributes": {"email": "user@example.com"}},
        "response": {},
    }

    result = lambda_handler(bad_event, lambda_context)

    # Should still return event (allow auth to continue)
    assert result == bad_event

    # No account should be created
    accounts_table = get_accounts_table()
    response = accounts_table.scan()
    assert response["Count"] == 0


def test_dynamodb_error_does_not_block_auth(cognito_event: dict[str, Any], lambda_context: MagicMock) -> None:
    """Test that DynamoDB errors don't prevent authentication"""
    # Mock boto3.resource to simulate DynamoDB error
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_table.get_item.side_effect = Exception("DynamoDB error")
        mock_resource.return_value.Table.return_value = mock_table

        result = lambda_handler(cognito_event, lambda_context)

        # Should still return event (allow auth to continue)
        assert result == cognito_event


def test_email_gsi_available(
    cognito_event: dict[str, Any],
    lambda_context: MagicMock,
    dynamodb_table: Any,
    monkeypatch: Any,
) -> None:
    """Test that email is properly set for GSI lookup"""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    lambda_handler(cognito_event, lambda_context)

    # Query by email GSI (multi-table design)
    accounts_table = get_accounts_table()
    response = accounts_table.query(
        IndexName="email-index",
        KeyConditionExpression="email = :email",
        ExpressionAttributeValues={":email": "user@example.com"},
    )

    assert response["Count"] == 1
    account = response["Items"][0]
    assert account["accountId"] == "ACCOUNT#a1b2c3d4-e5f6-7890-abcd-ef1234567890"
