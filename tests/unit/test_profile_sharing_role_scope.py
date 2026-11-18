"""Behavioral scope check for the #352 scoped profile/sharing execution role.

The profile/sharing-domain Lambda functions (``transfer-ownership`` and
``delete-profile-cascade``; ``list-my-shares`` was removed when listMyShares
migrated to an AppSync JS pipeline in #334) run under the scoped
per-domain role added in #352 (chunk 2 of the #326 IAM role split, reusing the
wiring pattern #351 established). That role grants DynamoDB read actions
(GetItem/Query/BatchGetItem) on exactly the tables the handlers touch
(profiles, shares, invites, campaigns, orders), item-level writes on
profiles/shares (including TransactWriteItems for the ownership transfer),
BatchWriteItem deletes on the cascade tables, and a conditioned DeleteItem on the
orders table -- each Order goes by a delete pinned to its ``fulfillmentVersion``,
the retry mechanism of the ARCH-1 deletion lifecycle. It also grants S3
ListBucketVersions/DeleteObject/DeleteObjectVersion scoped to the
``reports/*`` prefix of the exports bucket for cascade report cleanup. See
``tofu/application/modules/iam/main.tf``.

These tests invoke the real handlers against moto DynamoDB/S3 while recording
every DynamoDB and S3 API call at the botocore layer, then assert the recorded
calls stay within what the scoped role permits. If a future change makes these
handlers touch another table (for example ``accounts`` or ``catalogs`` via a
shared helper) or issue a write anywhere else, this test fails — the exact
signal needed to re-scope the domain role.
"""

import os
from typing import Any, List, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.delete_profile_cascade import lambda_handler as cascade_handler
from src.handlers.transfer_profile_ownership import lambda_handler as transfer_handler

PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"
INVITES_TABLE = "kernelworx-invites-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"
ORDER_FULFILLMENTS_TABLE = "kernelworx-order-fulfillments-ue1-dev"
EXPORTS_BUCKET = "kernelworx-exports-ue1-dev"

# Tables the #352 profile/sharing role grants read access to.
# `order_fulfillments` joins the scope because the cascade now deletes each Campaign's
# fulfillment history before the Orders that own it (ARCH-1, children-first).
DOMAIN_TABLES = {PROFILES_TABLE, SHARES_TABLE, INVITES_TABLE, CAMPAIGNS_TABLE, ORDERS_TABLE, ORDER_FULFILLMENTS_TABLE}

# Tables the #352 role grants BatchWriteItem on (cascade batch_writer deletes).
# Orders are not among them: each Order goes by a conditioned DeleteItem pinned to its
# fulfillmentVersion, which is the retry mechanism of the ARCH-1 lifecycle.
BATCH_WRITE_TABLES = {SHARES_TABLE, INVITES_TABLE, CAMPAIGNS_TABLE, ORDER_FULFILLMENTS_TABLE}

# Tables the #352 role grants item-level DeleteItem on. The orders entry is the
# fulfillmentVersion-pinned parent delete of the cascade.
DELETE_ITEM_TABLES = {PROFILES_TABLE, SHARES_TABLE, ORDERS_TABLE}

# DynamoDB actions the #352 profile/sharing role grants.
ALLOWED_DYNAMODB_ACTIONS = {
    "GetItem",
    "Query",
    "BatchGetItem",
    "BatchWriteItem",
    "PutItem",
    "UpdateItem",
    "DeleteItem",
    "TransactWriteItems",
}

# S3 API operations the #352 role permits for report cleanup, and the only
# object prefix the role allows.
ALLOWED_S3_OPERATIONS = {"ListObjectVersions", "DeleteObjects"}
ALLOWED_S3_PREFIX = "reports/"

OWNER_SUB = "owner-sub-001"
FRIEND_SUB = "friend-sub-002"
THIRD_PARTY_SUB = "friend-sub-003"
NEW_OWNER_SUB = "new-owner-sub-004"
PROFILE_ID = "PROFILE#profile-123"
CAMPAIGN_ID = "CAMPAIGN#campaign-123"


