"""Regression tests for index-backed admin user search (issue #586).

``adminSearchUser`` could only answer a partial query by scanning the whole
accounts table, because the only secondary index on the table (``email-index``)
is HASH-only on ``email`` and ``begins_with`` is illegal on a partition key --
DynamoDB rejects that key condition ("Query key condition not supported"), which
is what #576 shipped before it was reverted.

These tests drive the real handler and the real account write path against moto
so every emitted key condition is validated by a DynamoDB expression validator,
rather than asserted against a mocked ``tables.accounts.query``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Generator, List, Tuple

import pytest
from botocore.exceptions import ClientError

from src.handlers.admin_operations import _search_accounts_in_dynamodb, admin_search_user
from src.handlers.post_authentication import lambda_handler as post_auth_lambda_handler
from src.utils.dynamodb import tables

logger = logging.getLogger(__name__)

EMAIL_SEARCH_INDEX = "emailSearchIndex"


@pytest.fixture
def dynamodb_calls(dynamodb_table: Any) -> Generator[List[Tuple[str, Dict[str, Any]]], None, None]:
    """Record every DynamoDB operation the code under test actually issues."""
    calls: List[Tuple[str, Dict[str, Any]]] = []
    client = tables.accounts.meta.client

    def record(model: Any, params: Dict[str, Any], **kwargs: Any) -> None:
        calls.append((model.name, dict(params)))

    client.meta.events.register("before-call.dynamodb", record)
    try:
        yield calls
    finally:
        client.meta.events.unregister("before-call.dynamodb", record)


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


def _queries_against_index(calls: List[Tuple[str, Dict[str, Any]]], index_name: str) -> List[Dict[str, Any]]:
    return [params for operation, params in calls if operation == "Query" and params.get("IndexName") == index_name]


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
    assert index_queries[0]["ExpressionAttributeValues"] == {":searchKey": EMAIL_SEARCH_KEY, ":prefix": "anna@"}
    assert [operation for operation, _ in dynamodb_calls].count("Scan") == 0


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
    assert [operation for operation, _ in dynamodb_calls].count("Scan") == 0


def test_mixed_case_email_search_is_lowercased_for_the_index(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """The query is lowercased before it is used as a sort-key prefix."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("Anna@Example.COM", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    index_queries = _queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)
    assert index_queries[0]["ExpressionAttributeValues"][":prefix"] == "anna@example.com"


def test_partial_email_search_is_answered_by_an_index_not_a_table_scan(
    dynamodb_table: Any,
    dynamodb_calls: List[Tuple[str, Dict[str, Any]]],
    lambda_context: Any,
) -> None:
    """A partial email must be answered by one index query, with no table scan."""
    _bootstrap_account("sub-anna", "anna@example.com", lambda_context)
    _bootstrap_account("sub-bob", "bob@example.com", lambda_context)
    dynamodb_calls.clear()

    matches = _search_accounts_in_dynamodb("anna@", logger)

    assert [item["email"] for item in matches] == ["anna@example.com"]
    assert len(_queries_against_index(dynamodb_calls, EMAIL_SEARCH_INDEX)) == 1
    assert [operation for operation, _ in dynamodb_calls].count("Scan") == 0
