"""Unit tests for the campaign-keyed public offer read handler.

Covers ``src/handlers/public_orders_offer.py`` line- and branch-wise
(``--cov-fail-under=100``). The offer is the anonymous read behind
``/o/<campaignId>/<token>``: no caller identity, the share token IS the
authorization, and every negative branch (unknown campaign, missing or inactive
catalog, disabled token, a bad token) raises the identical NOT_FOUND.

Private helpers are exercised directly so the coercion, sorting, projection, and
QR branches are covered without a datastore round trip; the decorated ``handler``
is exercised end-to-end to cover the field dispatch and the ``__isError``
payloads.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import patch

import boto3
import pytest

from src.handlers import public_orders_offer as offer
from src.handlers.public_orders_offer import (
    OFFER_UNAVAILABLE_MESSAGE,
    _as_int,
    _build_offer,
    _campaign_is_active,
    _extract_s3_key,
    _load_catalog,
    _public_payment_methods,
    _public_product,
    _public_products,
    _run_guarded,
    _settings_blob,
    _signed_qr_url,
    _sort_key,
    _stored_methods,
    _token_matches,
    handler,
)
from src.utils.appsync_types import as_float
from src.utils.errors import AppError, ErrorCode
from src.utils.logging import redact_secrets

CAMPAIGN_ID = "CAMPAIGN#c1"
PROFILE_ID = "PROFILE#p1"
CATALOG_ID = "CATALOG#k1"
ACCOUNT_ID = "ACCOUNT#sub1"


def _recent_order_date(days_ago: int) -> str:
    """Return an ISO 8601 date string for ``days_ago`` days in the past."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@pytest.fixture
def accounts_table(dynamodb_table: Any) -> Any:
    """Accounts table handle within the moto context (no dedicated conftest fixture)."""
    return boto3.resource("dynamodb", region_name="us-east-1").Table("kernelworx-accounts-ue1-dev")


def _settings(**overrides: Any) -> Dict[str, Any]:
    blob: Dict[str, Any] = {
        "enabled": True,
        "token": "tok",
        "allowedPaymentMethods": ["venmo", "cash"],
    }
    blob.update(overrides)
    return blob


def _campaign_item(settings: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "profileId": PROFILE_ID,
        "campaignId": CAMPAIGN_ID,
        "campaignName": "Fall Sale",
        "isActive": True,
        "catalogId": CATALOG_ID,
        "publicOrders": settings,
    }
    item.update(overrides)
    return item


def _profile_item(**overrides: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {"ownerAccountId": ACCOUNT_ID, "profileId": PROFILE_ID, "sellerName": "My Profile"}
    item.update(overrides)
    return item


def _event(arguments: Dict[str, Any], field: str = "publicGetOrderOffer") -> Dict[str, Any]:
    return {"arguments": arguments, "info": {"fieldName": field}, "identity": None}


class TestLoadCampaign:
    def test_success(self, campaigns_table: Any) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        campaign = offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))
        assert campaign["profileId"] == PROFILE_ID

    def test_missing_campaign(self, campaigns_table: Any) -> None:
        with pytest.raises(AppError) as exc:
            offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))
        assert exc.value.error_code is ErrorCode.NOT_FOUND

    def test_ambiguous_projection(self, campaigns_table: Any) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        campaigns_table.put_item(Item={"profileId": "PROFILE#p2", "campaignId": CAMPAIGN_ID})
        with pytest.raises(AppError):
            offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))

    def test_zero_projection_logs_info_not_warning(
        self, campaigns_table: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A stale share link or an anonymous token probe is the normal zero-hit
        # case: it must not raise the log level.
        with caplog.at_level(logging.INFO):
            with pytest.raises(AppError):
                offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))
        hits = [record for record in caplog.records if "campaignId-index" in record.message]
        assert len(hits) == 1
        assert hits[0].levelno == logging.INFO

    def test_ambiguous_projection_logs_warning(self, campaigns_table: Any, caplog: pytest.LogCaptureFixture) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        campaigns_table.put_item(Item={"profileId": "PROFILE#p2", "campaignId": CAMPAIGN_ID})
        with caplog.at_level(logging.INFO):
            with pytest.raises(AppError):
                offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))
        hits = [record for record in caplog.records if "campaignId-index" in record.message]
        assert len(hits) == 1
        assert hits[0].levelno == logging.WARNING

    def test_campaign_projection_missing_profile_id(self) -> None:
        # The GSI can project a row whose profileId is missing/empty (a corrupt
        # projection); the base table cannot store such a row, so stub the query.
        with patch.object(offer.tables.campaigns, "query", return_value={"Items": [{"campaignId": CAMPAIGN_ID}]}):
            with pytest.raises(AppError):
                offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))

    def test_campaign_base_row_missing(self, campaigns_table: Any) -> None:
        # The GSI projects the campaign but the consistent base read misses (a
        # transfer race) — unreachable through moto (GSI and base are one item),
        # so the get_item is stubbed to model the missing row.
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        with patch.object(offer.tables.campaigns, "get_item", return_value={}):
            with pytest.raises(AppError):
                offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))

    def test_inactive_campaign_is_unavailable(self, campaigns_table: Any) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings(), isActive=False))
        with pytest.raises(AppError):
            offer._load_campaign(CAMPAIGN_ID, offer.get_logger(__name__))


