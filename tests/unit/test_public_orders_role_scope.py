"""Scope contract for the #679 public-orders Lambda execution role.

The public-orders domain role is the one anonymous-facing execution role in the
stack: it backs ``publicGetOrderOffer`` and ``publicGetOrderReceipt``, which
AppSync admits with the public API key alone. The role grants DynamoDB GetItem
on exactly the five tables the two reads touch, Query on the profiles and
campaigns tables plus their locator GSIs (``profileId-index``,
``campaignId-index``), and s3:GetObject scoped to the ``payment-qr-codes/*``
prefix of the exports bucket. It grants NO DynamoDB write anywhere — the
public order write runs through the AppSync OrdersDS datasource under the
AppSync service role — and no S3 API call (the QR pre-signing is pure
client-side signing; the grant exists because S3 authorizes a pre-signed GET
against the SIGNING principal's policy at request time, #353).

Two halves, mirroring tests/unit/test_payment_role_scope.py:

- Static: the inline policy documents in
  ``tofu/application/modules/iam/main.tf`` are the role's actual grants, and
  the behavioral recorder can never observe the S3 statement (no handler S3
  call reaches it), so the statement's actions and resource are asserted from
  the parsed policy directly.
- Behavioral: the real offer + receipt handlers run against moto while every
  DynamoDB and S3 call is recorded at the botocore layer; the recorded calls
  must stay within the role's scope — in particular no
  PutItem/UpdateItem/DeleteItem/TransactionWrite on the orders table is ever
  issued.

If a future change makes these handlers touch another table, issue a write,
or call S3 directly, this test fails — the signal needed to re-scope the role.
"""

from __future__ import annotations

from typing import Any, List

import boto3
import pytest

from src.handlers.public_orders_offer import handler as public_orders_handler
from tests.unit.test_edge_security import TF_APP, load_hcl
from tests.unit.test_payment_role_scope import ApiCallRecorder

IAM_MAIN = TF_APP / "modules" / "iam" / "main.tf"

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"

# Tables the role grants GetItem on, and the subset that also gets Query
# (the two locator tables).
GET_TABLES = {ACCOUNTS_TABLE, PROFILES_TABLE, CAMPAIGNS_TABLE, CATALOGS_TABLE, ORDERS_TABLE}
QUERY_TABLES = {PROFILES_TABLE, CAMPAIGNS_TABLE}

# DynamoDB operations the role grants, as the botocore recorder names them.
# Write operations are absent by design; the assertions below check the whole
# vocabulary, so a newly granted write fails before it fails the behavioral check.
ALLOWED_DYNAMODB_ACTIONS = {"GetItem", "Query"}

# The same grant as the policy documents phrase it (service-qualified).
ALLOWED_POLICY_ACTIONS = {"dynamodb:GetItem", "dynamodb:Query"}

CAMPAIGN_ID = "CAMPAIGN#c1"
PROFILE_ID = "PROFILE#p1"
CATALOG_ID = "CATALOG#k1"
ACCOUNT_ID = "ACCOUNT#sub1"
ORDER_SUFFIX = "s1"
ORDER_ID = f"ORDER#c1#{ORDER_SUFFIX}"
TOKEN = "tok"
RECEIPT_TOKEN = "rtok"
QR_S3_KEY = "payment-qr-codes/sub1/venmo.png"


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> ApiCallRecorder:
    """Provide an API call recorder; call ``attach()`` after seeding data."""
    return ApiCallRecorder(monkeypatch)


@pytest.fixture
def accounts_table(dynamodb_table: Any) -> Any:
    """Accounts table handle within the moto context (no dedicated conftest fixture)."""
    return boto3.resource("dynamodb", region_name="us-east-1").Table(ACCOUNTS_TABLE)


def _event(arguments: Any, field: str) -> Any:
    return {"arguments": arguments, "info": {"fieldName": field}, "identity": None}


