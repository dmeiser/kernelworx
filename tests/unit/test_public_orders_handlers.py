"""Unit tests for the public order offer read (#679 public-orders offer slice).

``publicGetOrderOffer`` is the anonymous read behind the share URL: given a bare
profile id and the URL token it answers who the seller is, which campaign is
anchored, which catalog products a buyer can pick, and which payment methods the
seller allowlisted — each with a short-lived pre-signed QR image when the method
has one. There is no caller identity on this path.

These tests pin the four properties that make the read safe and useful:

- the read order (GSI locator -> strongly consistent profile read -> token ->
  anchor campaign -> catalog -> account preferences), including the transient
  multi-projection window after a profile transfer, which resolves to NOT_FOUND
  rather than a guess;
- every negative branch answering the *identical* NOT_FOUND, so probing cannot
  distinguish "never enabled" from "bad token";
- an empty product or method list being a successful offer, not an error;
- the pre-sign trap: the stored key is passed EXPLICITLY, so the handler issues
  zero S3 API calls (the helper's no-key path would probe deterministic
  slug-shaped keys that can never match the stored UUID keys, costing up to
  three ``head_object`` calls), and neither the token nor the S3 key ever
  reaches a log line.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
import botocore.client
import pytest

from src.handlers.public_orders_offer import handler
from src.utils.dynamodb import override_table

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-v2-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"

OWNER_SUB = "owner-sub-001"
OWNER_ID = f"ACCOUNT#{OWNER_SUB}"
PROFILE_ID = "PROFILE#profile-123"
BARE_PROFILE_ID = "profile-123"
CAMPAIGN_ID = "CAMPAIGN#campaign-123"
CATALOG_ID = "CATALOG#catalog-123"
TOKEN = "6f1c1f0a-2f6e-4c1a-9b4f-7d2c0a5e8b11"

VENMO_KEY = f"payment-qr-codes/{OWNER_SUB}/9b1c2d3e4f5045a6b7c8d9e0f1a2b3c4.png"
PAYPAL_KEY = f"payment-qr-codes/{OWNER_SUB}/0a1b2c3d4e5f60718293a4b5c6d7e8f9.png"

NOT_FOUND_PAYLOAD = {"__isError": True, "errorCode": "NOT_FOUND", "message": "Offer not available"}


class ApiCallRecorder:
    """Records DynamoDB and S3 API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style calls are
    captured with their real operation names. Seeding done before ``attach()``
    is not recorded. Pre-signed URL generation never reaches this layer — it is
    pure client-side signing — so an offer that pre-signs correctly records zero
    S3 calls, which is what pins the explicit-key contract.
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
            elif service == "s3" and isinstance(params, dict):
                s3_calls.append((operation_name, str(params.get("Key") or params.get("Bucket") or "")))
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


