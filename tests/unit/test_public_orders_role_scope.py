"""Behavioral scope check for the #679 public-orders domain execution role.

The ``public-orders`` Lambda (``handlers/public_orders_offer.py``, wired through
``lambda_unit_resolver.js``) runs under its own scoped per-domain role added for
the public-orders offer slice, following the #351 pattern the other domain roles
reuse. That role grants:

- DynamoDB ``GetItem`` on exactly the four tables the offer reads — profiles,
  campaigns, catalogs, accounts — and ``Query`` on profiles plus its GSIs (the
  ``profileId-index`` locator);
- ``s3:GetObject`` on the ``payment-qr-codes/*`` prefix of the exports bucket.

The S3 grant is the subtle half. Pre-signing is local signing: the handler issues
zero S3 API calls, so a behavioral test can never observe the grant. It is
load-bearing anyway, because S3 authorizes a pre-signed GET against the SIGNING
role's policy at request time (#353) — without it every buyer's QR image fails
with 403. So the grant is asserted statically against the OpenTofu source here,
and the zero-call behavior is asserted separately.

Orders access is deliberately absent: the receipt read that needs orders is a
later slice, and unused permissions on a domain role are a liability. These
tests record every botocore call while invoking the real handler against moto,
then fail if the handler escapes the four tables, issues a write, or touches
orders or S3.
"""

from typing import Any, Dict, List, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.public_orders_offer import handler
from tests.unit.test_edge_security import TF_APP, block, first_resource, load_hcl, modules

IAM_TF = TF_APP / "modules" / "iam" / "main.tf"

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"

# The four tables the #679 role grants GetItem on.
DOMAIN_TABLES = {PROFILES_TABLE, CAMPAIGNS_TABLE, CATALOGS_TABLE, ACCOUNTS_TABLE}

# Tables the role grants Query on (plus its GSIs): the profileId-index
# locator. Never campaigns (the anchor campaign is resolved by canonical id),
# catalogs, or accounts.
QUERY_TABLES = {PROFILES_TABLE}

# Read-only domain: no write action of any kind is granted or exercised.
ALLOWED_DYNAMODB_ACTIONS = {"GetItem", "Query"}

OWNER_SUB = "owner-sub-001"
OWNER_ID = f"ACCOUNT#{OWNER_SUB}"
PROFILE_ID = "PROFILE#profile-123"
CAMPAIGN_ID = "CAMPAIGN#campaign-123"
CATALOG_ID = "CATALOG#catalog-123"
TOKEN = "6f1c1f0a-2f6e-4c1a-9b4f-7d2c0a5e8b11"
QR_KEY = f"payment-qr-codes/{OWNER_SUB}/9b1c2d3e4f5045a6b7c8d9e0f1a2b3c4.png"


