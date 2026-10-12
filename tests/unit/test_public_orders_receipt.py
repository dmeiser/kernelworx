"""Unit tests for the public buyer receipt read (#679 write slice).

``publicGetOrderReceipt`` is the token-authenticated read behind the buyer's
receipt link ``/r/<campaignId>/<orderSuffix>/<receiptToken>``. The order id
arrives split across two arguments because the raw ``ORDER#…#…`` id carries a
``#``; the handler re-prefixes it explicitly and answers from ONE strongly
consistent orders GetItem.

These tests pin:

- the exact base-table key the read issues, and that a legacy two-part
  ``ORDER#<uuid>`` id is simply unreachable — no GSI fallback;
- every negative branch (unknown order, absent token, wrong token, an
  authenticated order with no ``receiptToken``, a tampered segment, an
  embedded-campaign mismatch) answering the *identical* NOT_FOUND;
- the disclosure boundary: the receipt view carries the order and the buyer's
  own name, never the buyer's contact fields and never the receipt token;
- logging hygiene: no log record carries the receipt token, including the
  decorator's generic ``error=str(e)`` line.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
import botocore.client
import pytest

from src.handlers.public_orders_offer import handler
from src.utils.dynamodb import override_table

ORDERS_TABLE = "kernelworx-orders-v2-ue1-dev"

CAMPAIGN_ID = "CAMPAIGN#campaign-123"
BARE_CAMPAIGN_ID = "campaign-123"
ORDER_SUFFIX = "0f1e2d3c-4b5a-4678-9abc-def012345678"
ORDER_ID = f"ORDER#{BARE_CAMPAIGN_ID}#{ORDER_SUFFIX}"
PROFILE_ID = "PROFILE#profile-123"
RECEIPT_TOKEN = "9a8b7c6d-5e4f-4a3b-8c7d-6e5f4a3b2c1d"

NOT_FOUND_PAYLOAD = {"__isError": True, "errorCode": "NOT_FOUND", "message": "Receipt not available"}


class StubOrdersTable:
    """Answers ``get_item`` with a canned item, bypassing moto's key validation.

    Used only for stored shapes the write path cannot produce (an ``orderId``
    attribute disagreeing with the row's key, a non-string key attribute), so
    the defensive branches of the read are still exercised. It also records the
    keys it was asked for, which is how the exact reconstructed key is pinned.
    """

    def __init__(self, item: Optional[Dict[str, Any]]) -> None:
        self._item = item
        self.calls: List[Dict[str, Any]] = []

    def get_item(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"Key": kwargs.get("Key"), "ConsistentRead": kwargs.get("ConsistentRead")})
        return {"Item": self._item} if self._item is not None else {}


class ApiCallRecorder:
    """Records DynamoDB API calls once ``attach()`` is invoked.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style calls are
    captured with their real operation names. Seeding done before ``attach()``
    is not recorded. This is how "no GSI fallback" is pinned: a capability
    lookup that fell back to the eventually consistent ``orderId-index`` would
    record a Query.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dynamodb_calls: List[Any] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        recorded = self.dynamodb_calls

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            service = self.meta.service_model.service_name
            if service == "dynamodb" and isinstance(params, dict):
                recorded.append((operation_name, params.get("TableName"), params.get("IndexName")))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> ApiCallRecorder:
    """Provide an API call recorder; call ``attach()`` after seeding data."""
    return ApiCallRecorder(monkeypatch)


@pytest.fixture
def orders_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table(ORDERS_TABLE)


def seed_order(
    table: Any,
    *,
    campaign_id: str = CAMPAIGN_ID,
    order_id: str = ORDER_ID,
    receipt_token: Optional[str] = RECEIPT_TOKEN,
    status: Optional[str] = "NEW",
    seller_name: Optional[str] = "Test Seller",
    line_items: Optional[List[Dict[str, Any]]] = None,
    total_amount: Any = Decimal("9.00"),
) -> None:
    """Seed one public order row as the create pipeline writes it."""
    item: Dict[str, Any] = {
        "campaignId": campaign_id,
        "orderId": order_id,
        "profileId": PROFILE_ID,
        "customerName": "Ada Lovelace",
        "customerFirstName": "Ada",
        "customerLastName": "Lovelace",
        "customerPhone": "+15551234567",
        "customerEmail": "buyer@example.com",
        "orderDate": "2026-01-02T10:00:00Z",
        "paymentMethod": "Venmo",
        "lineItems": line_items
        if line_items is not None
        else [
            {
                "productId": "PRODUCT#a",
                "productName": "First",
                "quantity": 1,
                "pricePerUnit": Decimal("9.00"),
                "subtotal": Decimal("9.00"),
            }
        ],
        "totalAmount": total_amount,
        "orderSource": "PUBLIC",
        "createdAt": "2026-01-02T10:00:00Z",
        "updatedAt": "2026-01-02T10:00:00Z",
    }
    if status is not None:
        item["status"] = status
    if seller_name is not None:
        item["sellerName"] = seller_name
    if receipt_token is not None:
        item["receiptToken"] = receipt_token
    table.put_item(Item=item)


def receipt_event(**overrides: Any) -> Dict[str, Any]:
    """The unit-resolver payload for one receipt request (identity is null)."""
    arguments: Dict[str, Any] = {
        "campaignId": BARE_CAMPAIGN_ID,
        "orderSuffix": ORDER_SUFFIX,
        "receiptToken": RECEIPT_TOKEN,
    }
    arguments.update(overrides)
    return {"arguments": arguments, "identity": None, "info": {"fieldName": "publicGetOrderReceipt"}, "stash": {}}


def call(event: Dict[str, Any]) -> Any:
    return handler(event, None)


class TestReceiptPositive:
    """The shape a buyer sees, and the single read that produces it."""

    def test_receipt_shape(self, orders_table: Any) -> None:
        seed_order(orders_table)

        result = call(receipt_event())

        assert result["orderId"] == ORDER_ID
        assert result["sellerName"] == "Test Seller"
        assert result["orderDate"] == "2026-01-02T10:00:00Z"
        assert result["totalAmount"] == 9.0
        assert result["paymentMethodName"] == "Venmo"
        assert result["status"] == "NEW"
        assert result["buyerFirstName"] == "Ada"
        assert result["buyerLastName"] == "Lovelace"
        assert result["lineItems"] == [
            {"productId": "PRODUCT#a", "productName": "First", "quantity": 1, "pricePerUnit": 9.0, "subtotal": 9.0}
        ]

    def test_read_issues_one_consistent_getitem_on_the_reconstructed_key(self) -> None:
        stub = StubOrdersTable(
            {
                "campaignId": CAMPAIGN_ID,
                "orderId": ORDER_ID,
                "receiptToken": RECEIPT_TOKEN,
                "orderDate": "2026-01-02T10:00:00Z",
                "totalAmount": Decimal("1"),
                "paymentMethod": "Cash",
                "lineItems": [],
            }
        )
        override_table("orders", stub)

        call(receipt_event())

        assert stub.calls == [{"Key": {"campaignId": CAMPAIGN_ID, "orderId": ORDER_ID}, "ConsistentRead": True}]

    def test_only_one_dynamodb_call_is_issued(self, orders_table: Any, api_calls: Any) -> None:
        """The seller name rides the order row, so the read needs no profile read."""
        seed_order(orders_table)
        api_calls.attach()

        call(receipt_event())

        assert api_calls.dynamodb_calls == [("GetItem", ORDERS_TABLE, None)]

    def test_prefixed_campaign_id_argument_is_accepted(self, orders_table: Any) -> None:
        seed_order(orders_table)

        assert call(receipt_event(campaignId=CAMPAIGN_ID))["orderId"] == ORDER_ID

    def test_confirmed_status_is_reflected(self, orders_table: Any) -> None:
        seed_order(orders_table, status="CONFIRMED")

        assert call(receipt_event())["status"] == "CONFIRMED"

    def test_a_row_without_status_reads_new(self, orders_table: Any) -> None:
        seed_order(orders_table, status=None)

        assert call(receipt_event())["status"] == "NEW"

    def test_receipt_never_echoes_the_token_or_the_buyer_contact(self, orders_table: Any) -> None:
        seed_order(orders_table)

        result = call(receipt_event())

        assert RECEIPT_TOKEN not in str(result)
        for field in ("customerEmail", "customerPhone", "customerAddress", "receiptToken", "notes", "profileId"):
            assert field not in result

    def test_order_without_a_seller_name_degrades_to_empty(self, orders_table: Any) -> None:
        seed_order(orders_table, seller_name=None)

        assert call(receipt_event())["sellerName"] == ""

    def test_malformed_line_items_are_dropped_not_fatal(self, orders_table: Any) -> None:
        seed_order(
            orders_table,
            line_items=[
                {
                    "productId": "PRODUCT#a",
                    "productName": "First",
                    "quantity": 1,
                    "pricePerUnit": Decimal("1"),
                    "subtotal": Decimal("1"),
                },
                "not-an-item",
                {"productId": 7, "quantity": 1, "pricePerUnit": 1, "subtotal": 1},
                {"productId": "PRODUCT#b", "quantity": 1, "pricePerUnit": 1, "subtotal": 1},
                {"productId": "PRODUCT#c", "pricePerUnit": 1, "subtotal": 1},
            ],
        )

        shaped = call(receipt_event())["lineItems"]

        assert [item["productId"] for item in shaped] == ["PRODUCT#a", "PRODUCT#b"]
        assert shaped[1]["productName"] == ""

    def test_unusable_total_reads_zero_rather_than_failing(self, orders_table: Any) -> None:
        seed_order(orders_table, total_amount="not-a-number")

        assert call(receipt_event())["totalAmount"] == 0.0


class TestReceiptNegative:
    """Every failure answers the identical NOT_FOUND, so probing learns nothing."""

    def test_wrong_token(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(receiptToken="deadbeef")) == NOT_FOUND_PAYLOAD

    def test_missing_token_argument(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(receiptToken=None)) == NOT_FOUND_PAYLOAD

    def test_empty_token_argument(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(receiptToken="")) == NOT_FOUND_PAYLOAD

    def test_unknown_order(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(orderSuffix="00000000-0000-0000-0000-000000000000")) == NOT_FOUND_PAYLOAD

    def test_authenticated_order_has_no_receipt_link(self, orders_table: Any) -> None:
        """A row with no ``receiptToken`` attribute is not a receipt oracle."""
        seed_order(orders_table, receipt_token=None)
        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_stored_token_empty_is_a_mismatch(self, orders_table: Any) -> None:
        seed_order(orders_table, receipt_token="")
        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_order_a_with_order_bs_token(self, orders_table: Any) -> None:
        seed_order(orders_table)
        seed_order(
            orders_table,
            order_id=f"ORDER#{BARE_CAMPAIGN_ID}#11111111-2222-3333-4444-555555555555",
            receipt_token="another-order-token",
        )

        assert (
            call(receipt_event(orderSuffix="11111111-2222-3333-4444-555555555555", receiptToken=RECEIPT_TOKEN))
            == NOT_FOUND_PAYLOAD
        )

    def test_legacy_two_part_order_id_is_unreachable_without_a_gsi_fallback(
        self, orders_table: Any, api_calls: Any
    ) -> None:
        """A pre-split id cannot be addressed by the two-segment contract."""
        seed_order(orders_table, order_id=f"ORDER#{ORDER_SUFFIX}")
        api_calls.attach()

        assert call(receipt_event(orderSuffix=ORDER_SUFFIX)) == NOT_FOUND_PAYLOAD
        assert [name for name, _, _ in api_calls.dynamodb_calls] == ["GetItem"], (
            "no GSI fallback on a capability lookup"
        )
        assert all(index is None for _, _, index in api_calls.dynamodb_calls)

    def test_order_suffix_carrying_a_hash_is_refused_before_any_read(self, orders_table: Any, api_calls: Any) -> None:
        seed_order(orders_table)
        api_calls.attach()

        assert call(receipt_event(orderSuffix=f"{BARE_CAMPAIGN_ID}#{ORDER_SUFFIX}")) == NOT_FOUND_PAYLOAD
        assert api_calls.dynamodb_calls == []

    def test_empty_order_suffix_is_refused(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(orderSuffix="")) == NOT_FOUND_PAYLOAD

    def test_non_string_order_suffix_is_refused(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(orderSuffix=42)) == NOT_FOUND_PAYLOAD

    def test_missing_campaign_argument(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(campaignId=None)) == NOT_FOUND_PAYLOAD

    def test_campaign_argument_that_re_prefixes_to_an_empty_bare_id(self, orders_table: Any) -> None:
        seed_order(orders_table)
        assert call(receipt_event(campaignId="#")) == NOT_FOUND_PAYLOAD

    def test_embedded_campaign_mismatch_is_refused(self, orders_table: Any) -> None:
        """A row whose orderId attribute disagrees with its key is not served."""
        override_table(
            "orders",
            StubOrdersTable(
                {
                    "campaignId": CAMPAIGN_ID,
                    "orderId": f"ORDER#other-campaign#{ORDER_SUFFIX}",
                    "receiptToken": RECEIPT_TOKEN,
                    "orderDate": "2026-01-02T10:00:00Z",
                    "totalAmount": Decimal("1"),
                    "paymentMethod": "Cash",
                    "lineItems": [],
                }
            ),
        )

        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_stored_order_id_that_is_not_a_string_is_refused(self, orders_table: Any) -> None:
        override_table(
            "orders", StubOrdersTable({"campaignId": CAMPAIGN_ID, "orderId": 7, "receiptToken": RECEIPT_TOKEN})
        )
        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_stored_order_id_with_the_wrong_shape_is_refused(self, orders_table: Any) -> None:
        override_table(
            "orders",
            StubOrdersTable(
                {"campaignId": CAMPAIGN_ID, "orderId": f"ORDER#{BARE_CAMPAIGN_ID}", "receiptToken": RECEIPT_TOKEN}
            ),
        )
        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_stored_order_id_with_an_empty_segment_is_refused(self, orders_table: Any) -> None:
        override_table(
            "orders", StubOrdersTable({"campaignId": CAMPAIGN_ID, "orderId": "ORDER##", "receiptToken": RECEIPT_TOKEN})
        )
        assert call(receipt_event()) == NOT_FOUND_PAYLOAD

    def test_every_negative_branch_shares_one_payload(self, orders_table: Any) -> None:
        seed_order(orders_table)
        payloads = {
            str(call(receipt_event(receiptToken="wrong"))),
            str(call(receipt_event(orderSuffix="missing"))),
            str(call(receipt_event(campaignId=None))),
            str(call(receipt_event(orderSuffix="a#b"))),
        }
        assert payloads == {str(NOT_FOUND_PAYLOAD)}

    def test_unsupported_field_name_is_an_internal_error(self, orders_table: Any) -> None:
        event = receipt_event()
        event["info"] = {"fieldName": "somethingElse"}

        result = call(event)

        assert result["errorCode"] == "INTERNAL_ERROR"


class TestReceiptLoggingHygiene:
    """The receipt token is a durable capability; it never reaches a log line."""

    def test_no_log_record_carries_the_receipt_token(self, orders_table: Any, caplog: pytest.LogCaptureFixture) -> None:
        seed_order(orders_table)

        with caplog.at_level(logging.INFO):
            call(receipt_event())
            call(receipt_event(receiptToken="wrong"))

        assert RECEIPT_TOKEN not in caplog.text
        assert "buyer@example.com" not in caplog.text
        assert "+15551234567" not in caplog.text

    def test_generic_unexpected_exception_does_not_leak_the_token(
        self, orders_table: Any, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The decorator's ``error=str(e)`` line is the real leak surface."""
        seed_order(orders_table)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"validation failed for value {RECEIPT_TOKEN}")

        monkeypatch.setattr("src.handlers.public_orders_receipt._load_order", explode)

        with caplog.at_level(logging.INFO):
            result = call(receipt_event())

        assert result["errorCode"] == "INTERNAL_ERROR"
        assert RECEIPT_TOKEN not in caplog.text
        assert "validation failed" in caplog.text

    def test_generic_exception_without_the_token_is_left_alone(
        self, orders_table: Any, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed_order(orders_table)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("dynamodb throttled")

        monkeypatch.setattr("src.handlers.public_orders_receipt._load_order", explode)

        with caplog.at_level(logging.INFO):
            result = call(receipt_event())

        assert result["errorCode"] == "INTERNAL_ERROR"
        assert "dynamodb throttled" in caplog.text
