"""Account-search coverage for `adminSearchUser` against a real DynamoDB emulator.

The mocked tests in `test_admin_operations.py` patch `tables.accounts.query`
with a Python lambda, so a key condition DynamoDB would reject is evaluated
successfully in Python and the bug is invisible. These tests drive the real
handler against a moto-backed accounts table created from the production
schema (`table_schemas.create_accounts_table_schema`), so DynamoDB validates
every key condition the handler emits, and assert the operations actually
issued (#576).

Current, honest behavior: the `email-index` GSI is keyed on `email` alone, so
`begins_with` is not a legal key condition on it and no index-backed prefix
search exists. A full email uses the GSI; any partial query is served by a full
accounts-table scan.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import boto3
import pytest
from moto import mock_aws

from src.handlers.admin_operations import admin_search_user
from src.utils.errors import ErrorCode
from tests.unit.table_schemas import create_accounts_table_schema

ACCOUNT_ITEMS = [
    {
        "accountId": "ACCOUNT#sub-alice",
        "email": "alice@example.com",
        "givenName": "Alice",
        "familyName": "Anderson",
    },
    {
        "accountId": "ACCOUNT#sub-alina",
        "email": "a.okonkwo@example.com",
        "givenName": "Alina",
        "familyName": "Okonkwo",
    },
    {
        "accountId": "ACCOUNT#sub-bob",
        "email": "bob@example.com",
        "givenName": "Bob",
        "familyName": "Brown",
    },
]


class _FakeCognito:
    """Minimal Cognito stand-in covering the two filters the search issues."""

    def __init__(self, users: List[Dict[str, Any]]) -> None:
        self._users = users

    def list_users(self, UserPoolId: str, Filter: str, Limit: int) -> Dict[str, Any]:  # noqa: N803
        field, _, value = Filter.partition("=")
        field = field.strip()
        value = value.strip().strip('"')

        def attribute(user: Dict[str, Any], name: str) -> str:
            return next(a["Value"] for a in user["Attributes"] if a["Name"] == name)

        if field == "sub":
            matches = [u for u in self._users if attribute(u, "sub") == value]
        else:
            matches = [u for u in self._users if attribute(u, "email").startswith(value)]
        return {"Users": matches[:Limit]}


def _cognito_user(sub: str, email: str) -> Dict[str, Any]:
    return {
        "Username": email,
        "Attributes": [
            {"Name": "sub", "Value": sub},
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
        "Enabled": True,
        "UserStatus": "CONFIRMED",
        "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }


@pytest.fixture
def dynamodb_ops() -> List[Tuple[str, Dict[str, Any]]]:
    """DynamoDB operations recorded by the botocore event hooks in each test."""
    return []


@pytest.fixture
def accounts_table(dynamodb_ops: List[Tuple[str, Dict[str, Any]]]) -> Any:
    """Moto accounts table with the production schema, plus real seeded items."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(**create_accounts_table_schema())
        for item in ACCOUNT_ITEMS:
            table.put_item(Item=item)

        events = table.meta.client.meta.events
        for operation in ("Query", "Scan"):

            def record(params: Dict[str, Any], model: Any, operation: str = operation, **kwargs: Any) -> None:
                dynamodb_ops.append((operation, dict(params)))

            events.register(f"provide-client-params.dynamodb.{operation}", record)

        yield table


@pytest.fixture
def search(accounts_table: Any, monkeypatch: Any) -> Any:
    """Call the real `admin_search_user` with only Cognito mocked."""
    monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
    cognito_users = [
        _cognito_user(item["accountId"].removeprefix("ACCOUNT#"), item["email"]) for item in ACCOUNT_ITEMS
    ]
    cognito = _FakeCognito(cognito_users)

    monkeypatch.setattr("src.handlers.admin_operations.tables", SimpleNamespace(accounts=accounts_table))
    monkeypatch.setattr("src.handlers.admin_operations._get_cognito_client", lambda: cognito)
    monkeypatch.setattr(
        "src.handlers.admin_operations._batch_get_display_names",
        lambda account_ids, logger: {i: "Alice Anderson" for i in account_ids},
    )
    monkeypatch.setattr("src.handlers.admin_operations._batch_get_user_groups", lambda *args, **kwargs: {})

    def call(query: str) -> Any:
        event = {
            "arguments": {"query": query},
            "identity": {
                "sub": "sub-admin",
                "username": "adminuser",
                "claims": {"cognito:groups": ["ADMIN"], "mfa": True},
            },
            "info": {"fieldName": "adminSearchUser"},
        }
        return admin_search_user(event, None)

    return call


class TestAdminSearchAccountsScan:
    def test_partial_query_is_served_by_accounts_table_scan(
        self, search: Any, dynamodb_ops: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """A partial query still resolves, via a scan and with no GSI query."""
        result = search("ali")

        assert sorted(user["email"] for user in result) == ["a.okonkwo@example.com", "alice@example.com"]
        assert [operation for operation, _ in dynamodb_ops] == ["Scan"]

    def test_exact_email_query_uses_email_index_gsi(
        self, search: Any, dynamodb_ops: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """A full email is still answered by the legal `email = :email` key condition."""
        result = search("alice@example.com")

        assert [user["email"] for user in result] == ["alice@example.com"]
        assert [operation for operation, _ in dynamodb_ops] == ["Query"]
        query_params = dynamodb_ops[0][1]
        assert query_params["IndexName"] == "email-index"
        assert query_params["KeyConditionExpression"] == "email = :email"

    def test_query_under_minimum_length_is_rejected_before_any_read(
        self, search: Any, dynamodb_ops: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """A too-short query is refused with a real error, not a partial result."""
        payload = search("al")

        # The decorator turns AppError into the structured payload the JS
        # resolver maps onto GraphQL `extensions` (#329).
        assert payload["__isError"] is True
        assert payload["errorCode"] == ErrorCode.INVALID_INPUT
        assert payload["message"] == "Search query must be at least 3 characters"
        assert dynamodb_ops == []
