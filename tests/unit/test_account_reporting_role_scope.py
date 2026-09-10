"""Behavioral scope check for the #354 scoped account-and-reporting execution role.

The account/reporting-domain Lambda functions (``request-report``,
``list-catalogs-in-use``, ``list-unit-catalogs``, and
``list-unit-campaign-catalogs``) run under the scoped per-domain role added in
#354 (chunk 4 of the #326 IAM role split, reusing the wiring pattern #351
established). That role grants DynamoDB read actions (GetItem/Query/
BatchGetItem) on exactly the tables the handlers touch (profiles, shares,
campaigns, orders, catalogs — the first two only via the shared
``utils.auth`` collaborator paths), plus S3 PutObject / GetObject scoped to
the ``reports/*`` prefix of the exports bucket (request-report uploads the
generated report and returns a pre-signed GET URL, which S3 authorizes
against the signing role's policy at request time). Every handler in this
domain is read-only on DynamoDB: the role grants no write action. The
account-lifecycle handler ``delete-account`` is deliberately NOT in this
domain — it performs Cognito admin actions and stays on the isolated admin
role (#121). See ``tofu/application/modules/iam/main.tf``.

These tests invoke the real handlers (or the real async query helpers, in the
list-catalogs-in-use aioboto3 case where moto cannot intercept) while
recording every DynamoDB and S3 API call, then assert the recorded calls stay
within what the scoped role permits. If a future change makes these handlers
touch another table (for example ``accounts`` or ``invites``) or issue a
write anywhere, this test fails — the exact signal needed to re-scope the
domain role.
"""

import os
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import boto3
import botocore.client
import pytest

from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs, list_unit_catalogs
from src.handlers.report_generation import request_campaign_report

PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"
EXPORTS_BUCKET = "kernelworx-exports-ue1-dev"

# Tables the #354 account/reporting role grants read access to.
DOMAIN_TABLES = {PROFILES_TABLE, SHARES_TABLE, CAMPAIGNS_TABLE, ORDERS_TABLE, CATALOGS_TABLE}

# DynamoDB actions the #354 role grants. This domain is read-only on
# DynamoDB: no PutItem/UpdateItem/DeleteItem/BatchWriteItem anywhere.
ALLOWED_DYNAMODB_ACTIONS = {"GetItem", "Query", "BatchGetItem"}

# S3 API operations the #354 role permits, and the only object prefix the role
# allows. The role also grants s3:GetObject (for the pre-signed report
# download URL), but pre-signed URL generation is pure client-side signing, so
# no GetObject call is ever recorded here.
ALLOWED_S3_OPERATIONS = {"PutObject"}
ALLOWED_S3_PREFIX = "reports/"

OWNER_SUB = "owner-sub-001"
FRIEND_SUB = "friend-sub-002"
OTHER_SUB = "other-sub-003"
PROFILE_ID = "PROFILE#profile-123"
OTHER_PROFILE_ID = "PROFILE#profile-456"
CAMPAIGN_ID = "CAMPAIGN#campaign-123"
CATALOG_ID = "CATALOG#catalog-123"


class ApiCallRecorder:
    """Records DynamoDB and S3 API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style
    (Table.query/get_item) and client-style (batch_get_item) calls are
    captured with their real operation names. Seeding performed before
    ``attach()`` is not recorded. Pre-signed URL generation never reaches
    this layer (it is pure client-side signing), so no GetObject call is
    recorded for request-report's reportUrl — but the role still grants
    s3:GetObject on the reports prefix, because S3 authorizes the browser's
    pre-signed GET against the signing role's policy at request time.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dynamodb_calls: List[Tuple[str, str]] = []
        self.s3_calls: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        dynamodb_calls = self.dynamodb_calls
        s3_calls = self.s3_calls

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            service = self.meta.service_model.service_name
            if service == "dynamodb" and isinstance(params, dict):
                tables: List[str] = []
                if isinstance(params.get("TableName"), str):
                    tables.append(params["TableName"])
                if isinstance(params.get("RequestItems"), dict):
                    tables.extend(params["RequestItems"].keys())
                for table in tables:
                    dynamodb_calls.append((operation_name, table))
            elif service == "s3" and isinstance(params, dict):
                key = params.get("Key")
                if isinstance(key, str):
                    s3_calls.append((operation_name, key))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> ApiCallRecorder:
    """Provide an API call recorder; call ``attach()`` after seeding data."""
    return ApiCallRecorder(monkeypatch)


@pytest.fixture
def exports_bucket(dynamodb_table: Any) -> Any:
    """Create the exports bucket in moto inside the same mock context as the tables."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=os.environ["EXPORTS_BUCKET"])
    return s3