def assert_within_public_orders_role_scope(recorder: ApiCallRecorder) -> None:
    """Assert recorded calls stay within the public-orders role policy."""
    assert recorder.dynamodb_calls, "expected the handler to issue DynamoDB calls"
    operations = {op for op, _ in recorder.dynamodb_calls}
    tables = {table for _, table in recorder.dynamodb_calls}
    assert operations <= ALLOWED_DYNAMODB_ACTIONS, (
        f"unexpected DynamoDB actions: {operations - ALLOWED_DYNAMODB_ACTIONS}"
    )
    assert tables <= GET_TABLES, f"handler touched tables outside the public-orders role scope: {tables - GET_TABLES}"
    queried = {table for op, table in recorder.dynamodb_calls if op == "Query"}
    assert queried <= QUERY_TABLES, f"Query outside the locator tables: {queried - QUERY_TABLES}"
    order_writes = {(op, table) for op, table in recorder.dynamodb_calls if table == ORDERS_TABLE and op != "GetItem"}
    assert not order_writes, f"the public-orders role must never write the orders table: {order_writes}"
    # QR pre-signing is pure client-side signing; no S3 API call may be recorded.
    assert recorder.s3_calls == [], f"unexpected S3 API calls: {recorder.s3_calls}"


# ---------------------------------------------------------------------------
# Static half: the role's actual inline policy documents
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> List[Any]:
    """python-hcl2 collapses a single-item list to a scalar; unwrap uniformly."""
    return value if isinstance(value, list) else [value]


def _policy_documents() -> Any:
    doc = load_hcl(IAM_MAIN)
    found = {}
    for data in doc.get("data", []):
        for data_type, instances in data.items():
            if data_type != "aws_iam_policy_document":
                continue
            for name, attributes in instances.items():
                if isinstance(name, str) and name.startswith("lambda_public_orders"):
                    found[name] = [dict(statement) for statement in attributes.get("statement", [])]
    return found


def test_dynamodb_policy_grants_only_reads_on_the_five_tables() -> None:
    statements = _policy_documents()["lambda_public_orders_dynamodb"]
    assert all(statement.get("effect") == "Allow" for statement in statements)

    actions = {action for statement in statements for action in statement.get("actions", [])}
    assert actions == ALLOWED_POLICY_ACTIONS, f"unexpected actions in the policy: {actions}"

    by_action = {statement["actions"][0]: _as_list(statement["resources"]) for statement in statements}
    # GetItem covers all five tables; Query only the two locator tables plus
    # their GSIs.
    assert by_action["dynamodb:GetItem"] == ["${local.public_orders_table_arns}"]
    assert by_action["dynamodb:Query"] == ["${concat(local.public_orders_query_arns, local.public_orders_index_arns)}"]


def test_local_table_scopes_match_the_declared_contracts() -> None:
    doc = load_hcl(IAM_MAIN)
    locals_by_key = {key: value for block in doc.get("locals", []) for key, value in block.items()}
    assert locals_by_key["public_orders_table_keys"] == ["profiles", "campaigns", "catalogs", "accounts", "orders"]
    assert locals_by_key["public_orders_query_keys"] == ["profiles", "campaigns"]


def test_s3_policy_is_getobject_only_on_the_payment_qr_prefix() -> None:
    statements = _policy_documents()["lambda_public_orders_s3"]
    assert len(statements) == 1
    assert statements[0].get("effect") == "Allow"
    assert _as_list(statements[0].get("actions")) == ["s3:GetObject"]
    assert _as_list(statements[0].get("resources")) == ["${var.exports_bucket_arn}/payment-qr-codes/*"]


def test_no_write_action_appears_in_either_public_orders_policy() -> None:
    write_fragments = ("PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactionWrite")
    for name, statements in _policy_documents().items():
        for statement in statements:
            for action in statement.get("actions", []):
                assert not any(fragment in action for fragment in write_fragments), f"{name}: {action}"


