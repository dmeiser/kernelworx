"""Unit tests for the best-effort order-confirmation mailer (KW-PUBLIC-ORDERS-SES-1).

Covers the spec §10.2 ``test_public_order_emails`` contract: buyer email first,
with the seller half (owner-account ``GetItem`` included) isolated behind its own
error boundary; seller email always attempted to the owner account's ``email``;
buyer email only when provided and carrying the tokenized receipt link
absolutized from ``SITE_URL``; the three honest ``confirmationEmailSent`` states;
SES rejection swallowed; the ephemeral shape (no SES env vars) branches BEFORE
any SES client construction; the SES client carries explicit short timeouts; the
handler pre-escapes nothing (SES Handlebars auto-escapes raw); and no log record
ever contains the receipt token, the buyer email, or the phone.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import boto3
import pytest
from botocore.exceptions import ClientError

from src.handlers import public_order_emails
from src.handlers.public_order_emails import handle_send_order_emails
from src.handlers.public_orders_offer import handler as public_orders_handler
from tests.unit.test_payment_role_scope import ApiCallRecorder

ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"

OWNER_ACCOUNT_ID = "sub1"
SELLER_EMAIL = "seller@example.com"
BUYER_EMAIL = "ada@example.com"
ORDER_ID = "ORDER#c1#s1"
RECEIPT_TOKEN = "rtok"
BUYER_PHONE = "5551234567"

ORDER: Dict[str, Any] = {
    "orderId": ORDER_ID,
    "campaignId": "CAMPAIGN#c1",
    "profileId": "PROFILE#p1",
    "customerFirstName": "Ada",
    "customerLastName": "O'Brien",
    "customerName": "Ada O'Brien",
    "customerEmail": BUYER_EMAIL,
    "customerPhone": BUYER_PHONE,
    "paymentMethod": "Cash",
    "sellerName": "Troops R Us",
    "lineItems": [{"productId": "p1", "productName": "Cookies", "quantity": 2, "subtotal": 10.0}],
    "totalAmount": 10.0,
    "receiptToken": RECEIPT_TOKEN,
}


def make_event(**overrides: Any) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "operation": "send_order_emails",
        "order": ORDER,
        "sellerName": "Troops R Us",
        "ownerAccountId": OWNER_ACCOUNT_ID,
        "campaignName": "Fall Sale",
        "receiptUrl": "/r/c1/s1/rtok",
    }
    event.update(overrides)
    return event


@pytest.fixture
def ses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configured-SES shape: all four env vars set."""
    monkeypatch.setenv("SES_ORDER_FROM_ADDRESS", "orders@dev.kernelworx.app")
    monkeypatch.setenv("SES_ORDER_TEMPLATE", "order-confirm-dev")
    monkeypatch.setenv("SES_ORDER_SELLER_TEMPLATE", "order-confirm-seller-dev")
    monkeypatch.setenv("SITE_URL", "https://dev.kernelworx.app/")