def assert_within_account_reporting_role_scope(recorder: ApiCallRecorder, expect_dynamodb: bool = True) -> None:
    """Assert recorded calls stay within the #354 scoped account/reporting role policy."""
    if expect_dynamodb:
        assert recorder.dynamodb_calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in recorder.dynamodb_calls}
    tables = {table for _, table in recorder.dynamodb_calls}
    assert operations <= ALLOWED_DYNAMODB_ACTIONS, (
        f"unexpected DynamoDB actions: {operations - ALLOWED_DYNAMODB_ACTIONS}"
    )
    assert tables <= DOMAIN_TABLES, (
        f"handler touched tables outside the account/reporting role scope: {tables - DOMAIN_TABLES}"
    )
    for op, key in recorder.s3_calls:
        assert op in ALLOWED_S3_OPERATIONS, f"unexpected S3 operation: {op}"
        assert key.startswith(ALLOWED_S3_PREFIX), f"S3 access outside reports/ prefix: {key!r}"


def seed_profile(profiles_table: Any, owner_sub: str, profile_id: str, **extra: Any) -> None:
    """Seed a profile owned by owner_sub (ownerAccountId carries the ACCOUNT# prefix)."""
    profiles_table.put_item(
        Item={
            "ownerAccountId": f"ACCOUNT#{owner_sub}",
            "profileId": profile_id,
            "sellerName": "Test Seller",
            **extra,
        }
    )


def seed_campaign(campaigns_table: Any, profile_id: str, campaign_id: str, **extra: Any) -> None:
    """Seed a campaign (PK=profileId, SK=campaignId) with GSI key attributes."""
    campaigns_table.put_item(
        Item={
            "profileId": profile_id,
            "campaignId": campaign_id,
            "campaignName": "Fall",
            "campaignYear": 2024,
            **extra,
        }
    )


def seed_share(shares_table: Any, target_sub: str, permissions: List[str]) -> None:
    """Grant target_sub a share on PROFILE_ID owned by OWNER_SUB."""
    shares_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "targetAccountId": f"ACCOUNT#{target_sub}",
            "ownerAccountId": f"ACCOUNT#{OWNER_SUB}",
            "permissions": permissions,
        }
    )


def report_event(caller_sub: str) -> Dict[str, Any]:
    """AppSync event for requestCampaignReport as the given caller."""
    return {
        "arguments": {"input": {"campaignId": CAMPAIGN_ID, "format": "csv"}},
        "identity": {"sub": caller_sub},
        "requestId": "test-request",
    }


