"""Behavioral scope check for the #353 scoped payment execution role.

The payment-domain Lambda functions (``request-qr-upload``,
``confirm-qr-upload``, ``generate-qr-code-presigned-url``, and
``delete-qr-code``) run under the scoped per-domain role added in #353 (chunk 3
of the #326 IAM role split, reusing the wiring pattern #351 established). That
role grants DynamoDB GetItem/Query on exactly the tables the handlers touch
(accounts, profiles, shares — the last two only via the shared
``utils.auth.check_profile_access`` collaborator path), UpdateItem on the
accounts table only (payment methods live in the account record's
``preferences.paymentMethods`` attribute), and S3 GetObject (HeadObject) /
DeleteObject scoped to the ``payment-qr-codes/*`` prefix of the exports bucket.
The pre-signed POST/GET URLs are signed client-side and used by the browser
directly against S3, so they need no Lambda permission. See
``tofu/application/modules/iam/main.tf``.

These tests invoke the real handlers against moto DynamoDB/S3 while recording
every DynamoDB and S3 API call at the botocore layer, then assert the recorded
calls stay within what the scoped role permits. If a future change makes these
handlers touch another table (for example ``orders`` or ``catalogs``) or issue
a write anywhere else, this test fails — the exact signal needed to re-scope
the domain role.
"""

import os
from typing import Any, List, Optional, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.generate_qr_code_presigned_url import generate_qr_code_presigned_url
from src.handlers.payment_methods_handlers import confirm_qr_upload, delete_qr_code, request_qr_upload

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
SHARES_TABLE = "kernelworx-shares-ue1-dev"
EXPORTS_BUCKET = "kernelworx-exports-ue1-dev"

# Tables the #353 payment role grants read access to.
DOMAIN_TABLES = {ACCOUNTS_TABLE, PROFILES_TABLE, SHARES_TABLE}

# Tables the #353 role grants UpdateItem on (accounts preferences rewrites).
UPDATE_TABLES = {ACCOUNTS_TABLE}

# DynamoDB actions the #353 payment role grants. No BatchGetItem: the shared
# auth helper's single-profile path (check_profile_access) uses only
# GetItem/Query, unlike the batch paths other domains rely on.
ALLOWED_DYNAMODB_ACTIONS = {"GetItem", "Query", "UpdateItem"}

# S3 API operations the #353 role permits, and the only object prefix the role
# allows. HeadObject is authorized by the s3:GetObject IAM action.
ALLOWED_S3_OPERATIONS = {"HeadObject", "DeleteObject"}
ALLOWED_S3_PREFIX = "payment-qr-codes/"

OWNER_SUB = "owner-sub-001"
FRIEND_SUB = "friend-sub-002"
PROFILE_ID = "PROFILE#profile-123"
METHOD_NAME = "Venmo"
OLD_QR_KEY = f"{ALLOWED_S3_PREFIX}{OWNER_SUB}/old-qr.png"
NEW_QR_KEY = f"{ALLOWED_S3_PREFIX}{OWNER_SUB}/new-qr.png"


class ApiCallRecorder:
    """Records DynamoDB and S3 API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style
    (Table.get_item/update_item) and client-style calls are captured with
    their real operation names. Seeding performed before ``attach()`` is not
    recorded. Pre-signed URL generation never reaches this layer (it is pure
    client-side signing), which is exactly why the role needs no PutObject /
    GetObject grant for the upload/download URLs themselves.
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
def accounts_table(dynamodb_table: Any) -> Any:
    """Get the accounts DynamoDB table (depends on dynamodb_table for the mock context)."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table(ACCOUNTS_TABLE)


@pytest.fixture
def exports_bucket(dynamodb_table: Any) -> None:
    """Create the exports bucket in moto inside the same mock context as the tables."""

    def _create() -> Any:
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=os.environ["EXPORTS_BUCKET"])
        return s3

    return _create


