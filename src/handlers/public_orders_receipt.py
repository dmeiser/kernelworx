"""Public buyer receipt read: ``publicGetOrderReceipt`` (#679 write slice).

The token-authenticated read behind the buyer's receipt link
``/r/<campaignId>/<orderSuffix>/<receiptToken>``. Like the offer, there is no
caller identity on this auth mode — AppSync admits the request with the public
API key and ``identity`` is null, so the per-order receipt token IS the
authorization and this handler must never call ``get_caller_id``.

The order id arrives SPLIT across two arguments because the raw
``ORDER#<campaignId>#<suffix>`` id contains ``#``, which a browser treats as the
fragment delimiter and ``frontend/src/lib/ids.ts`` cuts at the first ``#``. The
handler re-prefixes explicitly (the Python counterpart of
``lib/order_lookup.js``'s ``parseEmbeddedCampaignId`` contract): PK
``CAMPAIGN#<campaignId>``, SK ``ORDER#<campaignIdBare>#<suffix>``. That
construction is also what retires legacy two-part ``ORDER#<uuid>`` ids: they can
never be addressed this way, and there is deliberately NO GSI fallback — a
capability lookup that falls back to an eventually consistent index would turn
a typo into a disclosure race.

One strongly consistent GetItem answers the read. The seller's display name is
carried on the order row itself (written by the create pipeline), so the receipt
needs no profile read: the token already authorizes this one order, and routing
the display name through the ``profileId-index`` GSI would add a locate, a
consistent read, and a transfer-window failure mode to a path that does not
need them.

Every negative branch — unknown order, an authenticated order with no
``receiptToken`` attribute, a mismatched token, a malformed or legacy id, an
embedded-campaign mismatch — raises the identical ``NOT_FOUND`` with one
message, so probing cannot enumerate which receipt links exist.

Logging hygiene is a contract (§9): the receipt token is a durable capability
with no expiry, so it never enters a log line, and neither does the buyer's
contact data. The unexpected-exception surface is scrubbed the same way the
offer path scrubs the share token, because the decorator's generic line logs
``error=str(e)``.
"""

import hmac
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id, strip_prefix
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_campaign_id, strip_prefix
    from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

# One message for every negative branch. Distinct messages per reason would
# turn the receipt link into an oracle over which order ids exist.
RECEIPT_UNAVAILABLE_MESSAGE = "Receipt not available"

# The field name this handler answers on the shared public-orders Lambda.
RECEIPT_FIELD = "publicGetOrderReceipt"

# Order ids are ORDER#<campaignId>#<suffix>; anything else (a legacy two-part
# id, a tampered segment) is refused before any datastore call.
_ORDER_ID_PARTS = 3


def _receipt_unavailable() -> AppError:
    """Return the single NOT_FOUND every negative branch raises."""
    return AppError(ErrorCode.NOT_FOUND, RECEIPT_UNAVAILABLE_MESSAGE)


def _order_key(arguments: Dict[str, Any]) -> Tuple[str, str]:
    """Rebuild the orders base-table key from the two split URL segments.

    Explicit re-prefixing, never a GSI fallback. A segment that is empty, not a
    string, or carries its own ``#`` is refused here rather than reaching the
    datastore: a caller who concatenates a whole order id into one segment gets
    the same NOT_FOUND as a wrong token.
    """
    campaign_id = ensure_campaign_id(arguments.get("campaignId"))
    order_suffix = arguments.get("orderSuffix")

    if not campaign_id or not isinstance(order_suffix, str) or not order_suffix or "#" in order_suffix:
        raise _receipt_unavailable()

    campaign_bare = strip_prefix(campaign_id)
    if not campaign_bare or "#" in campaign_bare:
        raise _receipt_unavailable()

    return campaign_id, f"ORDER#{campaign_bare}#{order_suffix}"


def _load_order(campaign_id: str, order_id: str) -> Dict[str, Any]:
    """One strongly consistent GetItem; missing or malformed is unavailable.

    ConsistentRead is required: a buyer who follows the emailed link minutes
    after submitting must see the row the create pipeline wrote.
    """
    item = tables.orders.get_item(Key={"campaignId": campaign_id, "orderId": order_id}, ConsistentRead=True).get("Item")
    if not isinstance(item, dict):
        raise _receipt_unavailable()
    return item


def _token_matches(order: Dict[str, Any], submitted: Any) -> bool:
    """Constant-time compare the receipt token against the stored capability.

    An order with no ``receiptToken`` attribute was placed through the
    authenticated API and has no receipt link; it answers the identical
    NOT_FOUND rather than disclosing that the order exists.
    """
    stored = order.get("receiptToken")
    if not isinstance(stored, str) or not stored or not isinstance(submitted, str) or not submitted:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), stored.encode("utf-8"))