class ApiCallRecorder:
    """Records DynamoDB and S3 API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so both resource-style
    (batch_writer, Table.query) and client-style (batch_get_item,
    transact_write_items) calls are captured with their real operation names.
    Seeding performed before ``attach()`` is not recorded.
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
                # TransactWriteItems nests table names inside TransactItems.
                for item in params.get("TransactItems", []) or []:
                    if isinstance(item, dict):
                        for op in ("Put", "Delete", "Update", "ConditionCheck"):
                            if isinstance(item.get(op), dict) and isinstance(item[op].get("TableName"), str):
                                tables.append(item[op]["TableName"])
                for table in tables:
                    dynamodb_calls.append((operation_name, table))
            elif service == "s3" and isinstance(params, dict):
                # ListObjectVersions carries Prefix; DeleteObjects carries the
                # object keys in the request body.
                subjects: List[str] = []
                if isinstance(params.get("Prefix"), str):
                    subjects.append(params["Prefix"])
                delete = params.get("Delete")
                if isinstance(delete, dict):
                    for obj in delete.get("Objects", []) or []:
                        if isinstance(obj, dict) and isinstance(obj.get("Key"), str):
                            subjects.append(obj["Key"])
                if not subjects:
                    subjects.append("")
                for subject in subjects:
                    s3_calls.append((operation_name, subject))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> ApiCallRecorder:
    """Provide an API call recorder; call ``attach()`` after seeding data."""
    return ApiCallRecorder(monkeypatch)


@pytest.fixture
def exports_bucket(dynamodb_table: Any) -> None:
    """Create the exports bucket in moto so cascade S3 cleanup runs against a real bucket.

    Depends on dynamodb_table so the bucket is created inside the same active
    mock_aws context as the DynamoDB tables.
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=os.environ["EXPORTS_BUCKET"])


def assert_within_profile_sharing_role_scope(recorder: ApiCallRecorder) -> None:
    """Assert recorded calls stay within the #352 scoped profile/sharing role policy."""
    assert recorder.dynamodb_calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in recorder.dynamodb_calls}
    tables = {table for _, table in recorder.dynamodb_calls}
    assert operations <= ALLOWED_DYNAMODB_ACTIONS, (
        f"unexpected DynamoDB actions: {operations - ALLOWED_DYNAMODB_ACTIONS}"
    )
    assert tables <= DOMAIN_TABLES, (
        f"handler touched tables outside the profile/sharing role scope: {tables - DOMAIN_TABLES}"
    )
    batch_write_tables = {table for op, table in recorder.dynamodb_calls if op == "BatchWriteItem"}
    assert batch_write_tables <= BATCH_WRITE_TABLES, f"BatchWriteItem outside cascade tables: {batch_write_tables}"
    delete_item_tables = {table for op, table in recorder.dynamodb_calls if op == "DeleteItem"}
    assert delete_item_tables <= DELETE_ITEM_TABLES, (
        f"DeleteItem outside the item-level tables of the #352 role: {delete_item_tables}"
    )
    transact_tables = {table for op, table in recorder.dynamodb_calls if op == "TransactWriteItems"}
    assert transact_tables <= {PROFILES_TABLE}, f"TransactWriteItems outside profiles table: {transact_tables}"
    for op, subject in recorder.s3_calls:
        assert op in ALLOWED_S3_OPERATIONS, f"unexpected S3 operation: {op}"
        assert subject.startswith(ALLOWED_S3_PREFIX), f"S3 access outside reports/ prefix: {subject!r}"


def seed_profile(profiles_table: Any, owner_sub: str = OWNER_SUB, profile_id: str = PROFILE_ID) -> None:
    """Seed an owner profile with the fields the sharing handlers validate."""
    profiles_table.put_item(
        Item={
            "ownerAccountId": f"ACCOUNT#{owner_sub}",
            "profileId": profile_id,
            "sellerName": "Test Seller",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-02T00:00:00Z",
        }
    )


def seed_share(shares_table: Any, target_sub: str, permissions: List[str]) -> None:
    """Grant target_sub a share on the seeded profile."""
    shares_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "targetAccountId": f"ACCOUNT#{target_sub}",
            "ownerAccountId": f"ACCOUNT#{OWNER_SUB}",
            "permissions": permissions,
            "createdAt": "2024-01-01T00:00:00Z",
        }
    )


def seed_fulfillment_for_order(order_fulfillments_table: Any, order_id: str = "ORDER#1") -> None:
    """Seed one fulfillment record of that Order, the way the fulfillment path writes it."""
    order_fulfillments_table.put_item(
        Item={
            "pk": order_id,
            "sk": f"FULFILLMENT#2024-10-02T00:00:00+00:00#ful-{order_id}",
            "entityType": "OrderFulfillment",
            "orderId": order_id,
            "campaignId": CAMPAIGN_ID,
            "fulfillmentId": f"ful-{order_id}",
            "lineItemId": "line-1",
            "productId": "PROD#1",
            "recordType": "FULFILL",
            "quantity": 2,
            "source": "KERNEL_STOCK",
            "createdAt": "2024-10-02T00:00:00+00:00",
        }
    )


def seed_campaign_with_order(campaigns_table: Any, orders_table: Any) -> None:
    """Seed a campaign on the profile and one order for it."""
    campaigns_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "campaignId": CAMPAIGN_ID,
            "campaignName": "Fall",
            "campaignYear": 2024,
        }
    )
    orders_table.put_item(
        Item={
            "campaignId": CAMPAIGN_ID,
            "orderId": "ORDER#1",
            "customerName": "Customer 1",
            "orderDate": "2024-10-01T00:00:00Z",
        }
    )


