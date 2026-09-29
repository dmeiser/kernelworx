"""Behavioral tests for the account-deletion cascade extracted into its own module.

Issue #554: the cascade was split across a circular import (``admin_operations``
imported ``account_operations`` at module scope, so ``account_operations`` had to
import the cascade internals back inside function bodies). That cycle is what
forced every sub-cascade to paginate the profiles table independently, so a
single account deletion issued six redundant ``Query`` sweeps of the caller's
whole profile list.

These tests invoke the real cascade against moto DynamoDB while recording every
DynamoDB call at the botocore layer, so a regression that re-introduces a
redundant sweep fails on the recorded call count rather than on a claim about
the source. The deletion itself is asserted against the real table contents, so
the sweep can never be optimized away by simply not deleting.
"""

import os
from typing import Any, Dict, List, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.deletion_cascade import delete_all_user_data

ACCOUNT_ID = "user-123-456"
ACCOUNT_KEY = f"ACCOUNT#{ACCOUNT_ID}"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"
INVITES_TABLE = "kernelworx-invites-ue1-dev"
ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"

PROFILE_IDS = ("PROFILE#profile-a", "PROFILE#profile-b")


class DynamoDbCallRecorder:
    """Records ``(operation, table)`` for every DynamoDB API call made while attached."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        calls = self.calls

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            if self.meta.service_model.service_name == "dynamodb" and isinstance(params, dict):
                table_name = params.get("TableName")
                if isinstance(table_name, str):
                    calls.append((operation_name, table_name))
                for request_table in params.get("RequestItems") or {}:
                    calls.append((operation_name, request_table))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)

    def count(self, operation: str, table: str) -> int:
        return sum(
            1
            for recorded_operation, recorded_table in self.calls
            if (recorded_operation, recorded_table) == (operation, table)
        )


@pytest.fixture
def dynamodb_calls(monkeypatch: pytest.MonkeyPatch) -> DynamoDbCallRecorder:
    """Provide a DynamoDB call recorder; call ``attach()`` after seeding data."""
    return DynamoDbCallRecorder(monkeypatch)


@pytest.fixture
def seeded_cascade(dynamodb_table: Any, s3_bucket: Any) -> Any:
    """Seed two owned profiles, each with a campaign, an order, a share and an invite."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    accounts = dynamodb.Table(ACCOUNTS_TABLE)
    profiles = dynamodb.Table(PROFILES_TABLE)
    campaigns = dynamodb.Table(CAMPAIGNS_TABLE)
    orders = dynamodb.Table(ORDERS_TABLE)
    shares = dynamodb.Table("kernelworx-shares-ue1-dev")
    invites = dynamodb.Table(INVITES_TABLE)

    accounts.put_item(Item={"accountId": ACCOUNT_KEY, "email": "owner@example.com"})

    for index, profile_id in enumerate(PROFILE_IDS):
        campaign_id = f"CAMPAIGN#campaign-{index}"
        profiles.put_item(
            Item={"ownerAccountId": ACCOUNT_KEY, "profileId": profile_id, "sellerName": f"Seller {index}"}
        )
        campaigns.put_item(
            Item={
                "profileId": profile_id,
                "campaignId": campaign_id,
                "catalogId": f"CATALOG#catalog-{index}",
                "isActive": True,
            }
        )
        orders.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": f"ORDER#order-{index}",
                "status": "PENDING",
            }
        )
        shares.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": "ACCOUNT#friend-sub",
                "permission": "READ",
            }
        )
        invites.put_item(
            Item={"inviteCode": f"INVITE#invite-{index}", "profileId": profile_id, "email": f"f{index}@example.com"}
        )

    return dynamodb


def _remaining(dynamodb: Any, table_name: str) -> int:
    return dynamodb.Table(table_name).scan(Select="COUNT")["Count"]