class ApiCallRecorder:
    """Records DynamoDB and S3 API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style calls are
    captured with their real operation names. Seeding before ``attach()`` is not
    recorded, and pre-signed URL generation never reaches this layer.
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
                table = params.get("TableName")
                if isinstance(table, str):
                    dynamodb_calls.append((operation_name, table))
            elif service == "s3":
                s3_calls.append(operation_name)
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> ApiCallRecorder:
    """Provide an API call recorder; call ``attach()`` after seeding data."""
    return ApiCallRecorder(monkeypatch)


@pytest.fixture
def accounts_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table(ACCOUNTS_TABLE)


@pytest.fixture
def campaigns_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table(CAMPAIGNS_TABLE)


@pytest.fixture
def catalogs_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table(CATALOGS_TABLE)


def seed_offer(profiles_table: Any, campaigns_table: Any, catalogs_table: Any, accounts_table: Any) -> None:
    """Seed a complete enabled offer, including a QR-bearing payment method."""
    profiles_table.put_item(
        Item={
            "ownerAccountId": OWNER_ID,
            "profileId": PROFILE_ID,
            "sellerName": "Test Seller",
            "publicOrders": {
                "enabled": True,
                "token": TOKEN,
                "campaignId": CAMPAIGN_ID,
                "allowedPaymentMethods": ["Venmo"],
            },
        }
    )
    campaigns_table.put_item(
        Item={
            "profileId": PROFILE_ID,
            "campaignId": CAMPAIGN_ID,
            "campaignName": "Autumn fundraiser",
            "catalogId": CATALOG_ID,
            "isActive": True,
        }
    )
    catalogs_table.put_item(
        Item={
            "catalogId": CATALOG_ID,
            "catalogName": "Snacks",
            "catalogType": "USER_CREATED",
            "isPublic": False,
            "products": [{"productId": "PRODUCT#a", "productName": "First", "price": 1}],
        }
    )
    accounts_table.put_item(
        Item={
            "accountId": OWNER_ID,
            "email": "owner@example.com",
            "preferences": {"paymentMethods": [{"name": "Venmo", "qrCodeUrl": QR_KEY}]},
        }
    )


def offer_event() -> Dict[str, Any]:
    """The API-key-mode payload: ``identity`` is null and must never be read."""
    return {
        "arguments": {"profileId": "profile-123", "token": TOKEN},
        "identity": None,
        "info": {"fieldName": "publicGetOrderOffer"},
        "prev": {},
        "stash": {},
    }


def assert_within_public_orders_role_scope(recorder: ApiCallRecorder) -> None:
    """Assert recorded calls stay inside the public-orders role's grants."""
    operations = {operation for operation, _ in recorder.dynamodb_calls}
    tables = {table for _, table in recorder.dynamodb_calls}
    assert operations <= ALLOWED_DYNAMODB_ACTIONS, (
        f"unexpected DynamoDB actions: {operations - ALLOWED_DYNAMODB_ACTIONS}"
    )
    assert tables <= DOMAIN_TABLES, f"handler touched tables outside the public-orders scope: {tables - DOMAIN_TABLES}"
    query_tables = {table for operation, table in recorder.dynamodb_calls if operation == "Query"}
    assert query_tables <= QUERY_TABLES, f"Query outside profiles: {query_tables}"
    assert recorder.s3_calls == [], f"the offer handler must issue no S3 API call: {recorder.s3_calls}"