def assert_within_payment_role_scope(recorder: ApiCallRecorder, expect_dynamodb: bool = True) -> None:
    """Assert recorded calls stay within the #353 scoped payment role policy."""
    if expect_dynamodb:
        assert recorder.dynamodb_calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in recorder.dynamodb_calls}
    tables = {table for _, table in recorder.dynamodb_calls}
    assert operations <= ALLOWED_DYNAMODB_ACTIONS, (
        f"unexpected DynamoDB actions: {operations - ALLOWED_DYNAMODB_ACTIONS}"
    )
    assert tables <= DOMAIN_TABLES, f"handler touched tables outside the payment role scope: {tables - DOMAIN_TABLES}"
    update_tables = {table for op, table in recorder.dynamodb_calls if op == "UpdateItem"}
    assert update_tables <= UPDATE_TABLES, f"UpdateItem outside accounts table: {update_tables}"
    for op, key in recorder.s3_calls:
        assert op in ALLOWED_S3_OPERATIONS, f"unexpected S3 operation: {op}"
        assert key.startswith(ALLOWED_S3_PREFIX), f"S3 access outside payment-qr-codes/ prefix: {key!r}"


def seed_account_with_payment_method(
    accounts_table: Any,
    owner_sub: str = OWNER_SUB,
    method_name: str = METHOD_NAME,
    qr_code_url: Optional[str] = None,
) -> None:
    """Seed an account record holding one custom payment method."""
    accounts_table.put_item(
        Item={
            "accountId": f"ACCOUNT#{owner_sub}",
            "email": "owner@example.com",
            "preferences": {"paymentMethods": [{"name": method_name, "qrCodeUrl": qr_code_url}]},
        }
    )


def seed_profile(profiles_table: Any, owner_sub: str = OWNER_SUB, profile_id: str = PROFILE_ID) -> None:
    """Seed an owner profile."""
    profiles_table.put_item(
        Item={
            "ownerAccountId": f"ACCOUNT#{owner_sub}",
            "profileId": profile_id,
            "sellerName": "Test Seller",
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
        }
    )


