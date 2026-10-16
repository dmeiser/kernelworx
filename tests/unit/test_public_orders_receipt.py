"""Unit tests for the public buyer receipt read handler.

Covers ``src/handlers/public_orders_receipt.py`` line- and branch-wise
(``--cov-fail-under=100``): the two URL-segment arguments are re-prefixed into
the orders base-table key, one strongly consistent GetItem answers the read, and
every negative branch (unknown order, no token, a mismatched token, a malformed
or legacy id, an embedded-campaign mismatch) raises the identical NOT_FOUND.

The private helpers are exercised directly so the defense-in-depth branches of
``_embedded_campaign_matches`` — only reachable with a hand-corrupted row — are
covered without a datastore round trip.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.handlers.public_orders_receipt import (
    _as_float,
    _build_receipt,
    _embedded_campaign_matches,
    _line_items,
    _load_order,
    _order_key,
    _redact_secrets,
    _status,
    _text,
    _token_matches,
    handle_receipt,
    run_receipt,
)
from src.utils.errors import AppError, ErrorCode

CAMPAIGN_ID = "CAMPAIGN#c1"
ORDER_SUFFIX = "s1"
ORDER_ID = f"ORDER#{ORDER_SUFFIX.split('#')[0]}"  # computed below in _order_id()


def _order_id(campaign_id: str = CAMPAIGN_ID, suffix: str = ORDER_SUFFIX) -> str:
    return f"ORDER#{campaign_id.removeprefix('CAMPAIGN#')}#{suffix}"


def _event(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {"arguments": arguments, "info": {"fieldName": "publicGetOrderReceipt"}, "identity": None}


def _order(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "campaignId": CAMPAIGN_ID,
        "orderId": _order_id(),
        "receiptToken": "tok",
        "sellerName": "Seller One",
        "orderDate": "2024-01-01T00:00:00Z",
        "totalAmount": Decimal("10.50"),
        "paymentMethod": "Venmo",
        "status": "NEW",
        "customerFirstName": "Jane",
        "customerLastName": "Doe",
        "lineItems": [
            {
                "productId": "prod-1",
                "productName": "Widget",
                "quantity": Decimal("2"),
                "pricePerUnit": Decimal("5.25"),
                "subtotal": Decimal("10.50"),
            }
        ],
    }
    if overrides:
        item.update(overrides)
    return item


class TestOrderKey:
    def test_happy_path_builds_composite_key(self) -> None:
        campaign_id, order_id = _order_key({"campaignId": "c1", "orderSuffix": "s1"})
        assert campaign_id == CAMPAIGN_ID
        assert order_id == "ORDER#c1#s1"

    def test_accepts_already_prefixed_campaign(self) -> None:
        campaign_id, order_id = _order_key({"campaignId": CAMPAIGN_ID, "orderSuffix": "s1"})
        assert campaign_id == CAMPAIGN_ID
        assert order_id == "ORDER#c1#s1"

    def test_empty_campaign_id_is_refused(self) -> None:
        with pytest.raises(AppError) as exc:
            _order_key({"campaignId": "", "orderSuffix": "s1"})
        assert exc.value.error_code is ErrorCode.NOT_FOUND

    def test_missing_campaign_id_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"orderSuffix": "s1"})

    def test_non_string_order_suffix_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"campaignId": "c1", "orderSuffix": 123})

    def test_empty_order_suffix_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"campaignId": "c1", "orderSuffix": ""})

    def test_order_suffix_carrying_a_fragment_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"campaignId": "c1", "orderSuffix": "a#b"})

    def test_campaign_with_empty_bare_id_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"campaignId": "CAMPAIGN#", "orderSuffix": "s1"})

    def test_campaign_bare_id_carrying_a_fragment_is_refused(self) -> None:
        with pytest.raises(AppError):
            _order_key({"campaignId": "a#b", "orderSuffix": "s1"})


class TestLoadOrder:
    def test_missing_order_is_unavailable(self, orders_table: Any) -> None:
        with pytest.raises(AppError) as exc:
            _load_order(CAMPAIGN_ID, "ORDER#c1#nope")
        assert exc.value.error_code is ErrorCode.NOT_FOUND

    def test_returns_the_stored_item(self, orders_table: Any) -> None:
        orders_table.put_item(Item=_order())
        item = _load_order(CAMPAIGN_ID, "ORDER#c1#s1")
        assert item["receiptToken"] == "tok"


class TestTokenMatches:
    def test_matching_tokens(self) -> None:
        assert _token_matches(_order(), "tok")

    def test_mismatched_tokens(self) -> None:
        assert not _token_matches(_order(), "wrong")

    def test_order_without_a_token_attribute(self) -> None:
        assert not _token_matches({"orderId": "x"}, "tok")

    def test_order_with_empty_token(self) -> None:
        assert not _token_matches(_order({"receiptToken": ""}), "tok")

    def test_order_with_non_string_token(self) -> None:
        assert not _token_matches(_order({"receiptToken": 7}), "tok")

    def test_non_string_submission(self) -> None:
        assert not _token_matches(_order(), None)

    def test_empty_submission(self) -> None:
        assert not _token_matches(_order(), "")


class TestEmbeddedCampaignMatches:
    def test_matching_embedded_campaign(self) -> None:
        assert _embedded_campaign_matches(_order(), CAMPAIGN_ID)

    def test_non_string_order_id(self) -> None:
        assert not _embedded_campaign_matches(_order({"orderId": 123}), CAMPAIGN_ID)

    def test_wrong_segment_count(self) -> None:
        assert not _embedded_campaign_matches(_order({"orderId": "ORDER#c1"}), CAMPAIGN_ID)

    def test_empty_embedded_campaign(self) -> None:
        assert not _embedded_campaign_matches(_order({"orderId": "ORDER##s1"}), CAMPAIGN_ID)

    def test_empty_suffix_segment(self) -> None:
        assert not _embedded_campaign_matches(_order({"orderId": "ORDER#c1#"}), CAMPAIGN_ID)

    def test_embedded_campaign_disagrees(self) -> None:
        assert not _embedded_campaign_matches(_order({"orderId": "ORDER#other#s1"}), CAMPAIGN_ID)


class TestCoercionHelpers:
    def test_as_float_numeric_forms(self) -> None:
        assert _as_float(2) == 2.0
        assert _as_float(1.5) == 1.5
        assert _as_float(Decimal("3")) == 3.0
        assert _as_float("4") == 4.0

    def test_as_float_rejects_non_numbers(self) -> None:
        assert _as_float(None) is None
        assert _as_float("not a number") is None
        assert _as_float([1]) is None

    def test_line_items_shapes_usable_rows(self) -> None:
        items = _line_items(_order())
        assert items == [
            {
                "productId": "prod-1",
                "productName": "Widget",
                "quantity": 2,
                "pricePerUnit": 5.25,
                "subtotal": 10.5,
            }
        ]

    def test_line_items_drops_unusable_rows(self) -> None:
        order = {
            "lineItems": [
                "not a dict",
                {"productName": "No Product", "quantity": 1, "pricePerUnit": 1, "subtotal": 1},  # missing product_id
                {"productId": "p", "quantity": "abc", "pricePerUnit": 1, "subtotal": 1},  # bad quantity
                {"productId": "p", "quantity": 1, "pricePerUnit": None, "subtotal": 1},  # bad price
                {"productId": "p", "quantity": 1, "pricePerUnit": 1, "subtotal": "zzz"},  # bad subtotal
                {"productId": "ok", "productName": "Good", "quantity": 1, "pricePerUnit": 2, "subtotal": 2},
            ]
        }
        assert _line_items(order) == [
            {"productId": "ok", "productName": "Good", "quantity": 1, "pricePerUnit": 2.0, "subtotal": 2.0}
        ]

    def test_text_passthrough_and_empty(self) -> None:
        assert _text("value") == "value"
        assert _text(None) == ""
        assert _text(123) == ""

    def test_status_known_and_default(self) -> None:
        assert _status({"status": "NEW"}) == "NEW"
        assert _status({"status": "CONFIRMED"}) == "CONFIRMED"
        assert _status({}) == "NEW"
        assert _status({"status": "WEIRD"}) == "NEW"


class TestBuildReceipt:
    def test_success(self, orders_table: Any) -> None:
        orders_table.put_item(Item=_order())
        receipt = _build_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}))
        assert receipt["orderId"] == "ORDER#c1#s1"
        assert receipt["sellerName"] == "Seller One"
        assert receipt["totalAmount"] == 10.5
        assert receipt["status"] == "NEW"
        assert receipt["paymentMethodName"] == "Venmo"
        assert receipt["buyerFirstName"] == "Jane"
        assert receipt["buyerLastName"] == "Doe"
        assert receipt["lineItems"][0]["productId"] == "prod-1"

    def test_mismatched_token_is_unavailable(self, orders_table: Any) -> None:
        orders_table.put_item(Item=_order())
        with pytest.raises(AppError) as exc:
            _build_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "nope"}))
        assert exc.value.error_code is ErrorCode.NOT_FOUND

    def test_missing_order_is_unavailable(self, orders_table: Any) -> None:
        with pytest.raises(AppError):
            _build_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}))


class TestRunReceipt:
    def test_success(self, orders_table: Any) -> None:
        orders_table.put_item(Item=_order())
        receipt = run_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}))
        assert receipt["orderId"] == "ORDER#c1#s1"

    def test_app_error_propagates(self, orders_table: Any) -> None:
        with pytest.raises(AppError):
            run_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}))

    def test_unexpected_error_is_redacted(self, orders_table: Any) -> None:
        token = "secret-token"
        boom = RuntimeError(f"boom {token}")

        with patch("src.handlers.public_orders_receipt._build_receipt", side_effect=boom):
            with pytest.raises(RuntimeError) as exc:
                run_receipt(_event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": token}))

        assert token not in str(exc.value)
        assert "[redacted]" in str(exc.value)

    def test_unexpected_error_without_token_leaves_message(self, orders_table: Any) -> None:
        boom = RuntimeError("some other failure")

        with patch("src.handlers.public_orders_receipt._build_receipt", side_effect=boom):
            with pytest.raises(RuntimeError) as exc:
                run_receipt(_event({"campaignId": "c1", "orderSuffix": "s1"}))

        assert str(exc.value) == "some other failure"


class TestRedactSecrets:
    def test_replaces_the_secret_in_place(self) -> None:
        exc = RuntimeError("boom secret-token here")
        redacted = _redact_secrets(exc, "secret-token")
        assert str(redacted) == "boom [redacted] here"

    def test_leaves_a_message_that_never_carried_it(self) -> None:
        exc = RuntimeError("plain failure")
        redacted = _redact_secrets(exc, "secret-token")
        assert str(redacted) == "plain failure"

    def test_none_secret_is_a_noop(self) -> None:
        exc = RuntimeError("boom token here")
        redacted = _redact_secrets(exc, None)
        assert str(redacted) == "boom token here"

    def test_empty_secret_is_a_noop(self) -> None:
        exc = RuntimeError("boom  here")
        redacted = _redact_secrets(exc, "")
        assert str(redacted) == "boom  here"


class TestHandleReceipt:
    def test_success_payload(self, orders_table: Any, lambda_context: Any) -> None:
        orders_table.put_item(Item=_order())
        result = handle_receipt(
            _event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}), lambda_context
        )
        assert result["orderId"] == "ORDER#c1#s1"
        # The origin/dev confirmationEmailSent flag was deliberately dropped: email
        # delivery is not wired in this slice, so the receipt omits the field.
        assert "confirmationEmailSent" not in result

    def test_not_found_payload(self, orders_table: Any, lambda_context: Any) -> None:
        result = handle_receipt(
            _event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}), lambda_context
        )
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.NOT_FOUND

    def test_unexpected_error_payload(self, orders_table: Any, lambda_context: Any) -> None:
        with patch("src.handlers.public_orders_receipt._build_receipt", side_effect=RuntimeError("kaput")):
            result = handle_receipt(
                _event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}), lambda_context
            )
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.INTERNAL_ERROR


class TestOrderStatusBackCompat:
    def test_legacy_row_without_status_reads_new(self, orders_table: Any, lambda_context: Any) -> None:
        order = _order()
        del order["status"]
        orders_table.put_item(Item=order)
        result = handle_receipt(
            _event({"campaignId": "c1", "orderSuffix": "s1", "receiptToken": "tok"}), lambda_context
        )
        assert result["status"] == "NEW"
