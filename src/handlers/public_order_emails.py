"""Best-effort order-confirmation mailer for the publicCreateOrder pipeline.

The email step of the public create pipeline (spec §5.3 step 8,
KW-PUBLIC-ORDERS-SES-1). AppSync invokes the public-orders Lambda with an
explicit ``send_order_emails`` operation discriminator after the order row is
committed; the invoking pipeline function and this handler both swallow every
failure, so an email problem can never fail a durable order.

Contract (spec §3.3/§6):

- Seller email is ALWAYS attempted, to the owner account's ``email`` attribute.
  If the account has no email, the seller send is skipped with a warning and
  the order still succeeds.
- Buyer email is sent only when the buyer provided one, and it carries the
  tokenized receipt link (``SITE_URL`` env + the site-relative path the
  pipeline passes through).
- The three honest ``confirmationEmailSent`` states stay distinguishable:
  not offered (no buyer address), sent, failed. ``configured: false`` means no
  SES env vars — the ephemeral shape — and is deliberately ambiguous with
  "send failed" (spec §6).
- No SES client is constructed until the env contract passes: on ephemeral (and
  any env without the SES module) the env vars are absent entirely, so the
  "no client" branch is taken before any boto3 work. Pinned by unit test.
- Template safety: buyer-supplied strings are passed to SES Handlebars
  auto-escaping RAW — no pre-escaping (double-escaping) anywhere here.
- Logging hygiene (§9): only the order id and booleans ever enter a log line.
  Never the receipt token, the buyer email, or the phone.
"""

import json
import os
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import boto3

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

# The operation discriminator the pipeline function puts in the Invoke payload.
# There is no info.fieldName on that payload, so this string is the route.
SEND_ORDER_EMAILS_OPERATION = "send_order_emails"

# Env contract: all four must be present (and non-empty) for the mailer to be
# "configured". Set together by every environment that instantiates the SES
# module; absent entirely elsewhere (ephemeral, prod until its SES slice).
_ENV_FROM_ADDRESS = "SES_ORDER_FROM_ADDRESS"
_ENV_ORDER_TEMPLATE = "SES_ORDER_TEMPLATE"
_ENV_ORDER_SELLER_TEMPLATE = "SES_ORDER_SELLER_TEMPLATE"
_ENV_SITE_URL = "SITE_URL"

logger = get_logger(__name__)


def _ses_config() -> Optional[Dict[str, str]]:
    """The SES env contract, or None when any part is missing (unconfigured)."""
    from_address = os.environ.get(_ENV_FROM_ADDRESS, "").strip()
    template = os.environ.get(_ENV_ORDER_TEMPLATE, "").strip()
    seller_template = os.environ.get(_ENV_ORDER_SELLER_TEMPLATE, "").strip()
    site_url = os.environ.get(_ENV_SITE_URL, "").strip()
    if not from_address or not template or not seller_template or not site_url:
        return None
    return {
        "from_address": from_address,
        "template": template,
        "seller_template": seller_template,
        "site_url": site_url.rstrip("/"),
    }


def _ses_client() -> Any:
    """Construct the SES client — called only after the env contract passes."""
    return boto3.client("ses")


def _order_id(event: Dict[str, Any]) -> str:
    order = event.get("order")
    order_id = order.get("orderId") if isinstance(order, dict) else None
    if not isinstance(order_id, str) or order_id == "":
        # The pipeline always stashes the stored row; a missing id is a wiring
        # fault, and failing is correct (the pipeline swallows it best-effort).
        raise AppError(ErrorCode.INTERNAL_ERROR, "Order emails requested without an order")
    return order_id


def _absolute_receipt_url(config: Dict[str, str], receipt_url: Any) -> Optional[str]:
    if not isinstance(receipt_url, str) or receipt_url == "":
        return None
    if receipt_url.startswith("http://") or receipt_url.startswith("https://"):
        return receipt_url
    return config["site_url"] + receipt_url


def _format_amount(value: Any) -> str:
    """Money as a two-decimal string, matching the receipt page formatCurrency."""
    try:
        return f"{Decimal(str(value)):.2f}"
    except InvalidOperation, ValueError:
        return str(value)


