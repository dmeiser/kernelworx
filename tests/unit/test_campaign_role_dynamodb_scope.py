"""Behavioral scope check for the #351 scoped campaign execution role.

The campaign-domain Lambda functions (``delete-campaign-orders`` and
``unit-reporting``) run under the scoped per-domain role added in #351 (chunk 1
of the #326 IAM role split). That role grants DynamoDB read actions
(GetItem/Query/BatchGetItem) on exactly the tables the handlers touch
(campaigns, orders, profiles, shares, order_fulfillments), BatchWriteItem on the
fulfillment table, and DeleteItem on the orders table -- each Order goes by a
conditional delete pinned to its ``fulfillmentVersion``, which a batch write
cannot express. See ``tofu/application/modules/iam/main.tf``.

These tests invoke the real handlers against moto DynamoDB while recording
every DynamoDB API call at the botocore layer, then assert the recorded
(operation, table) pairs stay within what the scoped role permits. If a future
change makes these handlers touch another table (for example ``accounts`` via a
shared helper) or issue a write anywhere else, this test fails — the exact
signal needed to re-scope the domain role. Follow-up chunks (#352–#354) should
copy this test for their own domains.
"""

from decimal import Decimal
from typing import Any, Dict, List, Tuple

import botocore.client
import pytest

from src.handlers.campaign_operations import delete_campaign_orders
from src.handlers.campaign_reporting import get_unit_report
from src.utils.ids import build_unit_campaign_key as _build_unit_campaign_key

PROFILE_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"
ORDER_FULFILLMENTS_TABLE = "kernelworx-order-fulfillments-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"

# Tables the #351 campaign role grants read access to. `order_fulfillments` joins the
# scope because deleting a Campaign's Orders takes their fulfillment history with them
# (ARCH-1, children-first).
DOMAIN_TABLES = {PROFILE_TABLE, CAMPAIGNS_TABLE, ORDERS_TABLE, SHARES_TABLE, ORDER_FULFILLMENTS_TABLE}

# Actions the #351 campaign role grants (BatchWriteItem additionally restricted
# to the fulfillment history those Orders own, and DeleteItem to the orders table,
# where the delete must carry the fulfillmentVersion condition a batch cannot).
ALLOWED_ACTIONS = {"GetItem", "Query", "BatchGetItem", "BatchWriteItem", "DeleteItem"}

OWNER_SUB = "owner-sub-001"
FRIEND_SUB = "friend-sub-002"
PROFILE_ID = "PROFILE#profile-123"
CAMPAIGN_ID = "CAMPAIGN#campaign-123"


class DynamoDbCallRecorder:
    """Records DynamoDB API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so both resource-style
    (batch_writer, Table.query) and client-style (batch_get_item) calls are
    captured with their real operation names. Seeding performed before
    ``attach()`` is not recorded.
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


def assert_within_campaign_role_scope(calls: List[Tuple[str, str]]) -> None:
    """Assert recorded calls stay within the #351 scoped campaign role policy."""
    assert calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in calls}
    tables = {table for _, table in calls}
    assert operations <= ALLOWED_ACTIONS, f"unexpected DynamoDB actions: {operations - ALLOWED_ACTIONS}"
    assert tables <= DOMAIN_TABLES, f"handler touched tables outside the campaign role scope: {tables - DOMAIN_TABLES}"
    batch_write_tables = {table for op, table in calls if op == "BatchWriteItem"}
    assert batch_write_tables <= {ORDER_FULFILLMENTS_TABLE}, (
        f"BatchWriteItem outside the order-fulfillments table (Orders go by pinned DeleteItem now): {batch_write_tables}"
    )
    delete_item_tables = {table for op, table in calls if op == "DeleteItem"}
    assert delete_item_tables <= {ORDERS_TABLE}, (
        f"DeleteItem outside the orders table (the fulfillmentVersion-pinned parent delete): {delete_item_tables}"
    )


def seed_campaign_with_orders(
    profiles_table: Any, campaigns_table: Any, orders_table: Any, order_count: int = 3
) -> None:
    """Seed an owner profile, a campaign on it, and orders for that campaign."""
    profiles_table.put_item(
        Item={
            "ownerAccountId": f"ACCOUNT#{OWNER_SUB}",
            "profileId": PROFILE_ID,
            "profileName": "Test Profile",
            "sellerName": "Test Seller",
        }
    )
    campaigns_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "campaignId": CAMPAIGN_ID,
            "campaignName": "Fall",
            "campaignYear": 2024,
            "catalogId": "CATALOG#catalog-123",
            "unitCampaignKey": _build_unit_campaign_key("Pack", 158, "Springfield", "IL", "Fall", 2024),
        }
    )
    for i in range(order_count):
        orders_table.put_item(
            Item={
                "campaignId": CAMPAIGN_ID,
                "orderId": f"ORDER#{i}",
                "customerName": f"Customer {i}",
                "orderDate": "2024-10-01T00:00:00Z",
                "totalAmount": Decimal("10.0"),
            }
        )


