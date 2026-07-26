"""Unit tests for post_authentication Cognito trigger Lambda."""

import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws  # type: ignore[import-untyped]

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ.setdefault("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")


TABLE_NAME = "kernelworx-accounts-ue1-dev"


def _make_event(sub: str = "user-sub-123", email: str = "user@example.com", **extra_attrs: str) -> Dict[str, Any]:
    attrs: Dict[str, str] = {"sub": sub, "email": email}
    attrs.update(extra_attrs)
    return {
        "triggerSource": "PostAuthentication_Authentication",
        "userPoolId": "us-east-1_TEST",
        "userName": "user@example.com",
        "request": {"userAttributes": attrs},
        "response": {},
    }


@pytest.fixture
def accounts_table() -> Any:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "accountId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "accountId", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "email-index",
                    "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


def test_creates_new_account(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    event = _make_event(given_name="Alice", family_name="Smith")
    result = lambda_handler(event, None)
    assert result is event
    item = accounts_table.get_item(Key={"accountId": "ACCOUNT#user-sub-123"}).get("Item")
    assert item is not None
    assert item["email"] == "user@example.com"
    assert item["givenName"] == "Alice"


def test_updates_existing_account(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    accounts_table.put_item(
        Item={
            "accountId": "ACCOUNT#user-sub-123",
            "email": "old@example.com",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "updatedAt": "2024-01-01T00:00:00+00:00",
        }
    )
    event = _make_event(email="new@example.com")
    result = lambda_handler(event, None)
    assert result is event
    item = accounts_table.get_item(Key={"accountId": "ACCOUNT#user-sub-123"}).get("Item")
    assert item["email"] == "new@example.com"


def test_missing_sub_returns_event_without_writes(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    event = {
        "triggerSource": "PostAuthentication_Authentication",
        "request": {"userAttributes": {"email": "nope@example.com"}},
        "response": {},
    }
    result = lambda_handler(event, None)
    assert result is event
    # No item should exist
    scan = accounts_table.scan()
    assert scan["Count"] == 0


def test_dynamodb_exception_still_returns_event(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    with patch("src.handlers.post_authentication.tables") as mock_tables:
        mock_tables.accounts.get_item.side_effect = Exception("DynamoDB error")
        event = _make_event()
        result = lambda_handler(event, None)
        assert result is event


def test_creates_account_without_given_family_name(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    event = _make_event()
    lambda_handler(event, None)
    item = accounts_table.get_item(Key={"accountId": "ACCOUNT#user-sub-123"}).get("Item")
    assert item["givenName"] == ""
    assert item["familyName"] == ""


def test_post_confirmation_trigger_creates_account(accounts_table: Any) -> None:
    from src.handlers.post_authentication import lambda_handler

    event = _make_event()
    event["triggerSource"] = "PostConfirmation_ConfirmSignUp"
    result = lambda_handler(event, None)
    assert result is event
    item = accounts_table.get_item(Key={"accountId": "ACCOUNT#user-sub-123"}).get("Item")
    assert item is not None