class TestRequestReportScope:
    """request-report reads campaigns/orders and authorizes via profiles/shares."""

    def test_owner_report(
        self,
        dynamodb_table: Any,
        exports_bucket: Any,
        campaigns_table: Any,
        orders_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(dynamodb_table, OWNER_SUB, PROFILE_ID)
        seed_campaign(campaigns_table, PROFILE_ID, CAMPAIGN_ID)
        orders_table.put_item(
            Item={
                "campaignId": CAMPAIGN_ID,
                "orderId": "ORDER#order-1",
                "profileId": PROFILE_ID,
                "customerName": "John Doe",
                "customerPhone": "555-123-4567",
                "totalAmount": 45,
                "lineItems": [{"productName": "Product A", "quantity": 2}],
            }
        )
        api_calls.attach()

        result = request_campaign_report(report_event(OWNER_SUB), lambda_context)

        assert result["status"] == "COMPLETED"
        assert result["reportId"].startswith("REPORT#")
        assert result["reportUrl"]
        # campaigns GSI query + orders query + owner-check GetItem on profiles.
        assert ("Query", CAMPAIGNS_TABLE) in api_calls.dynamodb_calls
        assert ("Query", ORDERS_TABLE) in api_calls.dynamodb_calls
        assert ("GetItem", PROFILES_TABLE) in api_calls.dynamodb_calls
        assert {table for _, table in api_calls.dynamodb_calls} <= {CAMPAIGNS_TABLE, ORDERS_TABLE, PROFILES_TABLE}
        # The report upload stays under the reports/ prefix.
        assert ("PutObject", result_s3_key(api_calls)) in api_calls.s3_calls
        assert_within_account_reporting_role_scope(api_calls)

    def test_shared_reader_report(
        self,
        dynamodb_table: Any,
        exports_bucket: Any,
        campaigns_table: Any,
        orders_table: Any,
        shares_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(dynamodb_table, OWNER_SUB, PROFILE_ID)
        seed_share(shares_table, FRIEND_SUB, ["READ"])
        seed_campaign(campaigns_table, PROFILE_ID, CAMPAIGN_ID)
        orders_table.put_item(
            Item={
                "campaignId": CAMPAIGN_ID,
                "orderId": "ORDER#order-1",
                "profileId": PROFILE_ID,
                "customerName": "John Doe",
                "totalAmount": 45,
                "lineItems": [],
            }
        )
        api_calls.attach()

        result = request_campaign_report(report_event(FRIEND_SUB), lambda_context)

        assert result["status"] == "COMPLETED"
        # check_profile_access: owner miss on profiles, share hit on shares,
        # then share-validity GetItem on profiles using the share's owner.
        assert ("GetItem", SHARES_TABLE) in api_calls.dynamodb_calls
        assert {table for _, table in api_calls.dynamodb_calls} <= {
            CAMPAIGNS_TABLE,
            ORDERS_TABLE,
            PROFILES_TABLE,
            SHARES_TABLE,
        }
        assert_within_account_reporting_role_scope(api_calls)


def result_s3_key(recorder: ApiCallRecorder) -> Optional[str]:
    """Return the S3 key the handler uploaded (there must be exactly one)."""
    assert len(recorder.s3_calls) == 1, f"expected exactly one S3 write, got {recorder.s3_calls}"
    return recorder.s3_calls[0][1]


class TestListUnitCatalogsScope:
    """list-unit-catalogs queries profiles/campaigns, batch-authorizes, reads catalogs."""

    def test_owner_sees_unit_catalogs(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(profiles_table, OWNER_SUB, PROFILE_ID, unitType="Pack", unitNumber=158)
        seed_profile(profiles_table, OTHER_SUB, OTHER_PROFILE_ID, unitType="Pack", unitNumber=158)
        seed_campaign(campaigns_table, PROFILE_ID, CAMPAIGN_ID, catalogId=CATALOG_ID)
        seed_campaign(campaigns_table, OTHER_PROFILE_ID, "CAMPAIGN#campaign-456", catalogId="CATALOG#catalog-456")
        catalogs_table.put_item(Item={"catalogId": CATALOG_ID, "catalogName": "Fall Catalog", "ownerAccountId": f"ACCOUNT#{OWNER_SUB}"})
        catalogs_table.put_item(
            Item={"catalogId": "CATALOG#catalog-456", "catalogName": "Other Catalog", "ownerAccountId": f"ACCOUNT#{OTHER_SUB}"}
        )
        api_calls.attach()

        result = list_unit_catalogs(
            {
                "arguments": {"unitType": "Pack", "unitNumber": 158, "campaignName": "Fall", "campaignYear": 2024},
                "identity": {"sub": OWNER_SUB},
            },
            lambda_context,
        )

        # Only the owned profile's catalog is accessible.
        assert [catalog["catalogId"] for catalog in result] == [CATALOG_ID]
        # profiles GSI query + owned BatchGetItem + shares BatchGetItem (miss)
        # + campaigns query + catalogs GetItem.
        assert ("Query", PROFILES_TABLE) in api_calls.dynamodb_calls
        assert ("BatchGetItem", PROFILES_TABLE) in api_calls.dynamodb_calls
        assert ("BatchGetItem", SHARES_TABLE) in api_calls.dynamodb_calls
        assert ("Query", CAMPAIGNS_TABLE) in api_calls.dynamodb_calls
        assert ("GetItem", CATALOGS_TABLE) in api_calls.dynamodb_calls
        assert_within_account_reporting_role_scope(api_calls)

    def test_owner_sees_unit_campaign_catalogs(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        from src.handlers.list_unit_catalogs import _build_unit_campaign_key

        unit_campaign_key = _build_unit_campaign_key("Pack", 158, "Springfield", "IL", "Fall", 2024)
        seed_profile(profiles_table, OWNER_SUB, PROFILE_ID)
        seed_campaign(
            campaigns_table,
            PROFILE_ID,
            CAMPAIGN_ID,
            catalogId=CATALOG_ID,
            unitCampaignKey=unit_campaign_key,
        )
        catalogs_table.put_item(Item={"catalogId": CATALOG_ID, "catalogName": "Fall Catalog", "ownerAccountId": f"ACCOUNT#{OWNER_SUB}"})
        api_calls.attach()

        result = list_unit_campaign_catalogs(
            {
                "arguments": {
                    "unitType": "Pack",
                    "unitNumber": 158,
                    "city": "Springfield",
                    "state": "IL",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                },
                "identity": {"sub": OWNER_SUB},
            },
            lambda_context,
        )

        assert [catalog["catalogId"] for catalog in result] == [CATALOG_ID]
        # campaigns unitCampaignKey-index query + owned BatchGetItem on
        # profiles (owned hit short-circuits the shares batch) + catalogs
        # GetItem.
        assert ("Query", CAMPAIGNS_TABLE) in api_calls.dynamodb_calls
        assert ("BatchGetItem", PROFILES_TABLE) in api_calls.dynamodb_calls
        assert ("GetItem", CATALOGS_TABLE) in api_calls.dynamodb_calls
        assert_within_account_reporting_role_scope(api_calls)


class RecordingAsyncTable:
    """Minimal aioboto3 Table double that records Query calls with its table name."""

    def __init__(self, table_name: str, items: List[Dict[str, Any]], calls: List[Tuple[str, str]]) -> None:
        self._table_name = table_name
        self._items = items
        self._calls = calls

    async def query(self, **kwargs: Any) -> Dict[str, Any]:
        """Record the Query and return the seeded page (never paginates)."""
        self._calls.append(("Query", self._table_name))
        return {"Items": list(self._items)}


class TestListCatalogsInUseScope:
    """list-catalogs-in-use queries only profiles/shares/campaigns (aioboto3 path).

    moto cannot intercept aiobotocore, so like tests/unit/test_list_catalogs_in_use.py
    this drives the real async orchestrator with a mocked aioboto3 session whose
    Table.query records (operation, table) pairs; the scope assertions are the
    same botocore-layer contract the other domains check.
    """

    @pytest.mark.asyncio
    async def test_queries_only_domain_tables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.handlers.list_catalogs_in_use as module

        calls: List[Tuple[str, str]] = []
        tables_by_name = {
            "kernelworx-profiles-v2-ue1-dev": RecordingAsyncTable(
                PROFILES_TABLE, [{"profileId": PROFILE_ID}], calls
            ),
            "kernelworx-shares-ue1-dev": RecordingAsyncTable(
                SHARES_TABLE, [{"profileId": "PROFILE#shared-1", "permissions": ["READ"]}], calls
            ),
            "kernelworx-campaigns-v2-ue1-dev": RecordingAsyncTable(
                CAMPAIGNS_TABLE, [{"catalogId": CATALOG_ID}], calls
            ),
        }

        async def table_factory(table_name: str) -> RecordingAsyncTable:
            return tables_by_name[table_name]

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table = table_factory
        mock_session = MagicMock()
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_dynamodb
        mock_context.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context

        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids(
                f"ACCOUNT#{OWNER_SUB}"
            )
        finally:
            module.aioboto3.Session = original_session

        assert owned == {CATALOG_ID}
        assert shared_profiles == ["PROFILE#shared-1"]
        assert shared_catalogs == {CATALOG_ID}
        assert calls, "expected the orchestrator to issue DynamoDB queries"
        operations = {op for op, _ in calls}
        table_names = {table for _, table in calls}
        assert operations == {"Query"}, f"list-catalogs-in-use must only Query, got {operations}"
        assert table_names <= DOMAIN_TABLES, f"queries outside the domain role scope: {table_names - DOMAIN_TABLES}"