class TestRequestQrUploadScope:
    """request-qr-upload reads the account record and only signs client-side."""

    def test_request_upload(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_account_with_payment_method(accounts_table)
        exports_bucket()
        api_calls.attach()

        result = request_qr_upload(
            {"arguments": {"paymentMethodName": METHOD_NAME}, "identity": {"sub": OWNER_SUB}},
            lambda_context,
        )

        assert result["s3Key"].startswith(f"{ALLOWED_S3_PREFIX}{OWNER_SUB}/")
        assert result["uploadUrl"]
        assert result["fields"]
        # Only the accounts read; the pre-signed POST itself makes no S3 API call.
        assert {table for _, table in api_calls.dynamodb_calls} == {ACCOUNTS_TABLE}
        assert all(op == "GetItem" for op, _ in api_calls.dynamodb_calls)
        assert api_calls.s3_calls == []
        assert_within_payment_role_scope(api_calls)


class TestConfirmQrUploadScope:
    """confirm-qr-upload HEADs the new object, deletes the replaced one, updates accounts."""

    def test_confirm_replaces_existing_qr(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_account_with_payment_method(accounts_table, qr_code_url=OLD_QR_KEY)
        s3 = exports_bucket()
        s3.put_object(Bucket=EXPORTS_BUCKET, Key=OLD_QR_KEY, Body=b"old-qr")
        s3.put_object(Bucket=EXPORTS_BUCKET, Key=NEW_QR_KEY, Body=b"new-qr")
        api_calls.attach()

        result = confirm_qr_upload(
            {
                "arguments": {"paymentMethodName": METHOD_NAME, "s3Key": NEW_QR_KEY},
                "identity": {"sub": OWNER_SUB},
            },
            lambda_context,
        )

        assert result == {"name": METHOD_NAME, "qrCodeUrl": NEW_QR_KEY}
        # HeadObject on the new key + DeleteObject on the replaced key.
        assert ("HeadObject", NEW_QR_KEY) in api_calls.s3_calls
        assert ("DeleteObject", OLD_QR_KEY) in api_calls.s3_calls
        assert ("UpdateItem", ACCOUNTS_TABLE) in api_calls.dynamodb_calls
        assert_within_payment_role_scope(api_calls)


class TestDeleteQrCodeScope:
    """delete-qr-code deletes the stored object and clears the key on accounts."""

    def test_delete_qr(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_account_with_payment_method(accounts_table, qr_code_url=OLD_QR_KEY)
        s3 = exports_bucket()
        s3.put_object(Bucket=EXPORTS_BUCKET, Key=OLD_QR_KEY, Body=b"old-qr")
        api_calls.attach()

        result = delete_qr_code(
            {"arguments": {"paymentMethodName": METHOD_NAME}, "identity": {"sub": OWNER_SUB}},
            lambda_context,
        )

        assert result is True
        assert ("DeleteObject", OLD_QR_KEY) in api_calls.s3_calls
        assert ("UpdateItem", ACCOUNTS_TABLE) in api_calls.dynamodb_calls
        assert_within_payment_role_scope(api_calls)


class TestGenerateQrCodePresignedUrlScope:
    """generate-qr-code-presigned-url signs only; collaborator path reads profiles/shares."""

    def test_owner_single_key_is_pure_signing(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        exports_bucket()
        api_calls.attach()

        result = generate_qr_code_presigned_url(
            {
                "qrCodeUrl": f"https://example/{OLD_QR_KEY}",
                "ownerAccountId": OWNER_SUB,
                "identity": {"sub": OWNER_SUB},
                "methodName": METHOD_NAME,
                "s3Key": OLD_QR_KEY,
            },
            None,
        )

        assert result is not None
        # Owner short-circuit: no DynamoDB auth reads and no S3 API calls.
        assert api_calls.dynamodb_calls == []
        assert api_calls.s3_calls == []
        assert_within_payment_role_scope(api_calls, expect_dynamodb=False)

    def test_owner_batch_keys_is_pure_signing(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        exports_bucket()
        api_calls.attach()

        result = generate_qr_code_presigned_url(
            {
                "s3Keys": [OLD_QR_KEY, NEW_QR_KEY],
                "ownerAccountId": OWNER_SUB,
                "identity": {"sub": OWNER_SUB},
                "methodName": "",
                "profileId": None,
            },
            None,
        )

        assert result is not None
        assert set(result.keys()) == {OLD_QR_KEY, NEW_QR_KEY}
        assert api_calls.dynamodb_calls == []
        assert api_calls.s3_calls == []
        assert_within_payment_role_scope(api_calls, expect_dynamodb=False)

    def test_collaborator_uses_auth_helper_within_scope(
        self,
        profiles_table: Any,
        shares_table: Any,
        accounts_table: Any,
        exports_bucket: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_profile(profiles_table)
        seed_share(shares_table, FRIEND_SUB, ["WRITE"])
        exports_bucket()
        api_calls.attach()

        result = generate_qr_code_presigned_url(
            {
                "qrCodeUrl": f"https://example/{OLD_QR_KEY}",
                "ownerAccountId": OWNER_SUB,
                "identity": {"sub": FRIEND_SUB},
                "methodName": METHOD_NAME,
                "s3Key": OLD_QR_KEY,
                "profileId": PROFILE_ID,
            },
            None,
        )

        assert result is not None
        # check_profile_access: owner miss + share hit on profiles/shares only.
        assert {table for _, table in api_calls.dynamodb_calls} <= {PROFILES_TABLE, SHARES_TABLE}
        assert ("GetItem", SHARES_TABLE) in api_calls.dynamodb_calls
        assert api_calls.s3_calls == []
        assert_within_payment_role_scope(api_calls)

    def test_owner_fallback_lookup_heads_slug_keys(
        self,
        accounts_table: Any,
        exports_bucket: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        s3 = exports_bucket()
        slug_key = f"{ALLOWED_S3_PREFIX}{OWNER_SUB}/venmo.png"
        s3.put_object(Bucket=EXPORTS_BUCKET, Key=slug_key, Body=b"qr")
        api_calls.attach()

        result = generate_qr_code_presigned_url(
            {
                "qrCodeUrl": "legacy-url-value",
                "ownerAccountId": OWNER_SUB,
                "identity": {"sub": OWNER_SUB},
                "methodName": METHOD_NAME,
                "s3Key": None,
            },
            None,
        )

        assert result is not None
        # _find_existing_qr_s3_key HEADs candidate slug keys until one exists.
        assert ("HeadObject", slug_key) in api_calls.s3_calls
        assert api_calls.dynamodb_calls == []
        assert_within_payment_role_scope(api_calls, expect_dynamodb=False)