def _embedded_campaign_matches(order: Dict[str, Any], campaign_id: str) -> bool:
    """Refuse an id whose embedded campaign segment disagrees with the PK.

    A GetItem keyed by the supplied campaignId cannot return another campaign's
    row, so this is defense in depth against a row whose ``orderId`` attribute
    disagrees with its key (a hand-edited or partially migrated item).
    """
    order_id = order.get("orderId")
    if not isinstance(order_id, str):
        return False
    parts = order_id.split("#")
    if len(parts) != _ORDER_ID_PARTS or not parts[1] or not parts[2]:
        return False
    return bool(ensure_campaign_id(parts[1]) == campaign_id)


def _as_float(value: Any) -> Optional[float]:
    """Coerce a stored DynamoDB number to float, or None when it is not one."""
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _line_items(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The stored line items shaped for ``PublicLineItem``.

    Prices were captured at order time, so they are read back verbatim; an item
    whose numbers are not usable is dropped rather than failing the whole
    receipt, exactly as the offer shapes a malformed product.
    """
    shaped = []
    for item in order.get("lineItems") or []:
        if not isinstance(item, dict):
            continue
        product_id = item.get("productId")
        name = item.get("productName")
        quantity = _as_float(item.get("quantity"))
        price = _as_float(item.get("pricePerUnit"))
        subtotal = _as_float(item.get("subtotal"))
        if not isinstance(product_id, str) or quantity is None or price is None or subtotal is None:
            continue
        shaped.append(
            {
                "productId": product_id,
                "productName": name if isinstance(name, str) else "",
                "quantity": int(quantity),
                "pricePerUnit": price,
                "subtotal": subtotal,
            }
        )
    return shaped


def _text(value: Any) -> str:
    """A non-null GraphQL String from a stored attribute, or empty."""
    return value if isinstance(value, str) else ""


def _status(order: Dict[str, Any]) -> str:
    """The order's payment-verification state.

    Public orders are always written NEW, so a row carrying a receipt token but
    no status predates the attribute and reads NEW — the same back-compat
    default the settings read applies to ``isActive``.
    """
    status = order.get("status")
    return status if status in ("NEW", "CONFIRMED") else "NEW"


def _build_receipt(event: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the receipt view for one ``publicGetOrderReceipt`` request."""
    logger = get_logger(__name__)
    arguments = event.get("arguments") or {}

    campaign_id, order_id = _order_key(arguments)
    order = _load_order(campaign_id, order_id)

    if not _token_matches(order, arguments.get("receiptToken")) or not _embedded_campaign_matches(order, campaign_id):
        raise _receipt_unavailable()

    logger.info("Public order receipt served", order_id=order_id, line_items=len(order.get("lineItems") or []))

    return {
        "sellerName": _text(order.get("sellerName")),
        "orderId": order_id,
        "orderDate": _text(order.get("orderDate")),
        "lineItems": _line_items(order),
        "totalAmount": _as_float(order.get("totalAmount")) or 0.0,
        "paymentMethodName": _text(order.get("paymentMethod")),
        "status": _status(order),
        "buyerFirstName": _text(order.get("customerFirstName")),
        "buyerLastName": _text(order.get("customerLastName")),
    }


def _redact_secrets(exc: Exception, secret: Optional[str]) -> Exception:
    """Strip the receipt token from an unexpected exception's message, in place.

    The decorator's generic path logs ``error=str(e)``. A library echoing a
    request argument would therefore put a durable capability in the log, so the
    scrub happens at this boundary where the secret is known exactly.
    """
    text = str(exc)
    if isinstance(secret, str) and secret and secret in text:
        exc.args = (text.replace(secret, "[redacted]"),)
    return exc


def run_receipt(event: Dict[str, Any]) -> Dict[str, Any]:
    """Run the receipt read with the receipt token scrubbed from unexpected errors."""
    token = (event.get("arguments") or {}).get("receiptToken")
    try:
        return _build_receipt(event)
    except AppError:
        raise
    except Exception as exc:
        raise _redact_secrets(exc, token if isinstance(token, str) else None) from None


@with_error_handling(error_message=RECEIPT_UNAVAILABLE_MESSAGE)
def handle_receipt(event: Dict[str, Any], context: Any) -> Any:
    """Entry point for the ``publicGetOrderReceipt`` field.

    Identity is null under the API-key auth mode and is never read. The shared
    public-orders Lambda routes here on ``info.fieldName``.
    """
    return run_receipt(event)
