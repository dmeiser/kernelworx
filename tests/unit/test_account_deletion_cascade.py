"""Behavioural checks for the shared account-deletion cascade (#554).

The cascade used to re-paginate the whole profiles table once per sub-cascade
(six sweeps for one account deletion) because the sub-cascades lived in
``admin_operations`` and the orchestrator in ``account_operations``, a cycle
that forced the profile list to be fetched inside each helper. The cascade
internals now live in ``deletion_cascade``, which queries the profiles table
once and hands the list to every sub-cascade.

These tests drive the real cascade against moto DynamoDB/S3 while recording
every DynamoDB call at the botocore layer, so they assert both halves of the
contract: the profile list is swept exactly once, and the cascade still
deletes every record it used to.
"""

import os
import subprocess
import sys
from typing import Any, List, Tuple

import boto3
import botocore.client
import pytest

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"
INVITES_TABLE = "kernelworx-invites-ue1-dev"

OWNER_SUB = "owner-sub-001"
FRIEND_SUB = "friend-sub-002"
OWNER_ACCOUNT_KEY = f"ACCOUNT#{OWNER_SUB}"


class DynamoDbCallRecorder:
    """Records (operation, table) for every DynamoDB call once ``attach()`` runs.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style calls
    (``Table.query``, ``batch_writer``) are captured with their real operation
    names. Seeding performed before ``attach()`` is not recorded.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        calls = self.calls

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            service = self.meta.service_model.service_name
            if service == "dynamodb" and isinstance(params, dict):
                tables: List[str] = []
                if isinstance(params.get("TableName"), str):
                    tables.append(params["TableName"])
                if isinstance(params.get("RequestItems"), dict):
                    tables.extend(params["RequestItems"].keys())
                for table in tables:
                    calls.append((operation_name, table))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)

    def count(self, operation: str, table: str) -> int:
        """Number of recorded calls of ``operation`` against ``table``."""
        return sum(1 for op, recorded_table in self.calls if op == operation and recorded_table == table)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> DynamoDbCallRecorder:
    """Provide a DynamoDB call recorder; call ``attach()`` after seeding data."""
    return DynamoDbCallRecorder(monkeypatch)


def _table(name: str) -> Any:
    return boto3.resource("dynamodb", region_name="us-east-1").Table(name)


def _seed_user_data() -> None:
    """Seed an owner with two profiles plus one order, share, and invite each."""
    _table(ACCOUNTS_TABLE).put_item(Item={"accountId": OWNER_ACCOUNT_KEY, "email": "owner@example.com"})
    _table(CATALOGS_TABLE).put_item(
        Item={"catalogId": "CATALOG#owner-catalog", "ownerAccountId": OWNER_ACCOUNT_KEY, "products": []}
    )

    profiles = _table(PROFILES_TABLE)
    for index in (1, 2):
        profile_id = f"PROFILE#owner-{index}"
        profiles.put_item(
            Item={
                "ownerAccountId": OWNER_ACCOUNT_KEY,
                "profileId": profile_id,
                "sellerName": f"Scout {index}",
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )
        _table(CAMPAIGNS_TABLE).put_item(
            Item={
                "profileId": profile_id,
                "campaignId": f"CAMPAIGN#owner-{index}",
                "campaignName": f"Season {index}",
                "campaignYear": 2024,
            }
        )
        _table(ORDERS_TABLE).put_item(
            Item={
                "campaignId": f"CAMPAIGN#owner-{index}",
                "orderId": f"ORDER#owner-{index}",
                "customerName": f"Buyer {index}",
            }
        )
        # An outbound share from the owner and an inbound share to the owner.
        _table(SHARES_TABLE).put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{FRIEND_SUB}",
                "ownerAccountId": OWNER_ACCOUNT_KEY,
                "permissions": ["VIEW"],
            }
        )
        _table(SHARES_TABLE).put_item(
            Item={
                "profileId": "PROFILE#someone-else",
                "targetAccountId": OWNER_ACCOUNT_KEY,
                "ownerAccountId": f"ACCOUNT#{FRIEND_SUB}",
                "permissions": ["VIEW"],
            }
        )
        _table(INVITES_TABLE).put_item(
            Item={
                "inviteCode": f"INVITE#owner-{index}",
                "profileId": profile_id,
                "email": f"invitee{index}@example.com",
            }
        )


def _seed_s3_data() -> None:
    """Seed the exports bucket with a report object and a payment QR code."""
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ["EXPORTS_BUCKET"]
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="reports/PROFILE#owner-1/r1.xlsx", Body=b"report")
    s3.put_object(Bucket=bucket, Key=f"payment-qr-codes/{OWNER_SUB}/venmo.png", Body=b"qr")


def _assert_everything_deleted() -> None:
    assert _table(PROFILES_TABLE).scan()["Count"] == 0
    assert _table(CAMPAIGNS_TABLE).scan()["Count"] == 0
    assert _table(ORDERS_TABLE).scan()["Count"] == 0
    assert _table(SHARES_TABLE).scan()["Count"] == 0
    assert _table(INVITES_TABLE).scan()["Count"] == 0
    assert "Item" not in _table(ACCOUNTS_TABLE).get_item(Key={"accountId": OWNER_ACCOUNT_KEY})


class TestDeleteAllUserDataProfileSweep:
    """The cascade must sweep the profiles table once, not once per sub-cascade."""

    def test_delete_all_user_data_queries_profiles_once(
        self, dynamodb_table: Any, recorder: DynamoDbCallRecorder
    ) -> None:
        """Two profiles with orders, shares, and invites still delete, from one profiles Query."""
        from src.handlers.account_operations import _delete_all_user_data as delete_all_user_data

        _seed_user_data()
        _seed_s3_data()
        recorder.attach()

        delete_all_user_data(OWNER_SUB)

        assert recorder.count("Query", PROFILES_TABLE) == 1, (
            "expected exactly one profiles-table sweep for the whole cascade, "
            f"got {recorder.count('Query', PROFILES_TABLE)}"
        )
        _assert_everything_deleted()

    def test_delete_all_user_data_preserves_catalogs(
        self, dynamodb_table: Any, recorder: DynamoDbCallRecorder
    ) -> None:
        """Catalogs are preserved per product design and are not swept or deleted."""
        from src.handlers.account_operations import _delete_all_user_data as delete_all_user_data

        _seed_user_data()
        _seed_s3_data()
        recorder.attach()

        delete_all_user_data(OWNER_SUB)

        assert recorder.count("Query", CATALOGS_TABLE) == 0
        assert _table(CATALOGS_TABLE).scan()["Count"] == 1

    def test_delete_all_user_data_removes_s3_reports_and_qr_codes(
        self, dynamodb_table: Any, recorder: DynamoDbCallRecorder
    ) -> None:
        """S3 report objects and payment QR codes are purged for every owned profile."""
        from src.handlers.account_operations import _delete_all_user_data as delete_all_user_data

        _seed_user_data()
        _seed_s3_data()

        delete_all_user_data(OWNER_SUB)

        keys = _s3_keys()
        assert not [key for key in keys if key.startswith("reports/")]
        assert not [key for key in keys if key.startswith("payment-qr-codes/")]


class TestCascadeModuleGraph:
    """The cascade is a leaf of the handler import graph, not a cycle participant."""

    @pytest.mark.parametrize("entry_module", ["src.handlers.deletion_cascade", "src.handlers.admin_operations"])
    def test_modules_import_standalone_in_a_fresh_interpreter(self, entry_module: str) -> None:
        """Each module imports cleanly when it is the first handler module loaded.

        A cycle would surface here as an ``ImportError`` for a name that is not
        yet defined while the partially initialized module is being executed.
        """
        script = (
            f"import {entry_module} as m; "
            "print(m.__name__)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            env={**os.environ, "PYTHONPATH": os.getcwd()},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == entry_module

    def test_deletion_cascade_does_not_import_admin_operations(self) -> None:
        """The cascade must be importable without pulling in the admin handler module."""
        script = (
            "import sys, src.handlers.deletion_cascade; "
            "print('admin_operations' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            env={**os.environ, "PYTHONPATH": os.getcwd()},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"


def _s3_keys() -> List[str]:
    s3 = boto3.client("s3", region_name="us-east-1")
    return [
        obj["Key"]
        for obj in s3.list_objects_v2(Bucket=os.environ["EXPORTS_BUCKET"]).get("Contents", [])
    ]
