"""Regression tests for index-backed admin user search (issue #586).

``adminSearchUser`` could only answer a partial query by scanning the whole
accounts table, because the only search index on the table (``email-index``) is
HASH-only on ``email`` and ``begins_with`` is illegal on a partition key --
DynamoDB rejects that key condition ("Query key condition not supported"), which
is what #576 shipped before it was reverted.

These tests drive the real handler and the real account write path against moto
so every emitted key condition is validated by a DynamoDB expression validator,
rather than asserted against a mocked ``tables.accounts.query``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Tuple

import pytest
from botocore.exceptions import ClientError

from src.handlers.admin_operations import _search_accounts_in_dynamodb, admin_search_user
from src.handlers.post_authentication import lambda_handler as post_auth_lambda_handler
from src.utils.dynamodb import EMAIL_SEARCH_KEY, tables
from src.utils.logging import get_logger

logger = get_logger(__name__)

EMAIL_SEARCH_INDEX = "emailSearchIndex"
PREFIX_KEY_CONDITION = "emailSearchKey = :searchKey AND begins_with(email, :prefix)"

ACCOUNTS_TABLE_NAME = "kernelworx-accounts-ue1-dev"


@pytest.fixture
def dynamodb_calls(dynamodb_table: Any) -> Generator[List[Tuple[str, Dict[str, Any]]], None, None]:
    """Record every DynamoDB operation the code under test actually issues."""
    calls: List[Tuple[str, Dict[str, Any]]] = []
    client = tables.accounts.meta.client

    def record(model: Any, params: Dict[str, Any], **kwargs: Any) -> None:
        body = params.get("body")
        calls.append((model.name, json.loads(body) if body else {}))

    client.meta.events.register("before-call.dynamodb", record)
    try:
        yield calls
    finally:
        client.meta.events.unregister("before-call.dynamodb", record)


def _operations(calls: List[Tuple[str, Dict[str, Any]]], operation: str) -> List[Dict[str, Any]]:
    return [payload for name, payload in calls if name == operation]


def _queries_against_index(calls: List[Tuple[str, Dict[str, Any]]], index_name: str) -> List[Dict[str, Any]]:
    return [payload for payload in _operations(calls, "Query") if payload.get("IndexName") == index_name]


def _string_values(payload: Dict[str, Any]) -> Dict[str, str]:
    """Unwrap the wire format of a recorded request (``{"S": "value"}`` per placeholder)."""
    return {name: typed["S"] for name, typed in payload["ExpressionAttributeValues"].items()}


def _put_account(account_id: str, email: str, given_name: str = "", family_name: str = "") -> None:
    """Write an account item directly (bulk fixtures that skip the trigger)."""
    tables.accounts.put_item(
        Item={
            "accountId": account_id,
            "email": email,
            "emailSearchKey": EMAIL_SEARCH_KEY,
            "givenName": given_name,
            "familyName": family_name,
        }
    )


def _bootstrap_account(
    sub: str,
    email: str,
    lambda_context: Any,
    given_name: str = "",
    family_name: str = "",
) -> str:
    """Create an account the way production does: through the Cognito bootstrap trigger."""
    account_id = f"ACCOUNT#{sub}"
    event: Dict[str, Any] = {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "request": {
            "userAttributes": {
                "sub": sub,
                "email": email,
                "given_name": given_name,
                "family_name": family_name,
            }
        },
        "response": {},
    }
    assert post_auth_lambda_handler(event, lambda_context) is event
    return account_id


def _index_query(prefix: str) -> Dict[str, Any]:
    """Run the prefix query directly against the real index."""
    return tables.accounts.query(
        IndexName=EMAIL_SEARCH_INDEX,
        KeyConditionExpression=PREFIX_KEY_CONDITION,
        ExpressionAttributeValues={":searchKey": EMAIL_SEARCH_KEY, ":prefix": prefix},
    )


class _FakeCognito:
    """Minimal stand-in for the Cognito IDP client used by the admin search path."""

    def __init__(self, users: List[Dict[str, Any]]) -> None:
        self._users = users

    def list_users(self, **kwargs: Any) -> Dict[str, Any]:
        return {"Users": self._users}

    def admin_get_user(self, **kwargs: Any) -> Dict[str, Any]:
        return self._users[0]

    def admin_list_groups_for_user(self, **kwargs: Any) -> Dict[str, Any]:
        return {"Groups": []}


def test_prefix_query_is_rejected_on_the_hash_only_email_index(dynamodb_table: Any, lambda_context: Any) -> None:
    """The legacy index cannot serve a prefix search; DynamoDB itself rejects the key condition."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)

    with pytest.raises(ClientError) as exc_info:
        tables.accounts.query(
            IndexName="email-index",
            KeyConditionExpression="begins_with(email, :prefix)",
            ExpressionAttributeValues={":prefix": "anna"},
        )

    assert exc_info.value.response["Error"]["Code"] == "ValidationException"