class FakeSes:
    """Records send_templated_email calls; optionally fails every send."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._fail = fail

    def send_templated_email(self, **kwargs: Any) -> Dict[str, Any]:
        if self._fail:
            raise RuntimeError("SES throttled")
        self.calls.append(kwargs)
        return {"MessageId": "msg-1"}


@pytest.fixture
def fake_ses(monkeypatch: pytest.MonkeyPatch) -> FakeSes:
    """Route boto3.client('ses') to the fake so the real ``_ses_client`` body runs.

    Any other service falls through to the real boto3 client (nothing else is
    constructed after the env contract passes).
    """
    fake = FakeSes()
    real_client = boto3.client

    def fake_client(service: str, *args: Any, **kwargs: Any) -> Any:
        if service == "ses":
            return fake
        return real_client(service, *args, **kwargs)

    monkeypatch.setattr(public_order_emails.boto3, "client", fake_client)
    return fake


def _seller_call(fake: FakeSes) -> Dict[str, Any]:
    """The seller send, located by template rather than by call order."""
    return next(call for call in fake.calls if call["Template"] == "order-confirm-seller-dev")


def _buyer_call(fake: FakeSes) -> Dict[str, Any]:
    """The buyer send, located by template rather than by call order."""
    return next(call for call in fake.calls if call["Template"] == "order-confirm-dev")


def _seed_account(dynamodb_table: Any, email: Optional[str]) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(ACCOUNTS_TABLE)
    item: Dict[str, Any] = {"accountId": "ACCOUNT#sub1"}
    if email is not None:
        item["email"] = email
    table.put_item(Item=item)
    return table


class TestUnconfigured:
    """The ephemeral shape: no SES env vars -> no client, honest not-configured."""

    def test_no_env_vars_constructs_no_client_and_reports_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch, dynamodb_table: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        for var in (
            "SES_ORDER_FROM_ADDRESS",
            "SES_ORDER_TEMPLATE",
            "SES_ORDER_SELLER_TEMPLATE",
            "SITE_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("boto3.client must not be called without the SES env contract")

        monkeypatch.setattr(public_order_emails.boto3, "client", boom)

        with caplog.at_level(logging.INFO):
            result = handle_send_order_emails(make_event(), None)

        assert result == {"configured": False, "sellerEmailSent": False, "confirmationEmailSent": False}

    def test_partial_env_vars_are_unconfigured(self, monkeypatch: pytest.MonkeyPatch, dynamodb_table: Any) -> None:
        monkeypatch.setenv("SES_ORDER_FROM_ADDRESS", "orders@dev.kernelworx.app")
        monkeypatch.delenv("SES_ORDER_TEMPLATE", raising=False)
        monkeypatch.delenv("SES_ORDER_SELLER_TEMPLATE", raising=False)
        monkeypatch.delenv("SITE_URL", raising=False)

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("boto3.client must not be called on a partial env contract")

        monkeypatch.setattr(public_order_emails.boto3, "client", boom)
        result = handle_send_order_emails(make_event(), None)
        assert result["configured"] is False


class TestBuyerFirstOrdering:
    """FUNC-12/ARCH-5: the buyer confirmation is the mailer's critical path."""

    def test_the_buyer_send_is_issued_before_the_seller_send(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)

        handle_send_order_emails(make_event(), None)

        assert [call["Template"] for call in fake_ses.calls] == ["order-confirm-dev", "order-confirm-seller-dev"]

    def test_a_throttled_owner_account_read_still_sends_the_buyer_confirmation(
        self,
        ses_env: None,
        fake_ses: FakeSes,
        dynamodb_table: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The seller half's ``GetItem`` ran OUTSIDE any error boundary.

        A throttling fault there aborted the Lambda before the buyer's
        confirmation was even attempted. It is now logged and swallowed, and it
        runs after the buyer send.
        """

        def throttled(**_kwargs: Any) -> Dict[str, Any]:
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "Slow down"}}, "GetItem")

        monkeypatch.setattr(public_order_emails.tables.accounts, "get_item", throttled)

        with caplog.at_level(logging.WARNING):
            result = handle_send_order_emails(make_event(), None)

        assert result["configured"] is True
        assert result["confirmationEmailSent"] is True
        assert result["sellerEmailSent"] is False
        assert _buyer_call(fake_ses)["Destination"]["ToAddresses"] == [BUYER_EMAIL]
        assert len(fake_ses.calls) == 1
        assert any("seller email failed" in record.message for record in caplog.records)

    def test_the_ses_client_carries_explicit_short_timeouts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ARCH-5: the mailer runs inside the checkout, so its client is bounded.

        Default botocore timeouts allow ~15s per attempt, which holds the buyer's
        mutation open and provokes duplicate submissions.
        """
        captured: Dict[str, Any] = {}

        def fake_client(service: str, **kwargs: Any) -> object:
            captured["service"] = service
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(public_order_emails.boto3, "client", fake_client)

        public_order_emails._ses_client()

        config = captured["config"]
        assert captured["service"] == "ses"
        assert config.connect_timeout == public_order_emails._SES_CONNECT_TIMEOUT_SECONDS
        assert config.read_timeout == public_order_emails._SES_READ_TIMEOUT_SECONDS
        assert (config.connect_timeout, config.read_timeout) == (2, 3)


class TestSellerEmail:
    def test_seller_email_always_attempted_to_the_owner_accounts_email(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)

        result = handle_send_order_emails(make_event(), None)

        assert result["configured"] is True
        assert result["sellerEmailSent"] is True
        seller_call = _seller_call(fake_ses)
        assert seller_call["Destination"]["ToAddresses"] == [SELLER_EMAIL]
        assert seller_call["Source"] == "orders@dev.kernelworx.app"
        assert seller_call["Template"] == "order-confirm-seller-dev"
        assert seller_call["ReplyToAddresses"] == ["orders@dev.kernelworx.app"]

        data = json.loads(seller_call["TemplateData"])
        assert data["orderId"] == ORDER_ID
        assert data["buyerFirstName"] == "Ada"
        assert data["buyerLastName"] == "O'Brien"
        assert data["buyerEmail"] == BUYER_EMAIL
        assert data["buyerPhone"] == BUYER_PHONE
        assert data["totalAmount"] == "10.00"
        assert data["paymentMethod"] == "Cash"
        assert data["lineItems"] == [{"productName": "Cookies", "quantity": 2, "subtotal": "10.00"}]

    def test_account_without_email_skips_seller_with_warning_but_succeeds(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        _seed_account(dynamodb_table, None)

        with caplog.at_level(logging.WARNING):
            result = handle_send_order_emails(make_event(), None)

        assert result["sellerEmailSent"] is False
        assert any("seller email skipped" in record.message for record in caplog.records)

    def test_missing_account_skips_seller_but_succeeds(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        result = handle_send_order_emails(make_event(), None)
        assert result["sellerEmailSent"] is False

    def test_ses_rejection_is_swallowed(
        self, ses_env: None, monkeypatch: pytest.MonkeyPatch, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        monkeypatch.setattr(public_order_emails, "_ses_client", lambda: FakeSes(fail=True))

        result = handle_send_order_emails(make_event(), None)

        assert result["sellerEmailSent"] is False

    def test_seller_email_still_sent_when_buyer_gave_no_email(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {**ORDER, "customerEmail": None}

        result = handle_send_order_emails(make_event(order=order), None)

        assert result["sellerEmailSent"] is True
        assert result["confirmationEmailSent"] is False
        # Exactly one send (seller only).
        assert len(fake_ses.calls) == 1


class TestBuyerEmail:
    def test_buyer_email_carries_the_absolutized_tokenized_receipt_link(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)

        result = handle_send_order_emails(make_event(), None)

        assert result["confirmationEmailSent"] is True
        buyer_call = _buyer_call(fake_ses)
        assert buyer_call["Destination"]["ToAddresses"] == [BUYER_EMAIL]
        assert buyer_call["Template"] == "order-confirm-dev"
        data = json.loads(buyer_call["TemplateData"])
        assert data["receiptUrl"] == f"https://dev.kernelworx.app/r/c1/s1/{RECEIPT_TOKEN}"
        assert data["firstName"] == "Ada"
        assert data["sellerName"] == "Troops R Us"

    def test_no_buyer_email_means_not_offered(self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {key: value for key, value in ORDER.items() if key != "customerEmail"}

        result = handle_send_order_emails(make_event(order=order), None)

        assert result["confirmationEmailSent"] is False
        assert len(fake_ses.calls) == 1  # seller only

    def test_buyer_receipt_link_prefers_the_event_seller_and_campaign_names(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        event = make_event()
        event.pop("sellerName")

        handle_send_order_emails(event, None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["sellerName"] == "Troops R Us"  # falls back to the stored row's denormalized name
        assert data["campaignName"] == "Fall Sale"


class TestEscapingAndLogging:
    def test_handler_pre_escapes_nothing(self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any) -> None:
        """The escaping rule: SES Handlebars auto-escapes raw values exactly once."""
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {**ORDER, "customerFirstName": "O<Brien>"}

        handle_send_order_emails(make_event(order=order), None)

        seller_data = json.loads(_seller_call(fake_ses)["TemplateData"])
        assert seller_data["buyerFirstName"] == "O<Brien>"
        buyer_data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert buyer_data["firstName"] == "O<Brien>"

    def test_no_log_record_contains_token_buyer_email_or_phone(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)

        with caplog.at_level(logging.INFO):
            handle_send_order_emails(make_event(), None)

        rendered = "\n".join(f"{record.message} {record.args}" for record in caplog.records)
        for forbidden in (RECEIPT_TOKEN, BUYER_EMAIL, BUYER_PHONE):
            assert forbidden not in rendered, f"log record leaked {forbidden!r}"


class TestDispatchAndScope:
    def test_dispatcher_routes_the_operation_discriminator(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        result = public_orders_handler(make_event(), None)
        assert result["configured"] is True
        assert result["sellerEmailSent"] is True

    def test_missing_order_id_is_a_structured_error(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        result = handle_send_order_emails(make_event(order={"campaignId": "CAMPAIGN#c1"}), None)
        assert result["__isError"] is True
        assert result["errorCode"] == "INTERNAL_ERROR"

    def test_email_step_reads_only_the_accounts_table(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Behavioral scope: the mailer's DynamoDB footprint is accounts GetItem only."""
        _seed_account(dynamodb_table, SELLER_EMAIL)
        recorder = ApiCallRecorder(monkeypatch)
        recorder.attach()

        handle_send_order_emails(make_event(), None)

        assert recorder.dynamodb_calls == [("GetItem", ACCOUNTS_TABLE)]
        assert recorder.s3_calls == []


class TestEdgeCases:
    def test_already_absolute_receipt_url_is_not_recomposed(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        event = make_event(receiptUrl="https://example.com/r/c1/s1/rtok")

        result = handle_send_order_emails(event, None)

        assert result["confirmationEmailSent"] is True
        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["receiptUrl"] == "https://example.com/r/c1/s1/rtok"

    def test_empty_receipt_url_renders_an_empty_link(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)

        handle_send_order_emails(make_event(receiptUrl=""), None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["receiptUrl"] == ""

    def test_malformed_line_items_are_dropped_from_template_data(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {**ORDER, "lineItems": [{"productName": "Cookies", "quantity": 2, "subtotal": 10.0}, "garbage"]}

        handle_send_order_emails(make_event(order=order), None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["lineItems"] == [{"productName": "Cookies", "quantity": 2, "subtotal": "10.00"}]

    def test_amounts_render_with_two_decimals_like_the_receipt_page(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        order = {
            **ORDER,
            "lineItems": [{"productId": "p1", "productName": "Cookies", "quantity": 2, "subtotal": 12.5}],
            "totalAmount": 12.5,
        }

        handle_send_order_emails(make_event(order=order), None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["totalAmount"] == "12.50"
        assert data["lineItems"] == [{"productName": "Cookies", "quantity": 2, "subtotal": "12.50"}]

    def test_a_non_numeric_amount_is_sent_as_stored_rather_than_failing_the_mail(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        """A stored amount ``Decimal`` cannot read is sent as stored, not as a failure.

        The email is best-effort: a row with a corrupt money value must still
        produce a send rather than raise out of the template data.
        """
        order = {**ORDER, "lineItems": [], "totalAmount": "n/a"}

        handle_send_order_emails(make_event(order=order), None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["totalAmount"] == "n/a"

    def test_a_missing_amount_renders_as_zero_not_the_word_none(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        """FUNC-15: ``None`` money formats as ``0.00``, never as ``$None``.

        ``Decimal(str(None))`` raises, and the as-stored fallback then printed
        the literal text ``None`` into the buyer's email next to the ``$``.
        """
        order = {
            **ORDER,
            "lineItems": [{"productId": "p1", "productName": "Cookies", "quantity": 2, "subtotal": None}],
            "totalAmount": None,
        }

        handle_send_order_emails(make_event(order=order), None)

        data = json.loads(_buyer_call(fake_ses)["TemplateData"])
        assert data["totalAmount"] == "0.00"
        assert data["lineItems"] == [{"productName": "Cookies", "quantity": 2, "subtotal": "0.00"}]

    def test_format_amount_maps_none_to_zero_and_keeps_other_values_verbatim(self) -> None:
        assert public_order_emails._format_amount(None) == "0.00"
        assert public_order_emails._format_amount(12.5) == "12.50"
        assert public_order_emails._format_amount("n/a") == "n/a"

    def test_missing_owner_account_id_skips_the_seller_email(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        event = make_event()
        event.pop("ownerAccountId")

        result = handle_send_order_emails(event, None)

        assert result["sellerEmailSent"] is False
        assert result["confirmationEmailSent"] is True

    def test_non_dict_buyer_address_renders_empty(self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {**ORDER, "customerAddress": "not-a-map"}

        handle_send_order_emails(make_event(order=order), None)

        seller_data = json.loads(_seller_call(fake_ses)["TemplateData"])
        assert seller_data["buyerAddress"] == ""

    def test_structured_buyer_address_joins_all_four_fields(
        self, ses_env: None, fake_ses: FakeSes, dynamodb_table: Any
    ) -> None:
        _seed_account(dynamodb_table, SELLER_EMAIL)
        order = {
            **ORDER,
            "customerAddress": {"street": "1 Main St", "city": "Springfield", "state": "IL", "zipCode": "62701"},
        }

        handle_send_order_emails(make_event(order=order), None)

        seller_data = json.loads(_seller_call(fake_ses)["TemplateData"])
        assert seller_data["buyerAddress"] == "1 Main St, Springfield, IL, 62701"
