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
embedded-campaign mismatch, or an order older than the receipt TTL — raises the
identical ``NOT_FOUND`` with one message, so probing cannot enumerate which
receipt links exist.

Logging hygiene is a contract (§9): the receipt token is a durable capability
with no expiry, so it never enters a log line, and neither does the buyer's
contact data. The unexpected-exception surface is scrubbed the same way the
offer path scrubs the share token, because the decorator's generic line logs
``error=str(e)``.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

try:  # pragma: no cover
    from utils.appsync_types import as_float
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id
    from utils.logging import get_logger, redact_secrets
    from utils.order_keys import build_order_id, parse_order_id
    from utils.tokens import constant_time_token_match
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import as_float
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_campaign_id
    from ..utils.logging import get_logger, redact_secrets
    from ..utils.order_keys import build_order_id, parse_order_id
    from ..utils.tokens import constant_time_token_match

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

# Receipt capability TTL: orders older than this many days are not accessible
# via the public receipt link. Derived from the order's createdAt (stored as
# orderDate ISO string) to avoid a schema migration. A leaked /r/ link grants
# read access only for this window; buyers with recent orders are unaffected.
RECEIPT_TTL_DAYS = 365

# The ORDER#<campaignId>#<suffix> grammar lives in ``utils.order_keys``; anything
# else (a legacy two-part id, a tampered segment) is refused before any datastore
# call.


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
    order_id = build_order_id(campaign_id, arguments.get("orderSuffix"))

    if not campaign_id or not order_id:
        raise _receipt_unavailable()

    return campaign_id, order_id


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
    return bool(constant_time_token_match(stored, submitted))


def _embedded_campaign_matches(order: Dict[str, Any], campaign_id: str) -> bool:
    """Refuse an id whose embedded campaign segment disagrees with the PK.

    A GetItem keyed by the supplied campaignId cannot return another campaign's
    row, so this is defense in depth against a row whose ``orderId`` attribute
    disagrees with its key (a hand-edited or partially migrated item).
    """
    order_id = order.get("orderId")
    embedded = parse_order_id(order_id)
    if embedded is None:
        return False
    return bool(ensure_campaign_id(embedded[0]) == campaign_id)


def _order_within_ttl(order: Dict[str, Any]) -> bool:
    """Check if the order is within the receipt TTL window.

    The order's createdAt is stored as orderDate (ISO 8601 string). Orders
    older than RECEIPT_TTL_DAYS return False and are treated as unavailable
    (NOT_FOUND), so a leaked capability link expires implicitly without a
    schema migration.
    """
    order_date_str = order.get("orderDate")
    if not isinstance(order_date_str, str) or not order_date_str:
        # Missing or malformed date: treat as expired (fail closed)
        return False
    try:
        order_dt = datetime.fromisoformat(order_date_str.replace("Z", "+00:00"))
    except ValueError:
        # Unparseable date: treat as expired (fail closed)
        return False
    if order_dt.tzinfo is None:
        # Stored dates without an offset are UTC by convention (the write
        # path mints them with util.time.nowISO8601); a naive parse must not
        # crash the subtraction against an aware "now".
        order_dt = order_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - order_dt
    return delta.days < RECEIPT_TTL_DAYS


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
        quantity = as_float(item.get("quantity"))
        price = as_float(item.get("pricePerUnit"))
        subtotal = as_float(item.get("subtotal"))
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

    if not _token_matches(order, arguments.get("receiptToken")):
        raise _receipt_unavailable()
    if not _embedded_campaign_matches(order, campaign_id):
        raise _receipt_unavailable()
    if not _order_within_ttl(order):
        raise _receipt_unavailable()

    logger.info("Public order receipt served", order_id=order_id, line_items=len(order.get("lineItems") or []))

    return {
        "sellerName": _text(order.get("sellerName")),
        "orderId": order_id,
        "orderDate": _text(order.get("orderDate")),
        "lineItems": _line_items(order),
        "totalAmount": as_float(order.get("totalAmount")) or 0.0,
        "paymentMethodName": _text(order.get("paymentMethod")),
        "status": _status(order),
        "buyerFirstName": _text(order.get("customerFirstName")),
        "buyerLastName": _text(order.get("customerLastName")),
    }


def run_receipt(event: Dict[str, Any]) -> Dict[str, Any]:
    """Run the receipt read with the receipt token scrubbed from unexpected errors."""
    token = (event.get("arguments") or {}).get("receiptToken")
    try:
        return _build_receipt(event)
    except AppError:
        raise
    except Exception as exc:
        raise redact_secrets(exc, token if isinstance(token, str) else None) from None


@with_error_handling(error_message=RECEIPT_UNAVAILABLE_MESSAGE)
def handle_receipt(event: Dict[str, Any], context: Any) -> Any:
    """Entry point for the ``publicGetOrderReceipt`` field.

    Identity is null under the API-key auth mode and is never read. The shared
    public-orders Lambda routes here on ``info.fieldName``.
    """
    return run_receipt(event)