def grant_share(shares_table: Any, caller_sub: str, permissions: List[str]) -> None:
    """Grant caller_sub a share on the seeded profile."""
    shares_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "targetAccountId": f"ACCOUNT#{caller_sub}",
            "ownerAccountId": f"ACCOUNT#{OWNER_SUB}",
            "permissions": permissions,
            "createdAt": "2024-01-01T00:00:00Z",
        }
    )


class TestDeleteCampaignOrdersScope:
    """delete-campaign-orders (owner and shared-WRITE paths) stays within the role scope."""

    def test_owner_delete(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        seed_campaign_with_orders(profiles_table, campaigns_table, orders_table)
        order_fulfillments_table.put_item(
            Item={
                "pk": "ORDER#1",
                "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#ful-1",
                "entityType": "OrderFulfillment",
                "orderId": "ORDER#1",
                "campaignId": CAMPAIGN_ID,
                "fulfillmentId": "ful-1",
                "quantity": 2,
                "createdAt": "2024-10-02T00:00:00+00:00",
            }
        )
        dynamodb_calls.attach()

        result = delete_campaign_orders(
            {"arguments": {"campaignId": CAMPAIGN_ID}, "identity": {"sub": OWNER_SUB}}, lambda_context
        )

        assert result == {"deletedCount": 3}
        assert ("DeleteItem", ORDERS_TABLE) in dynamodb_calls.calls
        assert_within_campaign_role_scope(dynamodb_calls.calls)

        # ARCH-1: the Campaign delete takes the fulfillment history with the Orders, and
        # takes it first. A record that outlives its Order can be neither reversed nor read
        # (both surfaces re-load the Order to authorize themselves), while the inventory
        # movement it names has already moved stock.
        assert order_fulfillments_table.scan()["Items"] == [], "the campaign delete orphaned fulfillment history"
        calls = dynamodb_calls.calls
        sweep = next(
            (i for i, (op, table) in enumerate(calls) if table == ORDER_FULFILLMENTS_TABLE and op == "Query"),
            -1,
        )
        # The parent goes by a conditional DeleteItem, never by the batch writer: the
        # condition is what leaves an Order readable when a fulfillment lands during its
        # sweep, which is what makes the next run able to finish the cleanup.
        order_delete = next(
            (i for i, (op, table) in enumerate(calls) if table == ORDERS_TABLE and op == "DeleteItem"), -1
        )
        assert sweep >= 0, "the campaign delete never read the fulfillment history it was about to orphan"
        assert sweep < order_delete, "the campaign deleted its Orders before their fulfillment history"

    def test_shared_writer_delete(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        order_fulfillments_table: Any,
        shares_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        seed_campaign_with_orders(profiles_table, campaigns_table, orders_table)
        grant_share(shares_table, FRIEND_SUB, ["WRITE"])
        dynamodb_calls.attach()

        result = delete_campaign_orders(
            {"arguments": {"campaignId": CAMPAIGN_ID}, "identity": {"sub": FRIEND_SUB}}, lambda_context
        )

        assert result == {"deletedCount": 3}
        assert ("GetItem", SHARES_TABLE) in dynamodb_calls.calls
        assert_within_campaign_role_scope(dynamodb_calls.calls)
        assert order_fulfillments_table.scan()["Items"] == []


class TestGetUnitReportScope:
    """get_unit_report (owner and shared-READ paths) stays within the role scope."""

    @staticmethod
    def _event(caller_sub: str) -> Dict[str, Any]:
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": caller_sub},
        }

    def test_owner_report(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        seed_campaign_with_orders(profiles_table, campaigns_table, orders_table)
        dynamodb_calls.attach()

        result = get_unit_report(self._event(OWNER_SUB), lambda_context)

        assert result["totalOrders"] == 3
        assert len(result["sellers"]) == 1
        # No writes at all on the reporting path.
        assert all(op != "BatchWriteItem" for op, _ in dynamodb_calls.calls)
        assert_within_campaign_role_scope(dynamodb_calls.calls)

    def test_shared_reader_report(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        shares_table: Any,
        lambda_context: Any,
        dynamodb_calls: DynamoDbCallRecorder,
    ) -> None:
        seed_campaign_with_orders(profiles_table, campaigns_table, orders_table)
        grant_share(shares_table, FRIEND_SUB, ["READ"])
        dynamodb_calls.attach()

        result = get_unit_report(self._event(FRIEND_SUB), lambda_context)

        assert result["totalOrders"] == 3
        assert_within_campaign_role_scope(dynamodb_calls.calls)