def _line_item_template_data(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Line items for the templates, exactly as stored (server-priced)."""
    items = order.get("lineItems")
    shaped = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        shaped.append(
            {
                "productName": str(item.get("productName") or ""),
                "quantity": item.get("quantity"),
                "subtotal": _format_amount(item.get("subtotal")),
            }
        )
    return shaped


def _buyer_template_data(order: Dict[str, Any], receipt_url: Optional[str], campaign_name: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "firstName": str(order.get("customerFirstName") or ""),
        "orderId": str(order.get("orderId") or ""),
        "sellerName": str(order.get("sellerName") or ""),
        "campaignName": campaign_name,
        "totalAmount": _format_amount(order.get("totalAmount")),
        "paymentMethod": str(order.get("paymentMethod") or ""),
        "lineItems": _line_item_template_data(order),
        "receiptUrl": receipt_url or "",
    }
    return data


def _seller_email_address(owner_account_id: Any) -> Optional[str]:
    """The owner account's email attribute, or None to skip with a warning."""
    if not isinstance(owner_account_id, str) or owner_account_id == "":
        return None
    account_id = ensure_account_id(owner_account_id)
    response = tables.accounts.get_item(Key={"accountId": account_id})
    account = response.get("Item")
    email = account.get("email") if isinstance(account, dict) else None
    if not isinstance(email, str) or email.strip() == "":
        return None
    return email.strip()


def _send_template(
    client: Any,
    *,
    config: Dict[str, str],
    template: str,
    to_address: str,
    template_data: Dict[str, Any],
) -> None:
    """One templated send. SES Handlebars auto-escapes the values raw."""
    client.send_templated_email(
        Source=config["from_address"],
        Destination={"ToAddresses": [to_address]},
        ReplyToAddresses=[config["from_address"]],
        Template=template,
        TemplateData=json.dumps(template_data),
    )


def _seller_template_data(order: Dict[str, Any], campaign_name: str) -> Dict[str, Any]:
    """Seller-notification template data: order + buyer contact, no receipt link."""
    data = _buyer_template_data(order, None, campaign_name)
    data["buyerFirstName"] = str(order.get("customerFirstName") or "")
    data["buyerLastName"] = str(order.get("customerLastName") or "")
    data["buyerEmail"] = str(order.get("customerEmail") or "")
    data["buyerPhone"] = str(order.get("customerPhone") or "")
    address = order.get("customerAddress")
    if isinstance(address, dict):
        parts = [address.get("street"), address.get("city"), address.get("state"), address.get("zipCode")]
        data["buyerAddress"] = ", ".join(str(part) for part in parts if part)
    else:
        data["buyerAddress"] = ""
    return data


def _send_seller_email(client: Any, config: Dict[str, str], event: Dict[str, Any], order: Dict[str, Any]) -> bool:
    """The seller notification, always attempted (spec §3.3).

    Returns True when handed to SES; False (with a warning) when the owner
    account has no email or the send itself failed — both are best-effort
    outcomes, never order failures.
    """
    order_id = str(order.get("orderId") or "")
    seller_email = _seller_email_address(event.get("ownerAccountId"))
    if seller_email is None:
        logger.warning("Public order seller email skipped: owner account has no email", order_id=order_id)
        return False

    data = _seller_template_data(order, str(event.get("campaignName") or ""))
    try:
        _send_template(
            client, config=config, template=config["seller_template"], to_address=seller_email, template_data=data
        )
    except Exception as exc:  # noqa: BLE001 - best-effort by contract
        logger.warning("Public order seller email failed", order_id=order_id, error_type=type(exc).__name__)
        return False
    logger.info("Public order seller email sent", order_id=order_id)
    return True


def _send_buyer_email(
    client: Any, config: Dict[str, str], event: Dict[str, Any], order: Dict[str, Any]
) -> Tuple[bool, bool]:
    """The buyer confirmation, only when an address was provided.

    Returns (attempted, sent): attempted is False when the buyer gave no email
    ("not offered"); sent is True only when SES accepted the message.
    """
    order_id = str(order.get("orderId") or "")
    buyer_email = order.get("customerEmail")
    if not isinstance(buyer_email, str) or buyer_email.strip() == "":
        return False, False

    receipt_url = _absolute_receipt_url(config, event.get("receiptUrl"))
    data = _buyer_template_data(order, receipt_url, str(event.get("campaignName") or ""))
    try:
        _send_template(
            client, config=config, template=config["template"], to_address=buyer_email.strip(), template_data=data
        )
    except Exception as exc:  # noqa: BLE001 - best-effort by contract
        logger.warning("Public order buyer email failed", order_id=order_id, error_type=type(exc).__name__)
        return True, False
    logger.info("Public order buyer email sent", order_id=order_id)
    return True, True


@with_error_handling(error_message="Order emails could not be sent")
def handle_send_order_emails(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """The pipeline's email step. Best-effort end to end; never raises for mail."""
    raw_order = event.get("order")
    order: Dict[str, Any] = raw_order if isinstance(raw_order, dict) else {}
    order_id = _order_id(event)

    config = _ses_config()
    if config is None:
        # Ephemeral shape (and any env without the SES module): no env vars, so
        # no SES client was ever constructed. Honestly "not configured".
        logger.info("Public order emails not configured (no SES env)", order_id=order_id)
        return {"configured": False, "sellerEmailSent": False, "confirmationEmailSent": False}

    client = _ses_client()
    seller_email_sent = _send_seller_email(client, config, event, order)
    _buyer_attempted, buyer_sent = _send_buyer_email(client, config, event, order)
    result = {
        "configured": True,
        "sellerEmailSent": seller_email_sent,
        "confirmationEmailSent": _buyer_attempted and buyer_sent,
    }
    logger.info(
        "Public order emails handled",
        order_id=order_id,
        seller_email_sent=result["sellerEmailSent"],
        confirmation_email_sent=result["confirmationEmailSent"],
    )
    return result