class TestProfileHelpers:
    def test_consistent_profile_owner_none(self) -> None:
        assert offer._consistent_profile(None, PROFILE_ID) is None

    def test_consistent_profile_found(self, profiles_table: Any) -> None:
        profiles_table.put_item(Item=_profile_item())
        assert offer._consistent_profile(ACCOUNT_ID, PROFILE_ID) == _profile_item()

    def test_consistent_profile_missing(self, profiles_table: Any) -> None:
        assert offer._consistent_profile(ACCOUNT_ID, PROFILE_ID) is None

    def test_resolve_ambiguous_no_owners(self, profiles_table: Any) -> None:
        assert (
            offer._resolve_ambiguous_projection([{"profileId": PROFILE_ID}], PROFILE_ID, offer.get_logger(__name__))
            is None
        )

    def test_resolve_ambiguous_single(self, profiles_table: Any) -> None:
        profiles_table.put_item(Item=_profile_item())
        result = offer._resolve_ambiguous_projection(
            [{"ownerAccountId": ACCOUNT_ID}], PROFILE_ID, offer.get_logger(__name__)
        )
        assert result == _profile_item()

    def test_resolve_ambiguous_multiple(self, profiles_table: Any) -> None:
        profiles_table.put_item(Item=_profile_item())
        profiles_table.put_item(Item=_profile_item(ownerAccountId="ACCOUNT#other"))
        result = offer._resolve_ambiguous_projection(
            [{"ownerAccountId": ACCOUNT_ID}, {"ownerAccountId": "ACCOUNT#other"}],
            PROFILE_ID,
            offer.get_logger(__name__),
        )
        assert result is None

    def test_load_profile_success(self, profiles_table: Any) -> None:
        profiles_table.put_item(Item=_profile_item())
        profile = offer._load_profile(PROFILE_ID, offer.get_logger(__name__))
        assert profile["sellerName"] == "My Profile"

    def test_load_profile_missing(self, profiles_table: Any) -> None:
        with pytest.raises(AppError):
            offer._load_profile(PROFILE_ID, offer.get_logger(__name__))

    def test_load_profile_ambiguous(self, profiles_table: Any) -> None:
        # A transfer leaves both the old and the new owner's row projected under
        # the same profileId; two consistent reads survive, so it is ambiguous.
        profiles_table.put_item(Item=_profile_item())
        profiles_table.put_item(Item=_profile_item(ownerAccountId="ACCOUNT#other"))
        with pytest.raises(AppError):
            offer._load_profile(PROFILE_ID, offer.get_logger(__name__))