class QueryStubTable:
    """Wraps a real table but answers ``query`` with canned GSI projections.

    moto keeps a GSI in step with the base table, so the transient
    post-transfer projection window cannot be produced by writing rows; the
    locator read is stubbed instead while the strongly consistent
    confirmation still runs against the real table.
    """

    def __init__(self, real_table: Any, projections: List[Dict[str, Any]]) -> None:
        self._real = real_table
        self._projections = projections

    def query(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"Items": self._projections}

    def get_item(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._real.get_item(*args, **kwargs)


def seed_profile(
    profiles_table: Any,
    *,
    owner_account_id: str = OWNER_ID,
    profile_id: str = PROFILE_ID,
    enabled: bool = True,
    token: Optional[str] = TOKEN,
    campaign_id: Optional[str] = CAMPAIGN_ID,
    allowed: Optional[List[str]] = None,
    seller_name: str = "Test Seller",
) -> None:
    """Seed a profile with its ``publicOrders`` blob."""
    blob: Dict[str, Any] = {"enabled": enabled}
    if token is not None:
        blob["token"] = token
    if campaign_id is not None:
        blob["campaignId"] = campaign_id
    blob["allowedPaymentMethods"] = ["venmo", "Cash"] if allowed is None else allowed
    profiles_table.put_item(
        Item={
            "ownerAccountId": owner_account_id,
            "profileId": profile_id,
            "sellerName": seller_name,
            "publicOrders": blob,
        }
    )


def seed_campaign(campaigns_table: Any, *, is_active: Any = True, catalog_id: Optional[str] = CATALOG_ID) -> None:
    """Seed the anchor campaign. ``is_active=None`` omits the attribute (legacy rows)."""
    item: Dict[str, Any] = {
        "profileId": PROFILE_ID,
        "campaignId": CAMPAIGN_ID,
        "campaignName": "Autumn fundraiser",
        "createdAt": "2026-01-01T00:00:00Z",
    }
    if is_active is not None:
        item["isActive"] = is_active
    if catalog_id is not None:
        item["catalogId"] = catalog_id
    campaigns_table.put_item(Item=item)


def seed_catalog(
    catalogs_table: Any,
    *,
    products: Optional[List[Dict[str, Any]]] = None,
    is_deleted: Optional[bool] = None,
) -> None:
    """Seed the anchor catalog. Products are stored inline; there is no per-product tombstone."""
    stored_products = [{"productId": "PRODUCT#c", "productName": "Third", "price": Decimal("3.0")}, *default_products()]
    item: Dict[str, Any] = {
        "catalogId": CATALOG_ID,
        "catalogName": "Snacks",
        "catalogType": "USER_CREATED",
        "isPublic": False,
        "products": stored_products if products is None else products,
    }
    if is_deleted is not None:
        item["isDeleted"] = is_deleted
    catalogs_table.put_item(Item=item)


def default_products() -> List[Dict[str, Any]]:
    """Catalog products deliberately stored out of ``sortOrder`` order."""
    return [
        {"productId": "PRODUCT#b", "productName": "Second", "price": Decimal("2.5"), "sortOrder": 10},
        {
            "productId": "PRODUCT#a",
            "productName": "First",
            "price": Decimal("1.0"),
            "sortOrder": 1,
            "description": "cheap",
        },
    ]


def seed_account(accounts_table: Any, methods: Optional[List[Dict[str, Any]]] = None) -> None:
    """Seed the owner account's ``preferences.paymentMethods``."""
    stored = (
        [{"name": "VENMO", "qrCodeUrl": VENMO_KEY}, {"name": "PayPal", "qrCodeUrl": PAYPAL_KEY}]
        if methods is None
        else methods
    )
    accounts_table.put_item(
        Item={"accountId": OWNER_ID, "email": "owner@example.com", "preferences": {"paymentMethods": stored}}
    )


def seed_offer(
    profiles_table: Any,
    campaigns_table: Any,
    catalogs_table: Any,
    accounts_table: Any,
    **profile_kwargs: Any,
) -> None:
    """Seed a complete, enabled offer."""
    seed_profile(profiles_table, **profile_kwargs)
    seed_campaign(campaigns_table)
    seed_catalog(catalogs_table)
    seed_account(accounts_table)


def offer_event(profile_id: Any = BARE_PROFILE_ID, token: Any = TOKEN) -> Dict[str, Any]:
    """The payload ``lambda_unit_resolver.js`` forwards: the whole AppSync context.

    ``identity`` is null on the API-key auth mode, so a handler that read a
    caller would fail here — that is deliberate.
    """
    return {
        "arguments": {"profileId": profile_id, "token": token},
        "identity": None,
        "info": {"fieldName": "publicGetOrderOffer", "selectionSetList": ["sellerName", "campaignId"]},
        "prev": {},
        "stash": {},
    }


def call(event: Dict[str, Any]) -> Any:
    return handler(event, None)


class TestOfferPositive:
    """The shape a buyer sees, and the reads that produce it."""

    def test_offer_shape_and_catalog_ordering(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        result = call(offer_event())

        assert result["sellerName"] == "Test Seller"
        # Bare ids at the API boundary, matching the URL contract.
        assert result["campaignId"] == "campaign-123"
        assert result["campaignName"] == "Autumn fundraiser"
        # The offer follows catalog order, not storage order.
        assert [p["productId"] for p in result["products"]] == ["PRODUCT#a", "PRODUCT#b", "PRODUCT#c"]
        assert result["products"][0]["price"] == 1.0
        assert result["products"][0]["description"] == "cheap"
        assert result["products"][1]["sortOrder"] == 10

    def test_method_intersection_is_case_insensitive_and_not_force_added(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        # The blob allowlists "venmo" (stored as "VENMO": matched
        # case-insensitively, served with the account's own spelling) and "Cash"
        # (a global pseudo-method, never stored in preferences). PayPal is stored
        # but not allowlisted, so it must not appear.
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["VENMO", "Cash"]
        assert result["paymentMethods"][0]["qrCodeUrl"]
        assert result["paymentMethods"][1]["qrCodeUrl"] is None

    def test_cash_and_check_are_not_force_added(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        # Cash is always "existing", but it reaches the buyer only because the
        # seller allowlisted it; an allowlist without it lists nothing else.
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["VENMO"]

    def test_allowlisted_global_method_without_a_stored_entry(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["check"])
        seed_account(accounts_table, methods=[{"name": "VENMO", "qrCodeUrl": VENMO_KEY}])

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["check"]
        assert result["paymentMethods"][0]["qrCodeUrl"] is None

    def test_signed_url_is_built_from_the_stored_key_with_zero_s3_calls(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        api_calls.attach()

        result = call(offer_event())

        url = result["paymentMethods"][0]["qrCodeUrl"]
        # The stored UUID key is what got signed — not a slug-shaped probe key.
        assert VENMO_KEY.replace("/", "%2F") in url or VENMO_KEY in url
        assert "Signature=" in url
        assert "Expires=" in url
        assert "venmo.png" not in url
        # The trap: the helper's no-key path would HEAD up to three deterministic
        # slug keys. Pre-signing is local, so a correct call makes no S3 call.
        assert api_calls.s3_calls == []
        s3_operations = {operation for operation, _ in api_calls.s3_calls}
        assert "HeadObject" not in s3_operations
        assert "ListObjectsV2" not in s3_operations

    def test_legacy_full_url_value_extracts_to_the_key(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        legacy = f"https://kernelworx-exports-ue1-dev.s3.amazonaws.com/{VENMO_KEY}"
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_account(accounts_table, methods=[{"name": "Venmo", "qrCodeUrl": legacy}])

        result = call(offer_event())

        url = result["paymentMethods"][0]["qrCodeUrl"]
        assert url is not None
        assert VENMO_KEY.replace("/", "%2F") in url or VENMO_KEY in url

    def test_empty_product_list_is_a_successful_offer(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_catalog(catalogs_table, products=[])

        result = call(offer_event())

        assert result["products"] == []
        assert result["paymentMethods"]

    def test_empty_method_list_is_a_successful_offer(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        # Every allowlisted non-global method was deleted from the account since
        # enable time, so the buyer gets a working page with no methods.
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])
        seed_account(accounts_table, methods=[])

        result = call(offer_event())

        assert result["paymentMethods"] == []
        assert result["sellerName"] == "Test Seller"

    def test_legacy_campaign_without_is_active_is_active(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_campaign(campaigns_table, is_active=None)

        result = call(offer_event())

        assert result["campaignId"] == "campaign-123"

    def test_prefixed_profile_id_is_accepted(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        result = call(offer_event(profile_id=PROFILE_ID))

        assert result["campaignId"] == "campaign-123"

    def test_stale_gsi_projection_resolves_to_the_surviving_owner(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        """Two projections, one consistent hit: the transfer finished, so serve it.

        The multi-projection window is transient; once only one candidate still
        exists in the base table, that row is the current owner and the offer
        proceeds — the ambiguity guard is for the window where both still exist.
        """
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        real = {"ownerAccountId": OWNER_ID, "profileId": PROFILE_ID}
        stale = {"ownerAccountId": "ACCOUNT#departed-owner", "profileId": PROFILE_ID}
        override_table("profiles", QueryStubTable(profiles_table, [real, stale]))

        result = call(offer_event())

        assert result["sellerName"] == "Test Seller"

    def test_projection_without_an_owner_yields_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        """A projection with no partition key cannot be confirmed consistently."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        override_table("profiles", QueryStubTable(profiles_table, [{"profileId": PROFILE_ID}]))

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_duplicated_allowlist_entries_yield_one_method(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo", "VENMO"])

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["VENMO"]

    def test_products_without_ids_or_prices_are_dropped(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_catalog(
            catalogs_table,
            products=[
                {"productName": "No id", "price": Decimal("1.0")},
                {"productId": "PRODUCT#x", "productName": "Bad price", "price": "not-a-number"},
                {"productId": "PRODUCT#ok", "productName": "Kept", "price": Decimal("2.0"), "sortOrder": "bad"},
            ],
        )

        result = call(offer_event())

        assert [p["productId"] for p in result["products"]] == ["PRODUCT#ok"]
        assert result["products"][0]["sortOrder"] is None

    def test_truncated_legacy_qr_url_yields_null_without_probing(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        api_calls: ApiCallRecorder,
    ) -> None:
        """A URL with no path has no key; signing nothing must not fall back to probing."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])
        seed_account(accounts_table, methods=[{"name": "VENMO", "qrCodeUrl": "https://bucket.example.com/"}])
        api_calls.attach()

        result = call(offer_event())

        assert result["paymentMethods"][0]["qrCodeUrl"] is None
        assert api_calls.s3_calls == []

    def test_malformed_stored_method_entries_are_ignored(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        """A preferences row holding junk cannot break the offer's method list."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo", "paypal"])
        seed_account(
            accounts_table,
            methods=["orphan-string", {"qrCodeUrl": VENMO_KEY}, {"name": "VENMO", "qrCodeUrl": VENMO_KEY}],
        )

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["VENMO"]

    def test_account_without_preferences_yields_no_methods(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        """An accounts row with no preferences blob is an empty list, not an error."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])
        accounts_table.update_item(
            Key={"accountId": OWNER_ID},
            UpdateExpression="REMOVE preferences",
        )

        result = call(offer_event())

        assert result["paymentMethods"] == []
        assert result["sellerName"] == "Test Seller"

    def test_signing_internal_error_propagates(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only the helper's FORBIDDEN degrades to null; a real failure is an error."""
        from src.utils.errors import AppError, ErrorCode

        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise AppError(ErrorCode.INTERNAL_ERROR, "signing failed")

        monkeypatch.setattr("src.handlers.public_orders_offer.generate_presigned_get_url", explode)

        result = call(offer_event())

        assert result["__isError"] is True
        assert result["errorCode"] == "INTERNAL_ERROR"


class TestOfferNegative:
    """Every negative branch answers the identical NOT_FOUND."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"token": "wrong-token"}, id="bad-token"),
            pytest.param({"token": None}, id="missing-token"),
            pytest.param({"token": ""}, id="empty-token"),
            pytest.param({"profile_id": "nope"}, id="unknown-profile"),
        ],
    )
    def test_offer_read_returns_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        kwargs: Dict[str, Any],
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        assert call(offer_event(**kwargs)) == NOT_FOUND_PAYLOAD

    def test_disabled_feature_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, enabled=False)

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_absent_settings_blob_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, token=None, campaign_id=None)
        profiles_table.update_item(
            Key={"ownerAccountId": OWNER_ID, "profileId": PROFILE_ID},
            UpdateExpression="REMOVE publicOrders",
        )

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_inactive_anchor_campaign_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_campaign(campaigns_table, is_active=False)

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_missing_anchor_campaign_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        campaigns_table.delete_item(Key={"profileId": PROFILE_ID, "campaignId": CAMPAIGN_ID})

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_soft_deleted_catalog_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_catalog(catalogs_table, is_deleted=True)

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_missing_catalog_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        catalogs_table.delete_item(Key={"catalogId": CATALOG_ID})

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_blob_without_an_anchor_campaign_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, campaign_id=None)

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_campaign_without_a_catalog_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        seed_campaign(campaigns_table, catalog_id=None)

        assert call(offer_event()) == NOT_FOUND_PAYLOAD

    def test_missing_profile_id_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        assert call(offer_event(profile_id=None)) == NOT_FOUND_PAYLOAD

    def test_ambiguous_gsi_projection_is_the_same_not_found(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A transfer window that projects two live owners is never a best guess."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)
        # Both rows still resolve consistently: the GSI is transiently stale and
        # the base table has not caught up either (the documented window).
        profiles_table.put_item(
            Item={
                "ownerAccountId": "ACCOUNT#new-owner",
                "profileId": PROFILE_ID,
                "sellerName": "New Seller",
                "publicOrders": {
                    "enabled": True,
                    "token": TOKEN,
                    "campaignId": CAMPAIGN_ID,
                    "allowedPaymentMethods": ["venmo"],
                },
            }
        )

        with caplog.at_level(logging.INFO):
            assert call(offer_event()) == NOT_FOUND_PAYLOAD
        assert TOKEN not in caplog.text

    def test_unsupported_field_is_an_internal_error(self, profiles_table: Any) -> None:
        event = offer_event()
        event["info"]["fieldName"] = "publicGetOrderReceipt"

        result = call(event)

        assert result["__isError"] is True
        assert result["errorCode"] == "INTERNAL_ERROR"


class TestQrCodeFailures:
    """A QR problem degrades one method's URL, never the whole offer."""

    def test_allowlisted_method_whose_qr_was_deleted_yields_null(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
    ) -> None:
        # delete_qr_code clears the stored key; the method itself stays.
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])
        seed_account(accounts_table, methods=[{"name": "VENMO", "qrCodeUrl": None}])

        result = call(offer_event())

        assert [m["name"] for m in result["paymentMethods"]] == ["VENMO"]
        assert result["paymentMethods"][0]["qrCodeUrl"] is None

    @pytest.mark.parametrize(
        "stored",
        [
            pytest.param(f"payment-qr-codes/someone-else/{VENMO_KEY.split('/')[-1]}", id="foreign-account-key"),
            pytest.param("not-an-s3-key", id="malformed-key"),
        ],
    )
    def test_foreign_or_malformed_key_yields_null_without_echoing_the_key(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        stored: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table, allowed=["venmo"])
        seed_account(accounts_table, methods=[{"name": "VENMO", "qrCodeUrl": stored}])

        with caplog.at_level(logging.INFO):
            result = call(offer_event())

        assert result["paymentMethods"][0]["qrCodeUrl"] is None
        assert "Skipping QR key that failed ownership validation" in caplog.text
        assert stored not in caplog.text

    def test_signing_helper_success_line_never_surfaces(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """generate_presigned_get_url logs s3_key on success; the offer suppresses it."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        with caplog.at_level(logging.INFO):
            result = call(offer_event())

        assert result["paymentMethods"][0]["qrCodeUrl"]
        assert VENMO_KEY not in caplog.text
        assert PAYPAL_KEY not in caplog.text


class TestLoggingHygiene:
    """The token, the S3 key, and buyer contact never reach a log line."""

    def test_no_log_record_carries_the_token_or_the_key(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        with caplog.at_level(logging.INFO):
            call(offer_event())
            call(offer_event(token="wrong-token"))

        assert TOKEN not in caplog.text
        assert VENMO_KEY not in caplog.text
        assert "owner@example.com" not in caplog.text

    def test_generic_unexpected_exception_does_not_leak_the_token(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The decorator's ``error=str(e)`` line is the real leak surface.

        A library that echoes a request argument (a validation or service error
        carrying the request) would put the capability token in the log, so the
        handler scrubs the known secret from any unexpected exception before it
        reaches the decorator.
        """
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"validation failed for value {TOKEN}")

        monkeypatch.setattr("src.handlers.public_orders_offer._load_campaign", explode)

        with caplog.at_level(logging.INFO):
            result = call(offer_event())

        assert result["errorCode"] == "INTERNAL_ERROR"
        assert TOKEN not in caplog.text
        assert "validation failed" in caplog.text

    def test_generic_exception_without_the_token_is_left_alone(
        self,
        profiles_table: Any,
        campaigns_table: Any,
        catalogs_table: Any,
        accounts_table: Any,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The scrub only rewrites a message that actually carries the secret."""
        seed_offer(profiles_table, campaigns_table, catalogs_table, accounts_table)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("dynamodb throttled")

        monkeypatch.setattr("src.handlers.public_orders_offer._load_campaign", explode)

        with caplog.at_level(logging.INFO):
            result = call(offer_event())

        assert result["errorCode"] == "INTERNAL_ERROR"
        assert "dynamodb throttled" in caplog.text