class TestDeleteAllUserDataProfileSweepCount:
    """The cascade must read the caller's profile list exactly once per deletion."""

    def test_profiles_table_is_queried_once(self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder) -> None:
        dynamodb_calls.attach()

        delete_all_user_data(ACCOUNT_ID)

        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 1, (
            "the account-deletion cascade must paginate the caller's profiles exactly once; "
            f"recorded profile queries: "
            f"{[call for call in dynamodb_calls.calls if call[1] == PROFILES_TABLE]}"
        )

    def test_profiles_table_is_queried_once_for_prefixed_account_id(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        dynamodb_calls.attach()

        delete_all_user_data(ACCOUNT_KEY)

        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 1

    def test_cascade_still_deletes_every_domain(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        """The single sweep must not skip any sub-cascade's deletions."""
        dynamodb_calls.attach()

        delete_all_user_data(ACCOUNT_ID)

        assert _remaining(seeded_cascade, PROFILES_TABLE) == 0
        assert _remaining(seeded_cascade, CAMPAIGNS_TABLE) == 0
        assert _remaining(seeded_cascade, ORDERS_TABLE) == 0
        assert _remaining(seeded_cascade, SHARES_TABLE) == 0
        assert _remaining(seeded_cascade, INVITES_TABLE) == 0
        assert _remaining(seeded_cascade, ACCOUNTS_TABLE) == 0

    def test_profile_sweep_count_is_independent_of_profile_count(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        """Adding profiles must scale the per-profile work, never the profile sweep itself."""
        profiles = seeded_cascade.Table(PROFILES_TABLE)
        for index in range(3, 8):
            profiles.put_item(
                Item={
                    "ownerAccountId": ACCOUNT_KEY,
                    "profileId": f"PROFILE#extra-{index}",
                    "sellerName": f"Extra {index}",
                }
            )

        dynamodb_calls.attach()

        delete_all_user_data(ACCOUNT_ID)

        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 1
        assert _remaining(seeded_cascade, PROFILES_TABLE) == 0


def test_delete_all_user_data_deletes_payment_qr_codes(
    seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """Payment QR objects are purged for the account, independent of the profile sweep."""
    bucket = os.environ["EXPORTS_BUCKET"]
    s3_bucket = boto3.client("s3", region_name="us-east-1")
    s3_bucket.put_object(Bucket=bucket, Key=f"payment-qr-codes/{ACCOUNT_ID}/venmo.png", Body=b"qr")

    delete_all_user_data(ACCOUNT_ID)

    response = s3_bucket.list_objects_v2(Bucket=bucket, Prefix=f"payment-qr-codes/{ACCOUNT_ID}/")
    assert response.get("KeyCount", 0) == 0


def test_delete_all_user_data_accepts_account_id_without_account_row(
    seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """A missing account row is not an error: the cascade still clears the user's data."""
    seeded_cascade.Table(ACCOUNTS_TABLE).delete_item(Key={"accountId": ACCOUNT_KEY})

    delete_all_user_data(ACCOUNT_ID)

    assert _remaining(seeded_cascade, PROFILES_TABLE) == 0


class TestSubCascadeProfileReuse:
    """A sub-cascade must delete from the profile list it is handed, not re-read it."""

    def test_delete_user_orders_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_user_orders

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[0]}]

        deleted = delete_user_orders(ACCOUNT_ID, profiles, _silent_logger())

        assert deleted == 1
        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0
        assert _remaining(seeded_cascade, ORDERS_TABLE) == 1

    def test_delete_user_campaigns_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_user_campaigns

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[0]}]

        deleted = delete_user_campaigns(ACCOUNT_ID, profiles, _silent_logger())

        assert deleted == 1
        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0

    def test_delete_user_shares_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_user_shares

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[1]}]

        deleted = delete_user_shares(ACCOUNT_ID, profiles, _silent_logger())

        assert deleted == 1
        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0

    def test_delete_invites_for_owned_profiles_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_invites_for_owned_profiles

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[0]}]

        deleted = delete_invites_for_owned_profiles(ACCOUNT_ID, profiles, _silent_logger())

        assert deleted == 1
        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0

    def test_delete_user_s3_reports_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_user_s3_reports

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[0]}]

        delete_user_s3_reports(ACCOUNT_ID, profiles, _silent_logger())

        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0

    def test_delete_user_profiles_uses_supplied_profiles(
        self, seeded_cascade: Any, dynamodb_calls: DynamoDbCallRecorder
    ) -> None:
        from src.handlers.deletion_cascade import delete_user_profiles

        dynamodb_calls.attach()
        profiles = [{"ownerAccountId": ACCOUNT_KEY, "profileId": PROFILE_IDS[0]}]

        deleted = delete_user_profiles(ACCOUNT_ID, profiles, _silent_logger())

        assert deleted == 1
        assert dynamodb_calls.count("Query", PROFILES_TABLE) == 0
        assert _remaining(seeded_cascade, PROFILES_TABLE) == 1


def test_get_user_profiles_returns_every_page(dynamodb_table: Any) -> None:
    """``get_user_profiles`` is the single sweep; it must still paginate fully."""
    from src.handlers.deletion_cascade import get_user_profiles

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    profiles = dynamodb.Table(PROFILES_TABLE)
    for index in range(5):
        profiles.put_item(
            Item={"ownerAccountId": ACCOUNT_KEY, "profileId": f"PROFILE#paged-{index}"},
        )
    profiles.put_item(Item={"ownerAccountId": "ACCOUNT#someone-else", "profileId": "PROFILE#other"})

    result: Dict[str, Any] = {"profileIds": sorted(item["profileId"] for item in get_user_profiles(ACCOUNT_KEY))}

    assert result["profileIds"] == [f"PROFILE#paged-{index}" for index in range(5)]


def _silent_logger() -> Any:
    from src.utils.logging import get_logger

    return get_logger("test.deletion_cascade")