class TestSettingsHelpers:
    def test_settings_blob(self) -> None:
        assert _settings_blob({"publicOrders": {"a": 1}}) == {"a": 1}
        assert _settings_blob({}) == {}
        assert _settings_blob({"publicOrders": "garbage"}) == {}

    def test_token_matches(self) -> None:
        assert _token_matches(_settings(), "tok")
        assert not _token_matches(_settings(), "wrong")
        assert not _token_matches(_settings(enabled=False), "tok")
        assert not _token_matches(_settings(token=""), "tok")
        assert not _token_matches(_settings(), "")
        assert not _token_matches(_settings(), None)

    def test_campaign_is_active(self) -> None:
        assert _campaign_is_active({}) is True  # pre-``isActive`` row reads active
        assert _campaign_is_active({"isActive": True}) is True
        assert _campaign_is_active({"isActive": False}) is False


class TestLoadCatalog:
    def test_success(self, catalogs_table: Any) -> None:
        catalogs_table.put_item(Item={"catalogId": CATALOG_ID, "name": "Cat"})
        assert _load_catalog({"catalogId": CATALOG_ID}) == {"catalogId": CATALOG_ID, "name": "Cat"}

    def test_missing_catalog_id(self) -> None:
        with pytest.raises(AppError):
            _load_catalog({})

    def test_missing_catalog_row(self, catalogs_table: Any) -> None:
        with pytest.raises(AppError):
            _load_catalog({"catalogId": CATALOG_ID})

    def test_deleted_catalog(self, catalogs_table: Any) -> None:
        catalogs_table.put_item(Item={"catalogId": CATALOG_ID, "isDeleted": True})
        with pytest.raises(AppError):
            _load_catalog({"catalogId": CATALOG_ID})


class TestCoercionHelpers:
    def test_as_float(self) -> None:
        assert as_float(2) == 2.0
        assert as_float("3.5") == 3.5
        assert as_float(None) is None
        assert as_float("nope") is None
        assert as_float([1]) is None

    def test_as_float_rejects_non_finite_values(self) -> None:
        """NaN and the infinities are numbers to ``float()`` but not money.

        A stored ``Decimal("NaN")`` price would survive every downstream check
        and reach the buyer's offer as garbage, so it is rejected like any other
        malformed stored value.
        """
        for value in (
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "inf",
            "Infinity",
        ):
            assert as_float(value) is None, value
        assert _as_int(Decimal("NaN")) is None
        assert _sort_key({"sortOrder": Decimal("NaN")}) == (1, 0.0)

    def test_public_product_drops_a_non_finite_price(self) -> None:
        assert _public_product({"productId": "p", "productName": "N", "price": Decimal("NaN")}) is None
        assert _public_product({"productId": "p", "productName": "N", "price": Decimal("Infinity")}) is None

    def test_as_int(self) -> None:
        assert _as_int(None) is None
        assert _as_int(7) == 7
        assert _as_int(2.9) == 2
        assert _as_int("bad") is None

    def test_sort_key(self) -> None:
        assert _sort_key({"sortOrder": 2}) == (0, 2.0)
        assert _sort_key({}) == (1, 0.0)
        assert _sort_key({"sortOrder": 1}) < _sort_key({"sortOrder": 2})
        assert _sort_key({}) > _sort_key({"sortOrder": 5})

    def test_public_product(self) -> None:
        good = _public_product({"productId": "p", "productName": "N", "price": 4, "sortOrder": 1, "description": "d"})
        assert good == {"productId": "p", "productName": "N", "price": 4.0, "description": "d", "sortOrder": 1}
        assert _public_product({"productName": "N", "price": 1}) is None  # no product id
        assert _public_product({"productId": "p", "price": 1}) is None  # no name
        assert _public_product({"productId": "p", "productName": "N", "price": "nope"}) is None
        assert _public_product(
            {"productId": "p", "productName": "N", "price": 1, "description": 7, "sortOrder": None}
        ) == {
            "productId": "p",
            "productName": "N",
            "price": 1.0,
            "description": None,
            "sortOrder": None,
        }

    def test_public_products_none_and_sort(self) -> None:
        assert _public_products({}) == []
        catalog = {
            "products": [
                "junk",
                {"productId": "b", "productName": "B", "price": 1, "sortOrder": 2},
                {"productId": "a", "productName": "A", "price": 1, "sortOrder": 1},
                {"productId": "c", "productName": "C", "price": 1},
            ]
        }
        assert [p["productId"] for p in _public_products(catalog)] == ["a", "b", "c"]