def test_partial_email_search_is_answered_by_the_email_search_index(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """A partial email is answered by one index query, with no table scan."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    _bootstrap_account("sub-bob", "bob@example.com", lambda_context)
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("anna@", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    index_queries = _queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)
    assert len(index_queries) == 1
    assert _string_values(index_queries[0]) == {
        ":searchKey": EMAIL_SEARCH_KEY,
        ":prefix": "anna@",
    }
    assert _operations(dynamodb_calls, "Scan") == []


def test_full_email_search_is_answered_by_the_email_search_index(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """A full email is a prefix of itself, so it uses the same index query with no scan."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("anna@example.com", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    assert len(_queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)) == 1
    assert _operations(dynamodb_calls, "Scan") == []


def test_mixed_case_email_search_is_lowercased_for_the_index(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """The query is lowercased before it is used as the sort-key prefix."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("Anna@Example.COM", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    index_queries = _queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)
    assert _string_values(index_queries[0])[":prefix"] == "anna@example.com"


def test_account_bootstrap_writes_the_search_key_so_new_accounts_are_searchable(
    dynamodb_table: Any,
    lambda_context: Any,
) -> None:
    """An account created by the Cognito trigger is reachable through the index."""
    account_id = _bootstrap_account("sub-anna", "anna@example.com", lambda_context)

    assert [item["accountId"] for item in _index_query("anna@")["Items"]] == [account_id]


def test_bootstrap_email_change_moves_the_account_within_the_index(
    dynamodb_table: Any,
    lambda_context: Any,
) -> None:
    """An email change on an existing account re-indexes it under the new address."""
    account_id = _bootstrap_account("sub-anna", "old@example.com", lambda_context)
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)

    assert [item["accountId"] for item in _index_query("anna@")["Items"]] == [account_id]
    assert _index_query("old@")["Count"] == 0


def test_unmigrated_account_without_search_key_is_still_findable(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """A pre-backfill account (no search key) must not become invisible to search."""
    tables.accounts.put_item(Item={"accountId": "ACCOUNT#legacy", "email": "legacy@example.com"})
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("legacy@", logger)

    assert [item["email"] for item in matches] == ["legacy@example.com"]
    assert len(_queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)) == 1
    assert len(_operations(dynamodb_calls, "Scan")) == 1


def test_search_falls_back_to_the_scan_when_the_index_is_missing(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """If the index is not deployed yet the scan keeps admin search working."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    tables.accounts.meta.client.update_table(
        TableName=ACCOUNTS_TABLE_NAME,
        GlobalSecondaryIndexUpdates=[{"Delete": {"IndexName": EMAIL_SEARCH_INDEX}}],
    )
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("anna@", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    assert len(_operations(dynamodb_calls, "Scan")) == 1


def test_truncated_index_results_are_reported_as_truncated(
    dynamodb_table: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A capped result set is never presented as a complete one."""
    for index in range(60):
        _put_account(f"ACCOUNT#{index}", f"bulk@user{index:02d}.example.com")

    matches = _search_accounts_in_dynamodb("bulk@", logger)

    assert len(matches) == 50
    warnings = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert any(entry.get("level") == "WARNING" and "truncated" in entry.get("message", "") for entry in warnings)


def test_name_search_still_matches_substrings(dynamodb_table: Any) -> None:
    """Name fragments are substring matches, which no prefix index can answer."""
    _put_account("ACCOUNT#anna", "anna.smith@example.com", given_name="Anna", family_name="Smith")
    _put_account("ACCOUNT#joanna", "jo@example.com", given_name="Joanna", family_name="Jones")

    matches = _search_accounts_in_dynamodb("anna", logger)

    assert sorted(item["accountId"] for item in matches) == ["ACCOUNT#anna", "ACCOUNT#joanna"]


def test_admin_search_user_uses_the_index_for_a_partial_email(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the resolver path answers a partial email without scanning the table."""
    monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    event: Dict[str, Any] = {
        "arguments": {"query": "anna@"},
        "identity": {"sub": "admin-sub", "claims": {"cognito:groups": ["ADMIN"], "mfa": True}},
        "requestContext": {"requestId": "test-correlation-id"},
        "info": {"fieldName": "adminSearchUser"},
    }
    cognito_user = {
        "Username": "anna@example.com",
        "Attributes": [
            {"Name": "sub", "Value": "sub-anna"},
            {"Name": "email", "Value": "anna@example.com"},
        ],
        "Enabled": True,
        "UserStatus": "CONFIRMED",
    }
    monkeypatch.setattr("src.handlers.admin_operations.get_cognito_client", lambda: _FakeCognito([cognito_user]))
    dynamodb_calls.clear()

    results = admin_search_user(event, lambda_context)

    assert [result["accountId"] for result in results] == ["sub-anna"]
    assert len(_queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)) == 1
    assert _operations(dynamodb_calls, "Scan") == []


def test_email_search_index_uses_the_constant_key_as_its_partition_key(dynamodb_table: Any) -> None:
    """The index is a single constant bucket: a Query without the constant is rejected."""
    with pytest.raises(ClientError) as exc_info:
        tables.accounts.query(
            IndexName=EMAIL_SEARCH_INDEX,
            KeyConditionExpression="begins_with(email, :prefix)",
            ExpressionAttributeValues={":prefix": "anna@"},
        )

    assert exc_info.value.response["Error"]["Code"] == "ValidationException"
