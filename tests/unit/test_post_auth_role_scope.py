"""Behavioral scope check for the #355 scoped post-auth execution role.

The Cognito post-authentication / post-confirmation account-bootstrap trigger
(``handlers/post_authentication.py``) runs under the scoped role added in #355
(chunk 5 of the #326 IAM role split), when the monolithic shared role was
retired. That role grants DynamoDB GetItem/PutItem/UpdateItem on the accounts
table only. See ``tofu/application/modules/iam/main.tf``.

These tests invoke the real handler against moto DynamoDB while recording
every DynamoDB API call at the botocore layer, then assert the recorded
(operation, table) pairs stay within what the scoped role permits. If a future
change makes the bootstrap trigger touch another table or issue another
action (for example a Scan to find orphaned accounts), this test fails — the
exact signal needed to re-scope the role.
"""

from typing import Any, Dict, List, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.post_authentication import lambda_handler

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"

# Tables the #355 post-auth role grants access to: the accounts table only.
DOMAIN_TABLES = {ACCOUNTS_TABLE}

# Actions the #355 post-auth role grants.
ALLOWED_ACTIONS = {"GetItem", "PutItem", "UpdateItem"}

ACCOUNT_SUB = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
ACCOUNT_KEY = f"ACCOUNT#{ACCOUNT_SUB}"


class DynamoDbCallRecorder:
    """Records DynamoDB API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so both resource-style
    (Table.get_item/put_item/update_item) and client-style calls are captured
    with their real operation names. Seeding performed before ``attach()`` is
    not recorded.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        calls = self.calls

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            if self.meta.service_model.service_name == "dynamodb":
                tables: List[str] = []
                if isinstance(params, dict):
                    if isinstance(params.get("TableName"), str):
                        tables.append(params["TableName"])
                    if isinstance(params.get("RequestItems"), dict):
                        tables.extend(params["RequestItems"].keys())
                for table in tables:
                    calls.append((operation_name, table))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def dynamodb_calls(monkeypatch: pytest.MonkeyPatch) -> DynamoDbCallRecorder:
    """Provide a DynamoDB call recorder; call ``attach()`` after seeding data."""
    return DynamoDbCallRecorder(monkeypatch)


def assert_within_post_auth_role_scope(calls: List[Tuple[str, str]]) -> None:
    """Assert recorded calls stay within the #355 scoped post-auth role policy."""
    assert calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in calls}
    tables = {table for _, table in calls}
    assert operations <= ALLOWED_ACTIONS, f"unexpected DynamoDB actions: {operations - ALLOWED_ACTIONS}"
    assert tables <= DOMAIN_TABLES, f"handler touched tables outside the post-auth role scope: {tables - DOMAIN_TABLES}"


def _cognito_event(sub: str = ACCOUNT_SUB, email: str = "user@example.com") -> Dict[str, Any]:
    """Minimal Cognito Post Authentication event carrying the given sub/email."""
    return {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "region": "us-east-1",
        "userPoolId": "us-east-1_TEST123",
        "userName": sub,
        "request": {"userAttributes": {"sub": sub, "email": email, "email_verified": "true"}},
        "response": {},
    }


class TestPostAuthBootstrapScope:
    """The account-bootstrap trigger (create and update paths) stays within the role scope."""

    def test_create_new_account(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        dynamodb_calls.attach()

        result = lambda_handler(_cognito_event(), lambda_context)

        # The trigger must return the event unmodified so Cognito continues.
        assert result["userName"] == ACCOUNT_SUB
        assert ("GetItem", ACCOUNTS_TABLE) in dynamodb_calls.calls
        assert ("PutItem", ACCOUNTS_TABLE) in dynamodb_calls.calls
        assert_within_post_auth_role_scope(dynamodb_calls.calls)

    def test_update_existing_account(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        accounts_table = boto3.resource("dynamodb", region_name="us-east-1").Table(ACCOUNTS_TABLE)
        accounts_table.put_item(
            Item={
                "accountId": ACCOUNT_KEY,
                "email": "old@example.com",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )
        dynamodb_calls.attach()

        result = lambda_handler(_cognito_event(email="new@example.com"), lambda_context)

        assert result["userName"] == ACCOUNT_SUB
        assert ("GetItem", ACCOUNTS_TABLE) in dynamodb_calls.calls
        assert ("UpdateItem", ACCOUNTS_TABLE) in dynamodb_calls.calls
        assert ("PutItem", ACCOUNTS_TABLE) not in dynamodb_calls.calls
        assert_within_post_auth_role_scope(dynamodb_calls.calls)

    def test_missing_sub_stays_in_scope(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        event = _cognito_event()
        del event["request"]["userAttributes"]["sub"]
        dynamodb_calls.attach()

        result = lambda_handler(event, lambda_context)

        # Returns the event without touching DynamoDB at all.
        assert "userName" in result
        assert dynamodb_calls.calls == []