class TestPaymentMethods:
    def test_stored_methods(self, accounts_table: Any) -> None:
        accounts_table.put_item(
            Item={
                "accountId": ACCOUNT_ID,
                "preferences": {"paymentMethods": [{"name": "Venmo"}, {"name": "cash"}, {"name": 7}]},
            }
        )
        stored = _stored_methods(ACCOUNT_ID)
        assert "venmo" in stored and "cash" in stored and 7 not in stored

    def test_stored_methods_accepts_either_account_id_spelling(self, accounts_table: Any) -> None:
        """The accounts partition key is always ``ACCOUNT#<id>``.

        A profile row's ``ownerAccountId`` can carry the bare legacy spelling; a
        verbatim read for it returns nothing and silently empties the offer's
        payment methods, so both spellings must resolve to the same row.
        """
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})
        assert "venmo" in _stored_methods("sub1")
        assert "venmo" in _stored_methods(ACCOUNT_ID)

    def test_public_payment_methods_resolves_a_bare_owner_account_id(self, accounts_table: Any) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})
        blob = {"allowedPaymentMethods": ["venmo"]}
        result = _public_payment_methods({"ownerAccountId": "sub1"}, blob, offer.get_logger(__name__))
        assert [method["name"] for method in result] == ["Venmo"]

    def test_stored_methods_without_a_usable_owner_id(self, accounts_table: Any) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})
        assert _stored_methods(None) == {}
        assert _stored_methods("") == {}
        assert _stored_methods(7) == {}

    def test_stored_methods_no_account(self, accounts_table: Any) -> None:
        assert _stored_methods(ACCOUNT_ID) == {}

    def test_stored_methods_no_preferences(self, accounts_table: Any) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": "garbage"})
        assert _stored_methods(ACCOUNT_ID) == {}

    def test_stored_methods_no_methods_key(self, accounts_table: Any) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {}})
        assert _stored_methods(ACCOUNT_ID) == {}

    def test_extract_s3_key(self) -> None:
        # The key is the path after the host (the S3 object key itself).
        assert _extract_s3_key("https://host.example/a/b.png") == "a/b.png"
        assert _extract_s3_key("https://host.example/") == ""
        assert _extract_s3_key("https://host.example") == "https://host.example"
        assert _extract_s3_key("not-a-url") == "not-a-url"

    def test_signed_qr_url_no_stored(self) -> None:
        assert _signed_qr_url(ACCOUNT_ID, {}, offer.get_logger(__name__)) is None
        assert _signed_qr_url(ACCOUNT_ID, {"qrCodeUrl": ""}, offer.get_logger(__name__)) is None
        assert _signed_qr_url(ACCOUNT_ID, {"qrCodeUrl": 7}, offer.get_logger(__name__)) is None

    def test_signed_qr_url_empty_key(self) -> None:
        assert _signed_qr_url(ACCOUNT_ID, {"qrCodeUrl": "https://host/"}, offer.get_logger(__name__)) is None

    def test_signed_qr_url_success(self) -> None:
        method = {"name": "Venmo", "qrCodeUrl": "https://host/v.png"}
        with patch.object(offer, "generate_presigned_get_url", return_value="https://signed/v.png"):
            assert _signed_qr_url(ACCOUNT_ID, method, offer.get_logger(__name__)) == "https://signed/v.png"

    def test_signed_qr_url_forbidden_is_suppressed(self) -> None:
        method = {"name": "Venmo", "qrCodeUrl": "https://host/v.png"}
        with patch.object(offer, "generate_presigned_get_url", side_effect=AppError(ErrorCode.FORBIDDEN, "no")):
            assert _signed_qr_url(ACCOUNT_ID, method, offer.get_logger(__name__)) is None

    def test_signed_qr_url_other_error_propagates(self) -> None:
        method = {"name": "Venmo", "qrCodeUrl": "https://host/v.png"}
        with patch.object(offer, "generate_presigned_get_url", side_effect=AppError(ErrorCode.INTERNAL_ERROR, "no")):
            with pytest.raises(AppError):
                _signed_qr_url(ACCOUNT_ID, method, offer.get_logger(__name__))

    def test_pre_signing_leaves_no_filter_on_the_helpers_logger(self) -> None:
        """PRIN-1: the pre-signing call does not mutate another module's logger.

        The key is still passed EXPLICITLY (the helper's no-key probe path is
        three ``head_object`` calls to a guaranteed miss), and the helper's own
        logger carries no ad-hoc filter afterwards: the old runtime
        ``logging.Filter`` was attached to that module's logger for the duration
        of every call and raced with concurrent invocations in one container.
        The key itself is not a secret on this path — the pre-signed URL handed
        to the buyer embeds it.
        """
        helper_logger = logging.getLogger(offer.generate_presigned_get_url.__module__)
        method = {"name": "Venmo", "qrCodeUrl": "https://host/payment-qr-codes/sub1/venmo.png"}
        with patch.object(offer, "generate_presigned_get_url", return_value="https://signed/v.png") as signed:
            assert _signed_qr_url(ACCOUNT_ID, method, offer.get_logger(__name__)) == "https://signed/v.png"
        assert signed.call_args.kwargs["s3_key"] == "payment-qr-codes/sub1/venmo.png"
        assert helper_logger.filters == []

    def test_public_payment_methods_full(self, accounts_table: Any) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})
        blob = {"allowedPaymentMethods": ["venmo", "VENMO", "cash", "paypal", 7]}
        result = _public_payment_methods({"ownerAccountId": ACCOUNT_ID}, blob, offer.get_logger(__name__))
        # dedup the repeated venmo, keep the reserved cash, drop the unknown paypal and the non-str
        assert [m["name"] for m in result] == ["Venmo", "cash"]

    def test_public_payment_methods_allowlist_not_a_list(self, accounts_table: Any) -> None:
        assert (
            _public_payment_methods(
                {"ownerAccountId": ACCOUNT_ID}, {"allowedPaymentMethods": "nope"}, offer.get_logger(__name__)
            )
            == []
        )

    def test_reserved_only_allowlist_never_reads_the_accounts_table(
        self, accounts_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PERF-6: Cash/Check are pseudo-methods, so no preferences read is needed.

        ``_validate_name`` rejects reserved names, so they can never appear in
        ``preferences.paymentMethods``; a cash/check-only offer must answer
        without an accounts-table round trip.
        """
        reads: list[Any] = []
        monkeypatch.setattr(offer, "_stored_methods", lambda owner_account_id: reads.append(owner_account_id) or {})
        blob = {"allowedPaymentMethods": ["cash", "Check"]}
        result = _public_payment_methods({"ownerAccountId": ACCOUNT_ID}, blob, offer.get_logger(__name__))
        assert [method["name"] for method in result] == ["cash", "Check"]
        assert reads == []

    def test_a_stored_method_name_still_triggers_exactly_one_read(
        self, accounts_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})
        reads: list[Any] = []
        real_stored_methods = offer._stored_methods

        def counting(owner_account_id: Any) -> Dict[str, Dict[str, Any]]:
            reads.append(owner_account_id)
            return real_stored_methods(owner_account_id)

        monkeypatch.setattr(offer, "_stored_methods", counting)
        blob = {"allowedPaymentMethods": ["cash", "venmo", "paypal"]}
        result = _public_payment_methods({"ownerAccountId": ACCOUNT_ID}, blob, offer.get_logger(__name__))
        assert [method["name"] for method in result] == ["cash", "Venmo"]
        assert reads == [ACCOUNT_ID]


class TestBuildOffer:
    @pytest.fixture(autouse=True)
    def _seed(self, campaigns_table: Any, profiles_table: Any, catalogs_table: Any, accounts_table: Any) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        profiles_table.put_item(Item=_profile_item())
        catalogs_table.put_item(
            Item={
                "catalogId": CATALOG_ID,
                "name": "Cat",
                "products": [{"productId": "p", "productName": "W", "price": 5, "sortOrder": 1}],
            }
        )
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})

    def test_success(self) -> None:
        offer_result = _build_offer(_event({"campaignId": "c1", "token": "tok"}))
        assert offer_result["sellerName"] == "My Profile"
        assert offer_result["campaignId"] == "c1"
        assert offer_result["campaignName"] == "Fall Sale"
        assert offer_result["products"][0]["productName"] == "W"
        assert offer_result["paymentMethods"][0]["name"] == "Venmo"
        # ARCH-7-BE: remainingOrders and isSoldOut
        assert offer_result["remainingOrders"] == 500  # no publicOrderCount on campaign
        assert offer_result["isSoldOut"] is False

    def test_remaining_orders_and_sold_out(self, campaigns_table: Any) -> None:
        # Need to override the table in the TableAccessor since the handler uses
        # tables.campaigns (which reads from env var), not the moto table directly.
        from src.utils.dynamodb import override_table

        # Campaign with publicOrderCount = 10
        override_table("campaigns", campaigns_table)
        campaigns_table.put_item(Item=_campaign_item(_settings(), publicOrderCount=10))
        offer_result = _build_offer(_event({"campaignId": "c1", "token": "tok"}))
        assert offer_result["remainingOrders"] == 490
        assert offer_result["isSoldOut"] is False

        # Campaign at cap
        campaigns_table.put_item(Item=_campaign_item(_settings(), publicOrderCount=500))
        offer_result = _build_offer(_event({"campaignId": "c1", "token": "tok"}))
        assert offer_result["remainingOrders"] == 0
        assert offer_result["isSoldOut"] is True

        # Campaign over cap (should not happen but handle gracefully)
        campaigns_table.put_item(Item=_campaign_item(_settings(), publicOrderCount=600))
        offer_result = _build_offer(_event({"campaignId": "c1", "token": "tok"}))
        assert offer_result["remainingOrders"] == 0
        assert offer_result["isSoldOut"] is True

        override_table("campaigns", None)

    def test_empty_campaign_id(self) -> None:
        with pytest.raises(AppError) as exc:
            _build_offer(_event({"campaignId": "", "token": "tok"}))
        assert exc.value.error_code is ErrorCode.NOT_FOUND
        assert exc.value.message == OFFER_UNAVAILABLE_MESSAGE

    def test_non_string_campaign_id(self) -> None:
        with pytest.raises(AppError):
            _build_offer(_event({"campaignId": 123, "token": "tok"}))

    def test_bad_token(self) -> None:
        with pytest.raises(AppError):
            _build_offer(_event({"campaignId": "c1", "token": "wrong"}))

    def test_campaign_without_profile_id(self) -> None:
        # _load_campaign already guarantees a non-empty profileId, so this is
        # defense-in-depth; model the corrupted campaign with a stubbed load.
        with patch.object(offer, "_load_campaign", return_value={"publicOrders": _settings()}):
            with pytest.raises(AppError):
                _build_offer(_event({"campaignId": "c1", "token": "tok"}))


class TestRunGuarded:
    def test_app_error_propagates(self) -> None:
        with patch.object(offer, "_build_offer", side_effect=AppError("x", ErrorCode.NOT_FOUND)):
            with pytest.raises(AppError):
                _run_guarded(_event({"campaignId": "c1", "token": "tok"}))

    def test_unexpected_error_is_redacted(self) -> None:
        with patch.object(offer, "_build_offer", side_effect=RuntimeError("boom tok")):
            with pytest.raises(RuntimeError) as exc:
                _run_guarded(_event({"campaignId": "c1", "token": "tok"}))
        assert "tok" not in str(exc.value)
        assert "[redacted]" in str(exc.value)

    def test_unexpected_error_without_token(self) -> None:
        with patch.object(offer, "_build_offer", side_effect=RuntimeError("plain failure")):
            with pytest.raises(RuntimeError) as exc:
                _run_guarded(_event({}))
        assert str(exc.value) == "plain failure"


class TestRedactSecrets:
    def test_replaces_in_text(self) -> None:
        assert str(redact_secrets(RuntimeError("boom tok here"), "tok")) == "boom [redacted] here"

    def test_leaves_when_absent(self) -> None:
        assert str(redact_secrets(RuntimeError("plain"), "tok")) == "plain"

    def test_none_secret(self) -> None:
        assert str(redact_secrets(RuntimeError("boom tok"), None)) == "boom tok"

    def test_empty_secret(self) -> None:
        assert str(redact_secrets(RuntimeError("boom  tok"), "")) == "boom  tok"


class TestHandlerDispatch:
    @pytest.fixture(autouse=True)
    def _seed(self, campaigns_table: Any, profiles_table: Any, catalogs_table: Any, accounts_table: Any) -> None:
        campaigns_table.put_item(Item=_campaign_item(_settings()))
        profiles_table.put_item(Item=_profile_item())
        catalogs_table.put_item(Item={"catalogId": CATALOG_ID, "name": "Cat"})
        accounts_table.put_item(Item={"accountId": ACCOUNT_ID, "preferences": {"paymentMethods": [{"name": "Venmo"}]}})

    def test_success(self, lambda_context: Any) -> None:
        result = handler(_event({"campaignId": "c1", "token": "tok"}), lambda_context)
        assert result["sellerName"] == "My Profile"
        assert result["campaignId"] == "c1"

    def test_bad_token_payload(self, lambda_context: Any) -> None:
        result = handler(_event({"campaignId": "c1", "token": "wrong"}), lambda_context)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.NOT_FOUND

    def test_missing_campaign_payload(self, lambda_context: Any) -> None:
        result = handler(_event({"campaignId": "nope", "token": "tok"}), lambda_context)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.NOT_FOUND

    def test_unexpected_error_payload(self, lambda_context: Any) -> None:
        with patch.object(offer, "_build_offer", side_effect=RuntimeError("kaput tok")):
            result = handler(_event({"campaignId": "c1", "token": "tok"}), lambda_context)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.INTERNAL_ERROR
        assert "tok" not in str(result)

    def test_receipt_field_dispatches(self, orders_table: Any, lambda_context: Any) -> None:
        orders_table.put_item(
            Item={
                "campaignId": CAMPAIGN_ID,
                "orderId": "ORDER#c1#s1",
                "receiptToken": "tok",
                "sellerName": "S",
                "orderDate": _recent_order_date(0),
                "totalAmount": 1,
                "paymentMethod": "Cash",
                "status": "NEW",
                "lineItems": [],
            }
        )
        result = handler(
            _event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}, "publicGetOrderReceipt"),
            lambda_context,
        )
        assert result["orderId"] == "ORDER#c1#s1"

    def test_unknown_field_is_refused(self, lambda_context: Any) -> None:
        result = handler(_event({}, "publicSomethingElse"), lambda_context)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.INTERNAL_ERROR

    def test_missing_field_is_refused(self, lambda_context: Any) -> None:
        result = handler({"arguments": {"campaignId": "c1"}}, lambda_context)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.INTERNAL_ERROR