class TestOfferRoleScope:
    """The real handler against moto, with every AWS call recorded."""

    def test_offer_reads_only_the_four_domain_tables(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        api_calls.attach()

        result = handler(offer_event(), None)

        assert result["sellerName"] == "Test Seller"
        assert result["paymentMethods"][0]["qrCodeUrl"]
        # GSI locate, consistent profile read, campaign GetItem, catalog GetItem,
        # accounts GetItem.
        assert api_calls.dynamodb_calls == [
            ("Query", PROFILES_TABLE),
            ("GetItem", PROFILES_TABLE),
            ("GetItem", CAMPAIGNS_TABLE),
            ("GetItem", CATALOGS_TABLE),
            ("GetItem", ACCOUNTS_TABLE),
        ], api_calls.dynamodb_calls
        assert_within_public_orders_role_scope(api_calls)

    def test_orders_and_s3_are_never_touched(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        dynamodb_table: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        """The orders table exists in the test stack but is off-limits to this role."""
        orders_table = boto3.resource("dynamodb", region_name="us-east-1").Table("kernelworx-orders-v2-ue1-dev")
        orders_table.put_item(Item={"campaignId": CAMPAIGN_ID, "orderId": f"{CAMPAIGN_ID}#order-1", "totalAmount": 1})
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        api_calls.attach()

        handler(offer_event(), None)

        touched = {table for _, table in api_calls.dynamodb_calls}
        assert "kernelworx-orders-v2-ue1-dev" not in touched
        assert api_calls.s3_calls == []
        assert_within_public_orders_role_scope(api_calls)

    def test_negative_read_stays_within_scope(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        """A bad token stops after the profile reads: no campaign/catalog/accounts read."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        api_calls.attach()

        event = offer_event()
        event["arguments"]["token"] = "wrong-token"
        result = handler(event, None)

        assert result["errorCode"] == "NOT_FOUND"
        assert {table for _, table in api_calls.dynamodb_calls} == {PROFILES_TABLE}
        assert api_calls.s3_calls == []
        assert_within_public_orders_role_scope(api_calls)


# ---------------------------------------------------------------------------
# Static IAM policy contract (the behavioral test cannot see these grants)
# ---------------------------------------------------------------------------

IAM_DOC = load_hcl(IAM_TF)


def _policy_document(policy_label: str) -> List[Dict[str, Any]]:
    """Statements of the inline policy document attached to ``policy_label``."""
    body = first_resource(IAM_DOC, "aws_iam_role_policy", policy_label)
    # `policy = data.aws_iam_policy_document.<name>.json` — the hcl2 form keeps
    # the interpolation, so the referenced document name is the trailing part.
    reference = str(block(body["policy"])).strip().removeprefix("${").removesuffix("}")
    reference = reference.removesuffix(".json")
    document_name = reference.rsplit(".", 1)[-1]
    for entry in IAM_DOC.get("data", []):
        bodies = entry.get("aws_iam_policy_document", {})
        if document_name in bodies:
            return [block(statement) for statement in block(bodies[document_name]).get("statement", [])]
    raise AssertionError(f"data.aws_iam_policy_document.{document_name} not found")


def _actions(statements: List[Dict[str, Any]]) -> set[str]:
    return {str(action) for statement in statements for action in block(statement["actions"])}


def _resources(statements: List[Dict[str, Any]]) -> List[str]:
    """Resource entries of each statement (a single interpolation parses as a string)."""
    out: List[str] = []
    for statement in statements:
        value = block(statement["resources"])
        out.extend(str(item) for item in (value if isinstance(value, list) else [value]))
    return out


def test_public_orders_role_exists_with_a_scoped_name():
    role = first_resource(IAM_DOC, "aws_iam_role", "lambda_public_orders_execution")
    assert "lambda-public-orders-exec" in str(block(role["name"]))


def test_role_arn_is_exported_for_the_environment_wiring():
    assert any(
        label == "lambda_public_orders_execution_role_arn" for entry in IAM_DOC.get("output", []) for label in entry
    )


def test_dynamodb_grants_are_read_only():
    statements = _policy_document("lambda_public_orders_dynamodb")
    assert _actions(statements) == {"dynamodb:GetItem", "dynamodb:Query"}

def test_dynamodb_grants_cover_the_four_domain_tables_and_no_orders():
    """The GetItem/Query resource lists, resolved from the locals they reference."""
    merged: Dict[str, Any] = {}
    for entry in IAM_DOC.get("locals", []):
        merged.update(entry)
    assert [str(key) for key in merged["public_orders_table_keys"]] == [
        "profiles",
        "campaigns",
        "catalogs",
        "accounts",
    ]
    assert [str(key) for key in merged["public_orders_query_keys"]] == ["profiles"]
    # The statements reference exactly these two local lists, so the grant set
    # is the four tables above plus the profiles GSI — nothing else.
    assert sorted(_resources(_policy_document("lambda_public_orders_dynamodb"))) == [
        "${concat(local.public_orders_query_arns, local.public_orders_index_arns)}",
        "${local.public_orders_table_arns}",
    ], _resources(_policy_document("lambda_public_orders_dynamodb"))


def test_s3_get_object_on_the_qr_prefix_is_granted_for_the_signed_gets():
    """The grant a behavioral test cannot observe.

    Pre-signing makes no S3 call, but S3 authorizes the buyer's pre-signed GET
    against the signing role at request time (#353), so the role must hold
    s3:GetObject on the QR prefix or every buyer's QR image 403s.
    """
    statements = _policy_document("lambda_public_orders_s3")
    assert _actions(statements) == {"s3:GetObject"}
    granted = _resources(statements)
    assert granted and all("payment-qr-codes/*" in resource for resource in granted), granted


def test_public_orders_is_mapped_to_the_role_in_all_three_environments():
    for env in ("dev", "prod", "ephemeral"):
        env_doc = load_hcl(TF_APP / "environments" / env / "main.tf")
        (lambda_block,) = modules(env_doc, "lambda")
        domain_map = block(lambda_block["lambda_domain_role_arns"])
        assert domain_map["public-orders"] == "${module.iam.lambda_public_orders_execution_role_arn}", env