class TestTransferOwnershipScope:
    """transfer-ownership (transactional profile rewrite + share updates) stays within scope."""

    def test_transfer_updates_shares(
        self,
        profiles_table: Any,
        shares_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(profiles_table)
        seed_share(shares_table, NEW_OWNER_SUB, ["READ", "WRITE"])
        seed_share(shares_table, THIRD_PARTY_SUB, ["READ"])
        api_calls.attach()

        result = transfer_handler(
            {
                "identity": {"sub": OWNER_SUB},
                "arguments": {"input": {"profileId": PROFILE_ID, "newOwnerAccountId": NEW_OWNER_SUB}},
            },
            lambda_context,
        )

        assert result["ownerAccountId"] == f"ACCOUNT#{NEW_OWNER_SUB}"
        # The ownership rewrite is a single transaction on the profiles table.
        assert ("TransactWriteItems", PROFILES_TABLE) in api_calls.dynamodb_calls
        assert_within_profile_sharing_role_scope(api_calls)


class TestDeleteProfileCascadeScope:
    """delete-profile-cascade (batch deletes + S3 report purge) stays within scope."""

    def test_cascade_delete_with_s3_report_cleanup(
        self,
        profiles_table: Any,
        shares_table: Any,
        invites_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        order_fulfillments_table: Any,
        exports_bucket: None,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(profiles_table)
        seed_share(shares_table, FRIEND_SUB, ["READ"])
        seed_campaign_with_order(campaigns_table, orders_table)
        invites_table.put_item(
            Item={
                "inviteCode": "INVITE#1",
                "profileId": PROFILE_ID,
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.put_object(Bucket=EXPORTS_BUCKET, Key=f"reports/{PROFILE_ID}/report.csv", Body=b"data")
        api_calls.attach()

        result = cascade_handler(
            {"arguments": {"profileId": PROFILE_ID}, "identity": {"sub": OWNER_SUB}},
            lambda_context,
        )

        assert result is True
        # BatchWriter deletes hit the three batched cascade tables. Orders are not among
        # them: each one goes by a DeleteItem carrying its fulfillmentVersion condition.
        batch_write_tables = {table for op, table in api_calls.dynamodb_calls if op == "BatchWriteItem"}
        assert batch_write_tables == {SHARES_TABLE, INVITES_TABLE, CAMPAIGNS_TABLE}
        assert ("DeleteItem", ORDERS_TABLE) in api_calls.dynamodb_calls
        # Report purge used the versioned-listing + delete path.
        assert ("ListObjectVersions", f"reports/{PROFILE_ID}/") in api_calls.s3_calls
        assert_within_profile_sharing_role_scope(api_calls)
        remaining = s3.list_objects_v2(Bucket=EXPORTS_BUCKET, Prefix=f"reports/{PROFILE_ID}/")
        assert remaining.get("Contents", []) == []

    def test_cascade_delete_without_s3_objects_stays_in_dynamodb_scope(
        self,
        profiles_table: Any,
        shares_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        order_fulfillments_table: Any,
        exports_bucket: None,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(profiles_table)
        seed_share(shares_table, FRIEND_SUB, ["READ"])
        seed_campaign_with_order(campaigns_table, orders_table)
        seed_fulfillment_for_order(order_fulfillments_table)
        api_calls.attach()

        result = cascade_handler(
            {"arguments": {"profileId": PROFILE_ID}, "identity": {"sub": OWNER_SUB}},
            lambda_context,
        )

        assert result is True
        assert_within_profile_sharing_role_scope(api_calls)

        # ARCH-1: the Order delete takes its fulfillment history with it. The record is
        # append-only, keyed by the Order, and both the reversal path and the audit read
        # re-load the Order to authorize themselves -- so an orphan is a record nobody can
        # reverse, cannot reach, and whose inventory movement already moved stock.
        remaining = order_fulfillments_table.scan()
        assert remaining["Items"] == [], "the cascade left fulfillment history behind its Order"

        # Children-first, in the recorded call order: the history sweep precedes the
        # conditioned DeleteItem that removes the Order, so a failure partway through
        # leaves an Order whose history is intact rather than one that lost part of its
        # accounting -- and an Order that is still readable is what a retry needs.
        calls = api_calls.dynamodb_calls
        sweep = next(i for i, (op, table) in enumerate(calls) if table == ORDER_FULFILLMENTS_TABLE and op == "Query")
        order_delete = next(i for i, (op, table) in enumerate(calls) if table == ORDERS_TABLE and op == "DeleteItem")
        assert sweep < order_delete, "the cascade deleted the Order before its fulfillment history"
