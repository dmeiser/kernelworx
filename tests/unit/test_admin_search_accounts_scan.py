"""Account-search coverage for `adminSearchUser` against a real DynamoDB emulator.

The mocked tests in `test_admin_operations.py` patch `tables.accounts.query`
with a Python lambda, so a key condition DynamoDB would reject is evaluated
successfully in Python and the bug is invisible. These tests drive the real
handler against a moto-backed accounts table created from the production
schema (`table_schemas.create_accounts_table_schema`), so DynamoDB validates
every key condition the handler emits, and assert the operations actually
issued (#576).

Current, honest behavior: the accounts table carries two GSIs. `email-index` is
keyed on `email` alone and answers a complete email; `emailSearchIndex` is a
prefix-segment index (constant `emailSearchKey` HASH + `email` RANGE) and
answers an email prefix with one Query. Both are sparse, so an account is only
reachable through an index once it carries the key attribute; a name fragment is
still a substring search served by a full accounts-table scan.
"""

from datetime import datetime, timezone
from json import loads
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import boto3
import pytest
from moto import mock_aws

from src.handlers.admin_user_operations import admin_search_user
from src.utils.errors import ErrorCode
from src.utils.logging import get_logger
from tests.unit.table_schemas import create_accounts_table_schema

logger = get_logger(__name__)

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
    cognito_users = [_cognito_user(item["accountId"].removeprefix("ACCOUNT#"), item["email"]) for item in ACCOUNT_ITEMS]
    cognito = _FakeCognito(cognito_users)

    monkeypatch.setattr("src.handlers.admin_user_operations.tables", SimpleNamespace(accounts=accounts_table))
    monkeypatch.setattr("src.handlers.admin_user_operations.get_cognito_client", lambda: cognito)
    monkeypatch.setattr(
        "src.handlers.admin_user_operations._batch_get_display_names",
        lambda account_ids, logger: {i: "Alice Anderson" for i in account_ids},
    )
    monkeypatch.setattr("src.handlers.admin_user_operations._batch_get_user_groups", lambda *args, **kwargs: {})

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
        """A full email is answered by the prefix index, falling back to the scan when unindexed.

        These fixture accounts carry no `emailSearchKey`, which is what an
        account looks like before the #586 backfill has covered it. The
        `emailSearchIndex` GSI is sparse, so it cannot project them, and the
        documented scan fallback is what keeps them findable (#586).
        """
        result = search("alice@example.com")

        assert [user["email"] for user in result] == ["alice@example.com"]
        assert [operation for operation, _ in dynamodb_ops] == ["Query", "Scan"]
        query_params = dynamodb_ops[0][1]
        assert query_params["IndexName"] == "emailSearchIndex"
        assert query_params["KeyConditionExpression"] == "emailSearchKey = :searchKey AND begins_with(email, :prefix)"

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


class TestAdminSearchScanPagination:
    """The name-fragment scan is bounded per request, not only between requests (#775).

    A name fragment is a substring match, and the accounts table carries only
    email-keyed GSIs, so the scan itself is unavoidable; what is bounded is how
    much one request may read. These tests drive the real scan loop against moto
    so the page chain, the per-request `Limit`, and the projection are validated
    by a DynamoDB implementation rather than by a mocked `scan`.
    """

    @staticmethod
    def _seed_bulk_accounts(accounts_table: Any, count: int) -> None:
        """Seed ``count`` accounts carrying a `preferences` blob like real rows do."""
        for index in range(count):
            accounts_table.put_item(
                Item={
                    "accountId": f"ACCOUNT#bulk-{index:04d}",
                    "email": f"bulk{index:04d}@example.com",
                    "givenName": "Bulk",
                    "familyName": "Aardvark",
                    "preferences": {"paymentMethods": [{"id": f"pm-{index}-{n}"} for n in range(20)]},
                }
            )

    @staticmethod
    def _scan_requests(dynamodb_ops: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        return [params for operation, params in dynamodb_ops if operation == "Scan"]

    @pytest.fixture
    def scan_tables(self, accounts_table: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
        """Point the handler's table accessor at the moto table so its client records."""
        monkeypatch.setattr("src.handlers.admin_operations.tables", SimpleNamespace(accounts=accounts_table))
        return accounts_table

    def test_match_on_a_later_page_is_still_found(
        self, scan_tables: Any, dynamodb_ops: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """The walk follows `LastEvaluatedKey` until the match turns up."""
        self._seed_bulk_accounts(scan_tables, 600)
        scan_tables.put_item(
            Item={"accountId": "ACCOUNT#zzz-needle", "email": "zzz@example.com", "givenName": "Needle"}
        )
        dynamodb_ops.clear()

        matches = _search_accounts_in_dynamodb("needle", logger)

        assert [item["accountId"] for item in matches] == ["ACCOUNT#zzz-needle"]
        scans = self._scan_requests(dynamodb_ops)
        assert [params["Limit"] for params in scans] == [250, 250, 250]
        assert "ExclusiveStartKey" not in scans[0]
        resume_keys = {str(params["ExclusiveStartKey"]) for params in scans[1:]}
        assert len(resume_keys) == len(scans) - 1

    def test_item_budget_is_enforced_per_request(
        self,
        scan_tables: Any,
        dynamodb_ops: List[Tuple[str, Dict[str, Any]]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """1004 rows: the scan reads exactly the 1000-item budget and says it truncated.

        Without a per-request `Limit` DynamoDB serves a page until it hits its
        own 1 MB byte cap, which for these rows is several hundred items, so the
        old loop could overshoot the budget on its very first request.
        """
        self._seed_bulk_accounts(scan_tables, 1001)
        dynamodb_ops.clear()

        matches = _search_accounts_in_dynamodb("absent", logger)

        scans = self._scan_requests(dynamodb_ops)
        assert [params["Limit"] for params in scans] == [250, 250, 250, 250]
        assert matches == []
        warnings = [loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        assert any(entry.get("level") == "WARNING" and "truncated" in entry.get("message", "") for entry in warnings)

    def test_scan_reads_only_the_searched_attributes(
        self, scan_tables: Any, dynamodb_ops: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """The page payload never carries the `preferences` blob into the Lambda."""
        self._seed_bulk_accounts(scan_tables, 1)
        dynamodb_ops.clear()

        matches = _search_accounts_in_dynamodb("bulk", logger)

        scans = self._scan_requests(dynamodb_ops)
        assert scans[0]["ProjectionExpression"] == "accountId, email, givenName, familyName"
        assert [item["accountId"] for item in matches] == ["ACCOUNT#bulk-0000"]
        assert all(set(item) == {"accountId", "email", "givenName", "familyName"} for item in matches)