def test_both_policies_attach_to_the_public_orders_role() -> None:
    doc = load_hcl(IAM_MAIN)
    attachments = {}
    for resource in doc.get("resource", []):
        for resource_type, instances in resource.items():
            if resource_type != "aws_iam_role_policy":
                continue
            for name, attributes in instances.items():
                role = attributes.get("role", "")
                text = role if isinstance(role, str) else "${" + str(role) + "}"
                attachments[name] = text
    expected = "${aws_iam_role.lambda_public_orders_execution.id}"
    assert attachments.get("lambda_public_orders_dynamodb") == expected
    assert attachments.get("lambda_public_orders_s3") == expected


# ---------------------------------------------------------------------------
# Behavioral half: the real handlers, recorded at the botocore layer
# ---------------------------------------------------------------------------


def _seed_offer_read(
    campaigns_table: Any,
    profiles_table: Any,
    catalogs_table: Any,
    accounts_table: Any,
) -> None:
    campaigns_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "campaignId": CAMPAIGN_ID,
            "campaignName": "Fall Sale",
            "isActive": True,
            "catalogId": CATALOG_ID,
            "publicOrders": {"enabled": True, "token": TOKEN, "allowedPaymentMethods": ["venmo", "cash"]},
        }
    )
    profiles_table.put_item(Item={"ownerAccountId": ACCOUNT_ID, "profileId": PROFILE_ID, "sellerName": "My Profile"})
    catalogs_table.put_item(
        Item={
            "catalogId": CATALOG_ID,
            "name": "Cat",
            "products": [{"productId": "p", "productName": "W", "price": 5, "sortOrder": 1}],
        }
    )
    accounts_table.put_item(
        Item={
            "accountId": ACCOUNT_ID,
            "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": f"https://host/{QR_S3_KEY}"}]},
        }
    )


def _seed_order(orders_table: Any) -> None:
    orders_table.put_item(
        Item={
            "campaignId": CAMPAIGN_ID,
            "orderId": ORDER_ID,
            "sellerName": "My Profile",
            "orderDate": "2026-01-01",
            "paymentMethod": "Venmo",
            "status": "NEW",
            "receiptToken": RECEIPT_TOKEN,
            "lineItems": [{"productId": "p", "productName": "W", "quantity": 1, "pricePerUnit": 5, "subtotal": 5}],
            "totalAmount": 5,
            "customerFirstName": "Buyer",
            "customerLastName": "One",
        }
    )


class TestOfferScope:
    def test_offer_read_issues_only_reads_within_the_role(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        _seed_offer_read(campaigns_table, profiles_table, catalogs_table, accounts_table)
        api_calls.attach()

        result = public_orders_handler(
            _event({"campaignId": "c1", "token": TOKEN}, "publicGetOrderOffer"), lambda_context
        )

        assert result["campaignId"] == "c1"
        assert result["sellerName"] == "My Profile"
        assert result["paymentMethods"][0]["name"] == "Venmo"
        assert result["paymentMethods"][0]["qrCodeUrl"].startswith("https://")
        assert_within_public_orders_role_scope(api_calls)


class TestReceiptScope:
    def test_receipt_read_is_a_single_orders_getitem(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        orders_table: Any,
        lambda_context: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        _seed_offer_read(campaigns_table, profiles_table, catalogs_table, accounts_table)
        _seed_order(orders_table)
        api_calls.attach()

        result = public_orders_handler(
            _event(
                {"campaignId": "c1", "orderSuffix": ORDER_SUFFIX, "receiptToken": RECEIPT_TOKEN},
                "publicGetOrderReceipt",
            ),
            lambda_context,
        )

        assert result["orderId"] == ORDER_ID
        assert result["sellerName"] == "My Profile"
        assert {tuple(call) for call in api_calls.dynamodb_calls} == {("GetItem", ORDERS_TABLE)}
        assert_within_public_orders_role_scope(api_calls)
