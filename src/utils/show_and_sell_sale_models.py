"""Wave 5.2 — pooled Show & Sell sales: persistence, revision history, obligations, planner.

Delivery checklist §4.2.1, §4.2.3, §4.3.3; data model §5.14, §5.15, §6.4, §8.6, §8.6.1,
§8.10; API contract §7.1.

This is the module the three sale mutations write through, and it owns four things that
must not be restated by a caller:

- **The row shapes.** A sale is one row at ``SALE#<saleId>`` holding its line items
  embedded (§6.4), and every correction first writes the full previous revision to
  ``SALE#<saleId>#REVISION#<revision>`` — an immutable child, so a later rename of the
  product or of the payment method can never reach a sale that already happened
  (§5.14, PAY-06). A We Owe obligation is its own row at ``WE_OWE#<weOweId>`` because
  reservation and fulfillment serialize on it separately (§5.15, §8.6).
- **Snapshots, derived server-side.** Product name, unit price, per-line subtotal and
  the sale total are computed from the Unit Campaign's own catalog: the SDL input
  carries no price field at all, so a client cannot offer one (§7.1, SALE-M-01-04), and
  money is integer cents end to end, never a float that has to be re-rounded later.
- **The per-product stock planner** (:func:`plan_sale_stock`, §4.2.3). Immediate
  quantity is the only thing that consumes the event's allocation: it moves that
  product's ``soldQty`` up and ``remainingQty``/``kernelPhysicalQty`` down under one
  ``EVENT_IMMEDIATE_SALE`` movement. We Owe consumes no allocation at all — the stock is
  still the Kernel's until a reservation says otherwise. A correction applies only the
  ``immediateDelta`` between the corrected and the original quantity, never a reversal
  and re-apply of the lines that did not change.
- **The We Owe target arithmetic** (:func:`we_owe_correction_targets`, §8.6.1). An
  original obligation's quantity is never rewritten upward, and no correction may take
  back quantity that has already been fulfilled: ``fulfilledQty <= correctedLineQty <=
  originalQty``, with the residue stated as ``cancelledQty`` and any reservation above
  the corrected remainder released in the same operation.

Two things this module deliberately does not do: it never picks an event state open or
shut (that is :func:`require_sale_state`, which says which states write stock now and
which only record a draft), and it never composes a transaction (that is the resolver's
``WritePlan``; the planner here only answers what one product's change is).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Tuple, cast

from . import inventory_models, show_and_sell_models
from .dynamodb import tables
from .errors import AppError, ErrorCode
from .inventory_models import (
    ACTOR_ACCOUNT_ID_ATTRIBUTE,
    ALLOCATED_QTY,
    ALLOCATION_OPEN,
    FULFILLMENT_ID_ATTRIBUTE,
    KERNEL_PHYSICAL_QTY,
    RELEASED_QTY,
    REMAINING_QTY,
    SOLD_IN_POSSESSION_QTY,
    SOLD_QTY,
    VERSION_ATTRIBUTE,
)
from .mutations import wire_key
from .pagination import query_all_items
from .sale_payment_models import expected_cash_cents
from .show_and_sell_models import (
    CREATED_AT_ATTRIBUTE,
    PRODUCT_IDS_ATTRIBUTE,
    SALE_SK_PREFIX,
    SHOW_AND_SELL_ID_ATTRIBUTE,
    STATUS_ATTRIBUTE,
    UNIT_CAMPAIGN_ID_ATTRIBUTE,
    UNIT_ID_ATTRIBUTE,
    UPDATED_AT_ATTRIBUTE,
    UPDATED_BY_ATTRIBUTE,
    WE_OWE_FULFILLMENT_SK_MARKER,
    WE_OWE_SK_PREFIX,
    WE_OWE_STATUS_CLOSED,
    WE_OWE_STATUS_OPEN,
    event_metadata_key,
    event_we_owe_rows,
    show_and_sell_pk,
    we_owe_fulfillment_rows,
    wire_item,
    wire_item_value,
)
from .unit_models import MAX_ID_LENGTH, normalize_optional_text, normalize_required_text

# --- Entity types and key layout (data model §6.4) ---------------------------------

SALE_ENTITY_TYPE = "ShowAndSellSale"
SALE_REVISION_ENTITY_TYPE = "ShowAndSellSaleRevision"
WE_OWE_ENTITY_TYPE = "WeOweObligation"

SALE_STATUS_ACTIVE = "ACTIVE"
SALE_STATUS_VOIDED = "VOIDED"
SALE_STATUSES: frozenset[str] = frozenset({SALE_STATUS_ACTIVE, SALE_STATUS_VOIDED})

WE_OWE_CLOSE_FULFILLED = "FULFILLED"
WE_OWE_CLOSE_CANCELLED = "CANCELLED"
WE_OWE_CLOSE_REASONS: frozenset[str] = frozenset({WE_OWE_CLOSE_FULFILLED, WE_OWE_CLOSE_CANCELLED})

#: An append-only fulfillment record (§5.15). It has no ``version`` attribute and is never
#: rewritten: a mistake is corrected by a later record, never by editing history.
WE_OWE_FULFILLMENT_ENTITY_TYPE = "WeOweFulfillment"

#: Which stock source one fulfillment draws on (§5.15, OWE-07). ``KERNEL_STOCK`` moves
#: Kernel physical on hand and sold-product-in-our-possession together; ``EXTERNAL_COUNCIL``
#: closes the supplied quantity and changes no Unit stock at all.
WE_OWE_SOURCE_KERNEL = "KERNEL_STOCK"
WE_OWE_SOURCE_EXTERNAL = "EXTERNAL_COUNCIL"
WE_OWE_SOURCES: frozenset[str] = frozenset({WE_OWE_SOURCE_KERNEL, WE_OWE_SOURCE_EXTERNAL})

# --- Attribute names (§5.14, §5.15) ------------------------------------------------

SALE_ID_ATTRIBUTE = "saleId"
SALE_AT_ATTRIBUTE = "saleAt"
ENTERED_BY_ATTRIBUTE = "enteredByAccountId"
BUYER_NAME_ATTRIBUTE = "buyerName"
BUYER_PHONE_ATTRIBUTE = "buyerPhone"
BUYER_EMAIL_ATTRIBUTE = "buyerEmail"
LINE_ITEMS_ATTRIBUTE = "lineItems"
TOTAL_CENTS_ATTRIBUTE = "totalCents"
PAYMENT_SNAPSHOT_ATTRIBUTE = "paymentMethodSnapshot"
REVISION_ATTRIBUTE = "revision"
VOIDED_BY_ATTRIBUTE = "voidedByAccountId"
VOIDED_AT_ATTRIBUTE = "voidedAt"
IDEMPOTENCY_KEY_ATTRIBUTE = "idempotencyKey"

LINE_ITEM_ID_ATTRIBUTE = "lineItemId"
PRODUCT_ID_ATTRIBUTE = "productId"
PRODUCT_NAME_SNAPSHOT_ATTRIBUTE = "productNameSnapshot"
UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE = "unitPriceCentsSnapshot"
IMMEDIATE_QTY_ATTRIBUTE = "immediateQty"
WE_OWE_QTY_ATTRIBUTE = "weOweQty"
SUBTOTAL_CENTS_ATTRIBUTE = "subtotalCents"

WE_OWE_ID_ATTRIBUTE = "weOweId"
SALE_ID_LINK_ATTRIBUTE = "saleId"
ORIGINAL_QTY_ATTRIBUTE = "originalQty"
FULFILLED_QTY_ATTRIBUTE = "fulfilledQty"
CANCELLED_QTY_ATTRIBUTE = "cancelledQty"
RESERVED_QTY_ATTRIBUTE = "reservedQty"
#: The same attribute name the inventory allocation rows use (§5.11, §5.15), so a
#: report that reads both speaks one vocabulary; spelled as a constant here because
#: this module's reads name it the way the others do.
REMAINING_QTY_ATTRIBUTE = REMAINING_QTY
UNCOVERED_QTY_ATTRIBUTE = "uncoveredQty"
VALUE_CENTS_SNAPSHOT_ATTRIBUTE = "valueCentsSnapshot"
CLOSE_REASON_ATTRIBUTE = "closeReason"
CLOSED_AT_ATTRIBUTE = "closedAt"

# --- Fulfillment record attributes (§5.15) -----------------------------------------

#: The quantity one fulfillment record carries: a positive count, never a signed delta,
#: because a correction to a fulfillment is a later record rather than a negative one.
FULFILLMENT_QTY_ATTRIBUTE = "quantity"
FULFILLMENT_SOURCE_ATTRIBUTE = "source"
#: The ``InventoryMovement`` a KERNEL_STOCK fulfillment consumed, named on the record so
#: the audit trail pairs the buyer's delivery with the stock that moved (§5.15). It is
#: absent for EXTERNAL_COUNCIL, where no Unit stock moved.
FULFILLMENT_MOVEMENT_ATTRIBUTE = "inventoryMovementId"

#: The ``setWeOweReservation`` argument (§7.2): a target quantity, not a delta, so a
#: caller that read ``reservedQty: 2`` and wants one held states ``1`` and the write says
#: what the obligation holds afterwards rather than what it meant to add.
TARGET_RESERVED_QTY_ARGUMENT = "targetReservedQty"

CORRECTED_BY_ATTRIBUTE = "correctedByAccountId"
CORRECTED_AT_ATTRIBUTE = "correctedAt"
REASON_ATTRIBUTE = "reason"

# --- Limits ------------------------------------------------------------------------

# A buyer name is what a Scout hands across the table with cash for something the Unit
# does not have on the shelf tonight: it is the only identity a We Owe obligation carries
# (§5.15 has no Account), so it has to be long enough for a real name and short enough to
# sit beside the line items it belongs to.
MAX_MONEY_CENTS = 100_000_000
#: API contract §3.4: "Buyer name: 1-200 trimmed characters when We Owe is present".
MAX_BUYER_NAME_LENGTH = 200
MAX_BUYER_PHONE_LENGTH = 40
MAX_BUYER_EMAIL_LENGTH = 254
MAX_SALE_REASON_LENGTH = 500

#: A cent ceiling high enough that no real sale reaches it and low enough that a
#: garbage value is a refusal rather than an arithmetic overflow downstream. Money is
#: stored as an integer number of cents everywhere in Show & Sell, because the whole
#: pool is split to the cent and a float total cannot be re-split exactly.

# --- Errors ------------------------------------------------------------------------

INSUFFICIENT_EVENT_STOCK = "INSUFFICIENT_EVENT_STOCK"
NO_EVENT_ALLOCATION = "NO_EVENT_ALLOCATION"
FULFILLED_WE_OWE_PROTECTED = "FULFILLED_WE_OWE_PROTECTED"
LINE_ITEM_NOT_FOUND = "LINE_ITEM_NOT_FOUND"
DUPLICATE_LINE_ITEM = "DUPLICATE_LINE_ITEM"
SALE_ALREADY_VOIDED = "SALE_ALREADY_VOIDED"
#: An event that never enabled We Owe still refuses an owed quantity (§7.1).
WE_OWE_NOT_ENABLED = "WE_OWE_NOT_ENABLED"

# --- We Owe reservation and fulfillment refusals (§4.4.2, §4.4.3, §10) -------------

#: A reservation or fulfillment against an obligation that has already closed: there is
#: nothing left owed and nothing left held, so a further write would invent quantity.
WE_OWE_OBLIGATION_CLOSED = "WE_OWE_OBLIGATION_CLOSED"
#: A reservation target above what the obligation still owes.
RESERVATION_ABOVE_REMAINING = "RESERVATION_ABOVE_REMAINING"
#: A reservation increase above the campaign's unassigned stock (OWE-04: reserved stock
#: "leaves sellable/unassigned stock and cannot be used elsewhere").
RESERVATION_ABOVE_UNASSIGNED = "RESERVATION_ABOVE_UNASSIGNED"
#: A fulfillment above what the obligation still owes.
FULFILLMENT_ABOVE_REMAINING = "FULFILLMENT_ABOVE_REMAINING"
#: A KERNEL_STOCK fulfillment above the quantity stock is held against (OWE-07).
FULFILLMENT_ABOVE_RESERVED = "FULFILLMENT_ABOVE_RESERVED"
#: An EXTERNAL_COUNCIL fulfillment over a portion that Kernel stock is promised to. The
#: Council cannot supply a unit the Kernel has already set aside for this same buyer, so
#: the caller releases the reservation first (OWE-07).
FULFILLMENT_ABOVE_UNCOVERED = "FULFILLMENT_ABOVE_UNCOVERED"
#: A reservation or fulfillment whose ``expectedVersion`` is not the obligation's version.
WE_OWE_VERSION_STALE = "WE_OWE_VERSION_STALE"

SALE_STATE_LIVE = "LIVE"
SALE_STATE_DRAFT = "DRAFT"


def _invalid(field: str, rule: str) -> AppError:
    """One INVALID_INPUT rejection, spelled the same way everywhere in this module."""
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


def _refuse(code: str, message: str, **details: Any) -> NoReturn:
    """A refusal carrying its subcode.

    ``AppError.details`` does not survive the resolver boundary, so a refusal that a
    browser has to act on also says what it is in its sentence; the subcode is what the
    unit tests and any future allowlisted forwarding read.
    """
    raise AppError(ErrorCode.CONFLICT, message, details={"subcode": code, **details})


# --- Identity ----------------------------------------------------------------------


def new_sale_id() -> str:
    """A stable sale identity, generated before the write (§5.14).

    A UUID rather than a counter: the id is the suffix of a sort key inside the event's
    partition, and two admins taking a sale at the same table must not collide on one
    the other guessed.
    """
    return str(uuid.uuid4())


def new_line_item_id() -> str:
    """A stable line identity (§5.14, §7.1).

    The line id is what a correction addresses, so it is minted by the server at the
    first entry and never re-derived: a correction that re-minted it would turn an edit
    of an existing line into a void plus a new line, and the obligation linked to the
    original line would lose the identity the correction has to reconcile.
    """
    return str(uuid.uuid4())


def new_we_owe_id() -> str:
    """A stable obligation identity, generated before the write (§5.15)."""
    return str(uuid.uuid4())


def new_fulfillment_id() -> str:
    """A stable fulfillment identity, minted by the server at write time (§5.15).

    The caller never names a fulfillment: the SDL input carries no such field, because an
    id the browser minted would make "did this click already record a fulfillment" a
    question about a client's memory rather than about the rows the write committed. The
    id is also the link the ``WE_OWE_FULFILL`` movement names, so the record and the
    stock that moved share one identity (§5.15).
    """
    return str(uuid.uuid4())


def normalize_fulfillment_id(value: Any, field: str = FULFILLMENT_ID_ATTRIBUTE) -> str:
    """Validate a ``fulfillmentId``, which sits at the end of a composite sort key."""
    return normalize_sale_key_id(value, field)


def normalize_sale_key_id(value: Any, field: str) -> str:
    """Validate an id that sits inside one of this module's composite sort keys.

    Same rule as the inventory surface: an id may contain ``#`` (a catalog product id is
    ``<catalogId>#prod-N``), but no segment may be empty, because the sort-key markers
    are ``#``-delimited and an empty segment lets two rows collide on one key.
    """
    text = normalize_required_text(value, field, MAX_ID_LENGTH)
    if "#" in text and (text.startswith("#") or text.endswith("#") or "##" in text):
        raise _invalid(field, "must not contain an empty # segment")
    return text


def normalize_sale_id(value: Any, field: str = SALE_ID_ATTRIBUTE) -> str:
    """Validate a ``saleId``."""
    return normalize_sale_key_id(value, field)


def normalize_we_owe_id(value: Any, field: str = WE_OWE_ID_ATTRIBUTE) -> str:
    """Validate a ``weOweId``."""
    return normalize_sale_key_id(value, field)


def normalize_line_item_id(value: Any, field: str = LINE_ITEM_ID_ATTRIBUTE) -> str:
    """Validate a ``lineItemId``."""
    return normalize_sale_key_id(value, field)


def normalize_sale_at(value: Any, field: str = SALE_AT_ATTRIBUTE) -> str:
    """Validate the actual sale time (§5.14: back-dated paper entry included)."""
    return show_and_sell_models.normalize_moment(value, field)


def normalize_buyer_name(value: Any, field: str = BUYER_NAME_ATTRIBUTE) -> Optional[str]:
    """Trim the optional buyer name; it is required only when a line creates We Owe."""
    return normalize_optional_text(value, field, MAX_BUYER_NAME_LENGTH)


def normalize_buyer_name_filter(value: Any, field: str) -> str:
    """A buyer-name filter, capped by the same ceiling as the stored name (§4.4.4).

    An empty filter is a refusal rather than "match everything": a caller that sent
    ``buyerName: ""`` meant to ask something, and answering it as the unfiltered list is how
    a filter that quietly does nothing survives review. The name is the obligation's own
    snapshot, so a filter matches what a Unit typed at the table — there is no Account to
    resolve it against, and no contact detail to match on (§5.15).
    """
    return normalize_required_text(value, field, MAX_BUYER_NAME_LENGTH)


def normalize_buyer_phone(value: Any, field: str = BUYER_PHONE_ATTRIBUTE) -> Optional[str]:
    """Trim the optional buyer phone. Never validated as a phone number: it is contact detail."""
    return normalize_optional_text(value, field, MAX_BUYER_PHONE_LENGTH)


def normalize_buyer_email(value: Any, field: str = BUYER_EMAIL_ATTRIBUTE) -> Optional[str]:
    """Trim the optional buyer email; same posture as the phone — contact detail, not an identity."""
    return normalize_optional_text(value, field, MAX_BUYER_EMAIL_LENGTH)


def normalize_sale_reason(value: Any, field: str = REASON_ATTRIBUTE) -> str:
    """Require the correction or void reason (§7.1: every sale mutation names why)."""
    return normalize_required_text(value, field, MAX_SALE_REASON_LENGTH)


def normalize_sale_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate a ``SaleStatus``."""
    if not isinstance(value, str) or value not in SALE_STATUSES:
        raise _invalid(field, f"must be one of {', '.join(sorted(SALE_STATUSES))}")
    return value


def normalize_we_owe_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate a We Owe report status (§5.15: OPEN/CLOSED only)."""
    if not isinstance(value, str) or value not in {WE_OWE_STATUS_OPEN, WE_OWE_STATUS_CLOSED}:
        raise _invalid(field, f"must be one of {WE_OWE_STATUS_OPEN}, {WE_OWE_STATUS_CLOSED}")
    return value


def normalize_we_owe_close_reason(value: Any, field: str = CLOSE_REASON_ATTRIBUTE) -> str:
    """Validate a We Owe close reason — an audit detail, never a third report status."""
    if not isinstance(value, str) or value not in WE_OWE_CLOSE_REASONS:
        raise _invalid(field, f"must be one of {', '.join(sorted(WE_OWE_CLOSE_REASONS))}")
    return value


def normalize_we_owe_source(value: Any, field: str = FULFILLMENT_SOURCE_ATTRIBUTE) -> str:
    """Which stock source a fulfillment draws on (§5.15, OWE-07).

    Two sources and no third: ``KERNEL_STOCK`` is the Unit's own shelf and moves stock,
    ``EXTERNAL_COUNCIL`` is a Council that supplied the quantity and moves nothing.
    """
    if not isinstance(value, str) or value not in WE_OWE_SOURCES:
        raise _invalid(field, f"must be one of {', '.join(sorted(WE_OWE_SOURCES))}")
    return value


def normalize_reservation_target(value: Any, field: str = TARGET_RESERVED_QTY_ARGUMENT) -> int:
    """A reservation target: a count that may be zero, because zero is how a Unit releases stock."""
    return normalize_quantity(value, field)


def normalize_fulfillment_qty(value: Any, field: str = FULFILLMENT_QTY_ATTRIBUTE) -> int:
    """One fulfillment's quantity (§5.15: a positive integer).

    Zero is refused rather than treated as a no-op: a record of delivering nothing would
    sit in the audit history beside the deliveries that happened, and the obligation's
    version would move for a write that changed no quantity.
    """
    return inventory_models.normalize_quantity(value, field, minimum=1)


def normalize_quantity(value: Any, field: str) -> int:
    """A non-negative quantity, read the way the inventory surface reads one."""
    return inventory_models.normalize_quantity(value, field)


def normalize_money_cents(value: Any, field: str) -> int:
    """A non-negative integer cent amount (§5.14: money is MoneyCents, never a float).

    The ceiling is checked before the quantity delegate reads the value, because that
    delegate caps at ``MAX_QUANTITY`` and would answer first — the money bound is the
    number a reader of this module should see, and a guard that can never fire is not a
    guard.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value > MAX_MONEY_CENTS:
        raise _invalid(field, f"must be at most {MAX_MONEY_CENTS} cents")
    return inventory_models.normalize_quantity(value, field)


def unit_price_cents(price: Any) -> int:
    """The catalog's dollar price of one product, in cents.

    The catalog stores a Dollar float (``Product.price``), and this is the one place it
    becomes money: ``Decimal(str(...))`` rather than ``Decimal(float)`` so a price typed
    as ``19.99`` becomes 1999 rather than the float's nearest representable neighbour,
    and ``ROUND_HALF_UP`` because that is how a sale is charged at the table. Every
    number downstream — line subtotal, sale total, whole pool, credit split — is then an
    integer count of cents, which is the only way the split can be exact (§7).
    """
    if isinstance(price, bool) or not isinstance(price, (int, float, Decimal, str)):
        raise _invalid("price", "must be a number")
    try:
        amount = (Decimal(str(price)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation, ValueError, ArithmeticError:
        raise _invalid("price", "must be a number") from None
    if amount < 0:
        raise _invalid("price", "must not be negative")
    return int(amount)


# --- Key builders (§6.4) -----------------------------------------------------------


def sale_sk(sale_id: str) -> str:
    """A sale's sort key inside its event's partition."""
    return f"{SALE_SK_PREFIX}#{sale_id}"


def sale_key(show_and_sell_id: str, sale_id: str) -> Dict[str, str]:
    """The current-revision sale row's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": sale_sk(sale_id)}


def sale_revision_sk(sale_id: str, revision: int) -> str:
    """One immutable prior revision's sort key (§6.4).

    The sale id leads, so the current row and every revision of it sit in one sort-key
    range and one query reads the whole history of one sale.
    """
    return f"{sale_sk(sale_id)}#REVISION#{int(revision)}"


def sale_revision_key(show_and_sell_id: str, sale_id: str, revision: int) -> Dict[str, str]:
    """One immutable prior revision's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": sale_revision_sk(sale_id, revision)}


def we_owe_sk(we_owe_id: str) -> str:
    """An obligation's sort key inside its event's partition."""
    return f"{WE_OWE_SK_PREFIX}#{we_owe_id}"


def we_owe_key(show_and_sell_id: str, we_owe_id: str) -> Dict[str, str]:
    """The obligation row's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": we_owe_sk(we_owe_id)}


def we_owe_fulfillment_sk(we_owe_id: str, fulfillment_id: str) -> str:
    """One fulfillment's sort key, under its obligation (§6.4).

    The parent id leads, so one range read answers "what has been delivered on this
    obligation" without touching any other obligation's history, and the parent row
    itself sits outside the range.
    """
    return f"{we_owe_sk(we_owe_id)}{WE_OWE_FULFILLMENT_SK_MARKER}{fulfillment_id}"


def we_owe_fulfillment_key(show_and_sell_id: str, we_owe_id: str, fulfillment_id: str) -> Dict[str, str]:
    """One fulfillment row's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": we_owe_fulfillment_sk(we_owe_id, fulfillment_id)}


# --- Reads -------------------------------------------------------------------------


def read_sale(show_and_sell_id: str, sale_id: str) -> Optional[Dict[str, Any]]:
    """One sale's current revision, read consistently from the base table.

    The event partition is the address, which is what makes a ``saleId`` from another
    event simply absent here rather than a cross-tenant read (§8.9's scope rule, AUTH-U).
    A prior-revision row is not this row: its sort key carries the ``#REVISION#`` marker,
    so an exact key read cannot answer history for a caller that asked for the sale.
    """
    response = tables.show_and_sells.get_item(Key=sale_key(show_and_sell_id, sale_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, Mapping) else None


def load_sale_or_not_found(show_and_sell_id: str, sale_id: str) -> Dict[str, Any]:
    """The sale a correction addresses, or ``NOT_FOUND``; never an existence oracle."""
    row = read_sale(show_and_sell_id, sale_id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell sale not found")
    return row


def read_we_owe(show_and_sell_id: str, we_owe_id: str) -> Optional[Dict[str, Any]]:
    """One obligation row, read consistently."""
    response = tables.show_and_sells.get_item(Key=we_owe_key(show_and_sell_id, we_owe_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, Mapping) else None


def load_we_owe_or_internal(show_and_sell_id: str, we_owe_id: str) -> Dict[str, Any]:
    """The obligation a reservation or fulfillment committed, or an internal fault.

    A replay loader cannot answer with a fresh write, so a missing obligation is not a caller's
    ``NOT_FOUND`` — the marker and the obligation commit in one transaction, so an absence means
    the rows no longer match the answer the first attempt was authorized to give.
    """
    row = read_we_owe(show_and_sell_id, we_owe_id)
    if row is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "the obligation could not be loaded")
    return row


def we_owe_row_by_id(we_owe_id: str) -> Optional[Dict[str, Any]]:
    """One obligation addressed by its own id, through ``weOweId-index`` (§6.4).

    The direct read has no event to address the partition by, which is what makes this the
    one obligation read that has to disambiguate the row from its own history: the index is
    keyed on ``weOweId``, a value the append-only fulfillment records carry as their parent
    link, so the marker is what picks the aggregate out of the range.
    """
    rows = [
        row
        for row in query_all_items(
            tables.show_and_sells,
            {
                "IndexName": "weOweId-index",
                "KeyConditionExpression": "#weOweId = :weOweId",
                "ExpressionAttributeNames": {"#weOweId": WE_OWE_ID_ATTRIBUTE},
                "ExpressionAttributeValues": {":weOweId": we_owe_id},
            },
        )
        if WE_OWE_FULFILLMENT_SK_MARKER not in str(row.get("sk") or "")
    ]
    return dict(rows[0]) if len(rows) == 1 else None


def load_we_owe_by_id_or_not_found(we_owe_id: str) -> Dict[str, Any]:
    """The obligation its caller addressed, or ``NOT_FOUND``.

    ``NOT_FOUND`` rather than an existence answer about another Unit's obligation: the
    tenant check happens on the campaign the row names, and an unknown id and a foreign id
    are the same reply (AUTH-U).
    """
    row = we_owe_row_by_id(we_owe_id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "We Owe obligation not found")
    return row


def campaign_we_owe_rows(unit_campaign_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """One Unit Campaign's obligations, through ``unitCampaignId-status-index`` (§6.4).

    The index is what answers "what does this campaign still owe" across every event at
    once, which no single event partition can: the obligations of a Unit Campaign are the
    list its table reads (§7.2). Two reads when the caller wants both states, because the
    index's range key is the state and an absent filter means both of them. Fulfillment
    records carry no ``status``, so they are never in this index at all.

    Ordered the way a table reads it: what is still owed before what is closed, newest
    first inside each state, and ``weOweId`` as the tiebreak so two pages of one read never
    disagree about which of two same-instant obligations came first.
    """
    statuses = [status] if status is not None else [WE_OWE_STATUS_OPEN, WE_OWE_STATUS_CLOSED]
    rows: List[Dict[str, Any]] = []
    for state in statuses:
        rows.extend(
            query_all_items(
                tables.show_and_sells,
                {
                    "IndexName": "unitCampaignId-status-index",
                    "KeyConditionExpression": "#unitCampaignId = :unitCampaignId AND #status = :status",
                    "ExpressionAttributeNames": {
                        "#unitCampaignId": UNIT_CAMPAIGN_ID_ATTRIBUTE,
                        "#status": STATUS_ATTRIBUTE,
                    },
                    "ExpressionAttributeValues": {":unitCampaignId": unit_campaign_id, ":status": state},
                },
            )
        )
    newest_first = sorted(
        rows,
        key=lambda row: (str(row.get(CREATED_AT_ATTRIBUTE) or ""), str(row.get(WE_OWE_ID_ATTRIBUTE) or "")),
        reverse=True,
    )
    # A second, stable sort on the state is what keeps the newest-first order inside each
    # state: OPEN before CLOSED is the order a table wants, and it says nothing about which
    # of two open obligations was written first.
    return sorted(newest_first, key=lambda row: 0 if str(row.get(STATUS_ATTRIBUTE) or "") == WE_OWE_STATUS_OPEN else 1)


def we_owe_fulfillment_history(show_and_sell_id: str, we_owe_id: str) -> List[Dict[str, Any]]:
    """One obligation's fulfillment records, oldest first (§5.15).

    The storage range orders by id, not by time, because §6.4's sort key is
    ``WE_OWE#<weOweId>#FULFILLMENT#<fulfillmentId>``; the history a reader wants is the
    sequence deliveries happened in, so the moment is the sort here and the id breaks a tie
    between two records written in the same instant.
    """
    rows = we_owe_fulfillment_rows(show_and_sell_id, we_owe_id)
    return sorted(
        rows,
        key=lambda row: (str(row.get(CREATED_AT_ATTRIBUTE) or ""), str(row.get(FULFILLMENT_ID_ATTRIBUTE) or "")),
    )


def sale_obligations(show_and_sell_id: str, sale_id: str) -> List[Dict[str, Any]]:
    """This sale's obligations, by line identity (§8.6.1 step 3 reads them this way).

    One partition query rather than a GSI: a correction is deciding about quantities a
    reservation may be moving at the same moment, so it has to see the rows as they are,
    and the obligation's ``lineItemId`` is what pairs each one with the line it came from.
    """
    rows = [row for row in event_we_owe_rows(show_and_sell_id) if str(row.get(SALE_ID_ATTRIBUTE) or "") == sale_id]
    return sorted(rows, key=lambda row: str(row.get(LINE_ITEM_ID_ATTRIBUTE) or ""))


def sale_revision_rows(show_and_sell_id: str, sale_id: str) -> List[Dict[str, Any]]:
    """One sale's immutable prior revisions, oldest first."""
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {
                ":pk": show_and_sell_pk(show_and_sell_id),
                ":prefix": f"{sale_sk(sale_id)}#",
            },
            "ConsistentRead": True,
        },
    )
    return sorted(rows, key=lambda row: int(row.get(REVISION_ATTRIBUTE) or 0))


def read_sale_revision(show_and_sell_id: str, sale_id: str, revision: int) -> Optional[Dict[str, Any]]:
    """One archived revision by number, or ``None`` when the sale never had one.

    A sale's revision counter is bumped by exactly one for every correction and every void,
    each of which archives the revision it replaced, so "the revision this write replaced"
    is always ``revision - 1`` and one exact key read answers it. A create is at revision 1
    and has no such row, which is why the caller asks only above 1.

    The read is consistent because of WHEN it happens: the answer builder calls this right
    after the transaction that wrote the revision child committed, and an eventually
    consistent read of a row written milliseconds ago can answer absent. That would not be
    a cosmetic gap — ``priorRevision`` would come back null and the products only the
    archived revision names would drop out of the allocation and position answer, and the
    idempotency marker would then replay that hollowed-out payload for seven days (§8).
    """
    response = tables.show_and_sells.get_item(
        Key=sale_revision_key(show_and_sell_id, sale_id, revision), ConsistentRead=True
    )
    item = response.get("Item")
    return dict(item) if isinstance(item, Mapping) else None


def event_sale_rows(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """This event's sales at their current revisions (revision children excluded).

    The partition query names every ``SALE#`` row, current and archived; the entity-type
    filter is what keeps the archived revision children out of an answer about the
    sales themselves. One consistent read, because a feasibility count decided on a
    lagging index could refuse — or allow — a sale against a set that is not the one
    re-finalization will walk.
    """
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": f"{SALE_SK_PREFIX}#"},
            "ConsistentRead": True,
        },
    )
    return [dict(row) for row in rows if row.get("entityType") == SALE_ENTITY_TYPE]


# --- Line inputs and snapshots (§7.1) ----------------------------------------------


def _line_quantities(raw: Mapping[str, Any], index: int) -> Tuple[int, int]:
    """One line's immediate and We Owe quantities, validated (§7.1's three rules)."""
    immediate = normalize_quantity(raw.get(IMMEDIATE_QTY_ATTRIBUTE), f"lineItems[{index}].{IMMEDIATE_QTY_ATTRIBUTE}")
    we_owe = normalize_quantity(raw.get(WE_OWE_QTY_ATTRIBUTE), f"lineItems[{index}].{WE_OWE_QTY_ATTRIBUTE}")
    if immediate + we_owe < 1:
        raise _invalid(
            f"lineItems[{index}]",
            "must ask for at least one item: immediateQty + weOweQty must be greater than zero",
        )
    return immediate, we_owe


def normalize_sale_lines(value: Any) -> List[Dict[str, Any]]:
    """Validate ``lineItems`` for a new sale: product, immediate quantity, We Owe quantity.

    There is deliberately no price, name, subtotal or total in this input, and no
    quantity the campaign holds: every one of those is a fact the server reads (§7.1),
    so a caller that sends one is refused by the SDL rather than overridden here.
    """
    return _normalize_lines(value, allow_line_ids=False)


def normalize_correction_lines(value: Any) -> List[Dict[str, Any]]:
    """Validate ``lineItems`` for a correction, where an existing line is named by id.

    A line with no ``lineItemId`` is supplemental (§7.1); a line that names one is that
    line's new whole quantity, never an amount to add. Duplicates are refused rather than
    resolved: two rows claiming to be the same line make "what is this line's quantity
    now" unanswerable, and silently taking the last would decide the caller's arithmetic
    for them.
    """
    return _normalize_lines(value, allow_line_ids=True)


def _normalize_lines(value: Any, *, allow_line_ids: bool) -> List[Dict[str, Any]]:
    """One pass over the shared validation, with the correction's id set when asked."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise _invalid("lineItems", "must be a non-empty list of sale lines")
    lines: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise _invalid(f"lineItems[{index}]", "must be an object")
        immediate, we_owe = _line_quantities(raw, index)
        line = {
            PRODUCT_ID_ATTRIBUTE: inventory_models.normalize_inventory_id(
                raw.get(PRODUCT_ID_ATTRIBUTE), f"lineItems[{index}].{PRODUCT_ID_ATTRIBUTE}"
            ),
            IMMEDIATE_QTY_ATTRIBUTE: immediate,
            WE_OWE_QTY_ATTRIBUTE: we_owe,
        }
        raw_id = raw.get(LINE_ITEM_ID_ATTRIBUTE)
        if allow_line_ids and raw_id is not None:
            line_item_id = normalize_line_item_id(raw_id, f"lineItems[{index}].{LINE_ITEM_ID_ATTRIBUTE}")
            if line_item_id in seen:
                raise AppError(
                    ErrorCode.INVALID_INPUT,
                    f"lineItems carries {LINE_ITEM_ID_ATTRIBUTE} {line_item_id} twice; a correction says each line's whole quantity once",
                    details={"subcode": DUPLICATE_LINE_ITEM, LINE_ITEM_ID_ATTRIBUTE: line_item_id},
                )
            seen.add(line_item_id)
            line[LINE_ITEM_ID_ATTRIBUTE] = line_item_id
        lines.append(line)
    return lines


def catalog_price_table(products: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The catalog's products as ``productId -> {name, cents}`` — the only price source.

    The caller reads the campaign's own catalog row, so this table is the allowlist too:
    a product the campaign's catalog does not offer has no entry, and
    :func:`snapshot_line_items` refuses it.
    """
    return {
        str(product["productId"]): {
            PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: str(product["productName"]),
            UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: unit_price_cents(product["price"]),
        }
        for product in products
        if isinstance(product, Mapping) and product.get("productId")
    }


def build_sale_line_item(
    *,
    line_item_id: str,
    product_id: str,
    product_name_snapshot: str,
    unit_price_cents_snapshot: int,
    immediate_qty: int,
    we_owe_qty: int,
) -> Dict[str, Any]:
    """One line item, with its subtotal derived rather than supplied."""
    item = {
        LINE_ITEM_ID_ATTRIBUTE: normalize_line_item_id(line_item_id),
        PRODUCT_ID_ATTRIBUTE: inventory_models.normalize_inventory_id(product_id, PRODUCT_ID_ATTRIBUTE),
        PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: normalize_required_text(
            product_name_snapshot, PRODUCT_NAME_SNAPSHOT_ATTRIBUTE, MAX_ID_LENGTH
        ),
        UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: normalize_money_cents(
            unit_price_cents_snapshot, UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE
        ),
        IMMEDIATE_QTY_ATTRIBUTE: normalize_quantity(immediate_qty, IMMEDIATE_QTY_ATTRIBUTE),
        WE_OWE_QTY_ATTRIBUTE: normalize_quantity(we_owe_qty, WE_OWE_QTY_ATTRIBUTE),
    }
    item[SUBTOTAL_CENTS_ATTRIBUTE] = line_subtotal_cents(item)
    return item


def snapshot_line_items(
    lines: Sequence[Mapping[str, Any]], prices: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Turn validated line inputs into embedded line items with server-derived snapshots.

    Name and price come from the catalog table the campaign points at, and each line is
    minted a stable ``lineItemId`` here — this is the only place a line identity is
    created, which is what lets a correction address it later (§5.14). A product the
    campaign's catalog does not offer is refused with the same sentence a receipt uses,
    because a sale of a product nobody sells is the same accounting hole.
    """
    snapshot: List[Dict[str, Any]] = []
    for line in lines:
        product_id = str(line[PRODUCT_ID_ATTRIBUTE])
        offered = prices.get(product_id)
        if offered is None:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                f"{PRODUCT_ID_ATTRIBUTE} {product_id} is not a product of this campaign's catalog",
            )
        snapshot.append(
            build_sale_line_item(
                line_item_id=str(line.get(LINE_ITEM_ID_ATTRIBUTE) or new_line_item_id()),
                product_id=product_id,
                product_name_snapshot=str(offered[PRODUCT_NAME_SNAPSHOT_ATTRIBUTE]),
                unit_price_cents_snapshot=int(offered[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE]),
                immediate_qty=int(line[IMMEDIATE_QTY_ATTRIBUTE]),
                we_owe_qty=int(line[WE_OWE_QTY_ATTRIBUTE]),
            )
        )
    return snapshot


def line_subtotal_cents(line: Mapping[str, Any]) -> int:
    """``(immediateQty + weOweQty) * unitPriceCentsSnapshot`` (§5.14)."""
    quantity = int(line[IMMEDIATE_QTY_ATTRIBUTE]) + int(line[WE_OWE_QTY_ATTRIBUTE])
    return normalize_money_cents(quantity * int(line[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE]), SUBTOTAL_CENTS_ATTRIBUTE)


def sale_total_cents(line_items: Sequence[Mapping[str, Any]]) -> int:
    """The sum of the line subtotals (§5.14)."""
    return normalize_money_cents(sum(int(line[SUBTOTAL_CENTS_ATTRIBUTE]) for line in line_items), TOTAL_CENTS_ATTRIBUTE)


def reprice_line_item(line: Mapping[str, Any], immediate_qty: int, we_owe_qty: int) -> Dict[str, Any]:
    """A corrected quantity on an existing line, with its snapshot kept.

    The name and price snapshots ride through untouched: a correction changes what sold,
    never what the product was called or priced at when it sold (§5.14).
    """
    return build_sale_line_item(
        line_item_id=str(line[LINE_ITEM_ID_ATTRIBUTE]),
        product_id=str(line[PRODUCT_ID_ATTRIBUTE]),
        product_name_snapshot=str(line[PRODUCT_NAME_SNAPSHOT_ATTRIBUTE]),
        unit_price_cents_snapshot=int(line[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE]),
        immediate_qty=immediate_qty,
        we_owe_qty=we_owe_qty,
    )


def sale_line_quantities(line_items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """Total immediate quantity per product across the sale's lines (§8.6.1 step 2).

    Aggregated by product because stock is counted per product: three lines of one
    product consume one allocation, and the planner is asked once for the whole delta.
    """
    totals: Dict[str, int] = {}
    for line in line_items:
        product_id = str(line[PRODUCT_ID_ATTRIBUTE])
        totals[product_id] = totals.get(product_id, 0) + int(line[IMMEDIATE_QTY_ATTRIBUTE])
    return totals


def buyer_name_required(line_items: Sequence[Mapping[str, Any]]) -> bool:
    """Whether any line creates a We Owe obligation, and so whether a buyer name is required."""
    return any(int(line[WE_OWE_QTY_ATTRIBUTE]) > 0 for line in line_items)


# --- Row builders ------------------------------------------------------------------


#: §5.14's required attributes, on a sale row and on one embedded line item.
_SALE_REQUIRED_ATTRIBUTES: Tuple[str, ...] = (
    SALE_ID_ATTRIBUTE,
    SHOW_AND_SELL_ID_ATTRIBUTE,
    UNIT_ID_ATTRIBUTE,
    UNIT_CAMPAIGN_ID_ATTRIBUTE,
    SALE_AT_ATTRIBUTE,
    ENTERED_BY_ATTRIBUTE,
    LINE_ITEMS_ATTRIBUTE,
    TOTAL_CENTS_ATTRIBUTE,
    PAYMENT_SNAPSHOT_ATTRIBUTE,
    REVISION_ATTRIBUTE,
    STATUS_ATTRIBUTE,
)
_SALE_LINE_REQUIRED_ATTRIBUTES: Tuple[str, ...] = (
    LINE_ITEM_ID_ATTRIBUTE,
    PRODUCT_ID_ATTRIBUTE,
    PRODUCT_NAME_SNAPSHOT_ATTRIBUTE,
    UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE,
    IMMEDIATE_QTY_ATTRIBUTE,
    WE_OWE_QTY_ATTRIBUTE,
    SUBTOTAL_CENTS_ATTRIBUTE,
)


def _missing_required(item: Mapping[str, Any], required: Sequence[str]) -> List[str]:
    """Every required attribute that is absent, as a list.

    A list rather than a raise because the same check answers two questions: "is the row
    I am about to write valid" and "is the row I read back corrupt". The second has no
    caller who can fix it by re-typing an input, so it wants everything that is wrong at
    once, and the first wants the builder's invariant failure to name every term it broke
    rather than only the first.
    """
    return [f"{name} is required" for name in required if item.get(name) is None]


def sale_line_violations(line: Mapping[str, Any]) -> List[str]:
    """What is wrong with one embedded line item, §5.14's shape and invariants."""
    missing = _missing_required(line, _SALE_LINE_REQUIRED_ATTRIBUTES)
    if missing:
        return missing
    quantity = int(line[IMMEDIATE_QTY_ATTRIBUTE]) + int(line[WE_OWE_QTY_ATTRIBUTE])
    violations: List[str] = []
    if quantity < 1:
        violations.append("immediateQty + weOweQty must be greater than zero")
    if int(line[SUBTOTAL_CENTS_ATTRIBUTE]) != quantity * int(line[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE]):
        violations.append("subtotalCents must equal (immediateQty + weOweQty) * unitPriceCentsSnapshot")
    return violations


def sale_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """What is wrong with one sale row (§5.14's invariants, stated once)."""
    violations = _missing_required(item, _SALE_REQUIRED_ATTRIBUTES)
    if violations:
        return violations
    lines = list(item[LINE_ITEMS_ATTRIBUTE] or [])
    if not lines:
        violations.append("lineItems must not be empty")
    for line in lines:
        violations.extend(sale_line_violations(line))
    violations.extend(_sale_total_violation(item, lines))
    violations.extend(_payment_snapshot_violations(item[PAYMENT_SNAPSHOT_ATTRIBUTE]))
    violations.extend(_sale_revision_violation(item))
    return violations


def _sale_total_violation(item: Mapping[str, Any], lines: Sequence[Mapping[str, Any]]) -> List[str]:
    """The total is the sum of the subtotals, never a number typed beside them (§5.14).

    A sale whose stored total disagrees with its own lines is the worst kind of defect in
    this feature: the whole pool, the cash drawer and every Scout's credit are summed from
    these rows, so a drift here becomes a discrepancy a human has to chase at the table.
    """
    subtotal_sum = sum(int(line.get(SUBTOTAL_CENTS_ATTRIBUTE) or 0) for line in lines)
    if subtotal_sum != int(item[TOTAL_CENTS_ATTRIBUTE]):
        return ["totalCents must equal the sum of the line subtotals"]
    return []


def _sale_revision_violation(item: Mapping[str, Any]) -> List[str]:
    """Revision history's two preconditions: a positive counter, and a first instant.

    ``createdAt`` matters from revision 2 onward because an archived revision has to carry
    when the sale was entered, not merely when it was last corrected (§5.14).
    """
    revision = int(item[REVISION_ATTRIBUTE])
    if revision < 1:
        return ["revision must be a positive integer"]
    if revision > 1 and not item.get(CREATED_AT_ATTRIBUTE):
        return ["createdAt must be stored so a prior revision can be read as history"]
    return []


def _payment_snapshot_violations(snapshot: Any) -> List[str]:
    """The one-method snapshot's own rules (§5.14).

    A sale cannot carry a second method, because then "how was this sale paid" would have
    no single answer and expected cash would be arithmetic on a list — §7.1's
    split-payment guidance answers a split by recording Other with an explanation instead.
    """
    if not isinstance(snapshot, Mapping):
        return ["paymentMethodSnapshot must carry methodCode and displayName"]
    violations: List[str] = []
    code = snapshot.get("methodCode")
    if not isinstance(code, str) or not code:
        violations.append("paymentMethodSnapshot.methodCode is required")
    if not isinstance(snapshot.get("displayName"), str) or not str(snapshot.get("displayName")):
        violations.append("paymentMethodSnapshot.displayName is required")
    violations.extend(_other_details_violations(code, snapshot))
    return violations


def _other_details_violations(code: Any, snapshot: Mapping[str, Any]) -> List[str]:
    """Other's note is required exactly for Other and belongs to nothing else (§5.14).

    The note is the whole reason Other exists: an unusual payment is recorded so the cash
    count still adds up, and a bare Other leaves the drawer with an unexplained difference.
    """
    details = str(snapshot.get("otherDetails") or "").strip()
    if code == "OTHER" and not details:
        return ["paymentMethodSnapshot.otherDetails is required for the Other method"]
    if code not in (None, "OTHER") and details:
        return ["paymentMethodSnapshot.otherDetails belongs only to the Other method"]
    return []


def build_show_and_sell_sale_item(
    *,
    show_and_sell_id: str,
    unit_id: str,
    unit_campaign_id: str,
    sale_at: str,
    entered_by_account_id: str,
    line_items: Sequence[Mapping[str, Any]],
    payment_method_snapshot: Mapping[str, Any],
    idempotency_key: str,
    now_iso: str,
    sale_id: Optional[str] = None,
    buyer_name: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    buyer_email: Optional[str] = None,
    revision: int = 1,
    status: str = SALE_STATUS_ACTIVE,
    created_at: Optional[str] = None,
    voided_by_account_id: Optional[str] = None,
    voided_at: Optional[str] = None,
    require_buyer_name: bool = True,
) -> Dict[str, Any]:
    """One ``ShowAndSellSale`` row, built from validated parts with money derived.

    ``require_buyer_name`` is false only on the correction path, where the row already
    exists and the caller is correcting a line that never needed a name; the create path
    and any corrected sale that still owes something pass the default and are refused
    without one (§5.14: We Owe needs a buyer, and no Account is required for one).
    """
    buyer = normalize_buyer_name(buyer_name)
    if require_buyer_name and buyer is None and buyer_name_required(line_items):
        raise _invalid(
            BUYER_NAME_ATTRIBUTE,
            "is required because at least one line creates We Owe; a We Owe obligation has no Account, only a buyer name",
        )
    stable_sale_id = normalize_sale_id(sale_id or new_sale_id())
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": sale_sk(stable_sale_id),
        "entityType": SALE_ENTITY_TYPE,
        SALE_ID_ATTRIBUTE: stable_sale_id,
        SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_models.normalize_event_id(show_and_sell_id),
        UNIT_ID_ATTRIBUTE: normalize_sale_key_id(unit_id, UNIT_ID_ATTRIBUTE),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        SALE_AT_ATTRIBUTE: normalize_sale_at(sale_at),
        ENTERED_BY_ATTRIBUTE: normalize_sale_key_id(entered_by_account_id, ENTERED_BY_ATTRIBUTE),
        LINE_ITEMS_ATTRIBUTE: [dict(line) for line in line_items],
        TOTAL_CENTS_ATTRIBUTE: sale_total_cents(line_items),
        PAYMENT_SNAPSHOT_ATTRIBUTE: dict(payment_method_snapshot),
        REVISION_ATTRIBUTE: normalize_quantity(revision, REVISION_ATTRIBUTE),
        STATUS_ATTRIBUTE: normalize_sale_status(status),
        IDEMPOTENCY_KEY_ATTRIBUTE: normalize_required_text(idempotency_key, IDEMPOTENCY_KEY_ATTRIBUTE, 128),
        CREATED_AT_ATTRIBUTE: show_and_sell_models.normalize_moment(created_at or now_iso, CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: show_and_sell_models.normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE),
    }
    for name, value in _sale_optional_attributes(
        buyer, buyer_phone, buyer_email, voided_by_account_id, voided_at
    ).items():
        item[name] = value
    violations = sale_invariant_violations(item)
    if violations:
        raise _invalid("lineItems", f"would break the sale invariants: {'; '.join(violations)}")
    return item


def _sale_optional_attributes(
    buyer_name: Optional[str],
    buyer_phone: Optional[str],
    buyer_email: Optional[str],
    voided_by_account_id: Optional[str],
    voided_at: Optional[str],
) -> Dict[str, Any]:
    """The buyer and void fields, carried only when they have a value.

    A sale with no We Owe carries no buyer name rather than an empty string, and a sale
    that has not been voided carries no void audit: the absence is the answer, and a
    stored empty would read as "the buyer's name was blank" to every report that lists one
    (§5.14). The void pair is validated here too, because a void audit that names an
    account but no instant, or the other way round, is the same unreadable row.
    """
    candidates: Tuple[Tuple[str, Any], ...] = (
        (BUYER_NAME_ATTRIBUTE, buyer_name),
        (BUYER_PHONE_ATTRIBUTE, normalize_buyer_phone(buyer_phone)),
        (BUYER_EMAIL_ATTRIBUTE, normalize_buyer_email(buyer_email)),
        (
            VOIDED_BY_ATTRIBUTE,
            None if voided_by_account_id is None else normalize_sale_key_id(voided_by_account_id, VOIDED_BY_ATTRIBUTE),
        ),
        (VOIDED_AT_ATTRIBUTE, None if voided_at is None else normalize_sale_at(voided_at)),
    )
    return {name: value for name, value in candidates if value is not None}


def build_sale_revision_item(
    sale_row: Mapping[str, Any],
    *,
    corrected_by_account_id: str,
    reason: str,
    corrected_at: str,
) -> Dict[str, Any]:
    """The immutable child holding one whole previous revision (§5.14, §8.6.1 step 1).

    Every value the sale row carried is copied — line items, total, buyer fields, the
    payment snapshot, the state, the sale time and the entry audit — and the correction's
    own actor, reason and instant are added. This row is never updated afterwards, which
    is why a product renamed, a method deactivated, or a later correction cannot reach a
    sale that already happened: the history keeps the words it was written in.
    """
    sale_id = normalize_sale_id(sale_row[SALE_ID_ATTRIBUTE])
    show_and_sell_id = str(sale_row[SHOW_AND_SELL_ID_ATTRIBUTE])
    revision = int(sale_row[REVISION_ATTRIBUTE])
    if revision < 1:
        raise _invalid(REVISION_ATTRIBUTE, "must be a positive integer before a revision can be archived")
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": sale_revision_sk(sale_id, revision),
        "entityType": SALE_REVISION_ENTITY_TYPE,
        SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_id,
        UNIT_ID_ATTRIBUTE: sale_row[UNIT_ID_ATTRIBUTE],
        UNIT_CAMPAIGN_ID_ATTRIBUTE: sale_row[UNIT_CAMPAIGN_ID_ATTRIBUTE],
        SALE_ID_ATTRIBUTE: sale_id,
        REVISION_ATTRIBUTE: revision,
        SALE_AT_ATTRIBUTE: sale_row[SALE_AT_ATTRIBUTE],
        ENTERED_BY_ATTRIBUTE: sale_row[ENTERED_BY_ATTRIBUTE],
        LINE_ITEMS_ATTRIBUTE: [sale_line_payload(line) for line in sale_row[LINE_ITEMS_ATTRIBUTE]],
        TOTAL_CENTS_ATTRIBUTE: int(sale_row[TOTAL_CENTS_ATTRIBUTE]),
        PAYMENT_SNAPSHOT_ATTRIBUTE: dict(sale_row[PAYMENT_SNAPSHOT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: normalize_sale_status(sale_row[STATUS_ATTRIBUTE]),
        CREATED_AT_ATTRIBUTE: sale_row[CREATED_AT_ATTRIBUTE],
        CORRECTED_BY_ATTRIBUTE: normalize_sale_key_id(corrected_by_account_id, CORRECTED_BY_ATTRIBUTE),
        CORRECTED_AT_ATTRIBUTE: normalize_sale_at(corrected_at),
        REASON_ATTRIBUTE: normalize_sale_reason(reason),
    }
    for name in (
        BUYER_NAME_ATTRIBUTE,
        BUYER_PHONE_ATTRIBUTE,
        BUYER_EMAIL_ATTRIBUTE,
        VOIDED_BY_ATTRIBUTE,
        VOIDED_AT_ATTRIBUTE,
    ):
        if sale_row.get(name) is not None:
            item[name] = sale_row[name]
    return item


def build_we_owe_item(
    *,
    show_and_sell_id: str,
    unit_campaign_id: str,
    sale_id: str,
    line_item: Mapping[str, Any],
    buyer_name: str,
    now_iso: str,
    we_owe_id: Optional[str] = None,
    quantity: Optional[int] = None,
) -> Dict[str, Any]:
    """One open We Owe obligation created by one line (§5.15).

    The obligation snapshots the product's name and the value of what it owes at the
    moment of the sale, and its quantity arithmetic starts at ``originalQty`` with
    nothing fulfilled, cancelled, or reserved. ``valueCentsSnapshot`` is the owed portion
    priced at the same snapshot price the line carried, so a later price change cannot
    rewrite what the Unit owes the buyer (§5.15: "corrections retain history").
    """
    owed = (
        int(line_item[WE_OWE_QTY_ATTRIBUTE])
        if quantity is None
        else normalize_quantity(quantity, ORIGINAL_QTY_ATTRIBUTE)
    )
    if owed < 1:
        raise _invalid(WE_OWE_QTY_ATTRIBUTE, "must be greater than zero to create a We Owe obligation")
    price = int(line_item[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE])
    # Mint the id once: the sort key and the row's own weOweId attribute are one identity,
    # and minting twice would store the row under a key no later write can address.
    obligation_id = normalize_we_owe_id(we_owe_id or new_we_owe_id())
    return {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": we_owe_sk(obligation_id),
        "entityType": WE_OWE_ENTITY_TYPE,
        WE_OWE_ID_ATTRIBUTE: obligation_id,
        SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_models.normalize_event_id(show_and_sell_id),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        SALE_ID_ATTRIBUTE: normalize_sale_id(sale_id),
        LINE_ITEM_ID_ATTRIBUTE: normalize_line_item_id(line_item[LINE_ITEM_ID_ATTRIBUTE]),
        BUYER_NAME_ATTRIBUTE: normalize_required_text(buyer_name, BUYER_NAME_ATTRIBUTE, MAX_BUYER_NAME_LENGTH),
        PRODUCT_ID_ATTRIBUTE: inventory_models.normalize_inventory_id(
            line_item[PRODUCT_ID_ATTRIBUTE], PRODUCT_ID_ATTRIBUTE
        ),
        PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: str(line_item[PRODUCT_NAME_SNAPSHOT_ATTRIBUTE]),
        ORIGINAL_QTY_ATTRIBUTE: owed,
        FULFILLED_QTY_ATTRIBUTE: 0,
        CANCELLED_QTY_ATTRIBUTE: 0,
        RESERVED_QTY_ATTRIBUTE: 0,
        REMAINING_QTY_ATTRIBUTE: owed,
        UNCOVERED_QTY_ATTRIBUTE: owed,
        VALUE_CENTS_SNAPSHOT_ATTRIBUTE: normalize_money_cents(owed * price, VALUE_CENTS_SNAPSHOT_ATTRIBUTE),
        STATUS_ATTRIBUTE: WE_OWE_STATUS_OPEN,
        VERSION_ATTRIBUTE: 1,
        CREATED_AT_ATTRIBUTE: show_and_sell_models.normalize_moment(now_iso, CREATED_AT_ATTRIBUTE),
    }


#: §5.15's required attributes on an obligation row.
_WE_OWE_REQUIRED_ATTRIBUTES: Tuple[str, ...] = (
    WE_OWE_ID_ATTRIBUTE,
    SHOW_AND_SELL_ID_ATTRIBUTE,
    SALE_ID_ATTRIBUTE,
    LINE_ITEM_ID_ATTRIBUTE,
    BUYER_NAME_ATTRIBUTE,
    PRODUCT_ID_ATTRIBUTE,
    ORIGINAL_QTY_ATTRIBUTE,
    FULFILLED_QTY_ATTRIBUTE,
    CANCELLED_QTY_ATTRIBUTE,
    RESERVED_QTY_ATTRIBUTE,
    REMAINING_QTY_ATTRIBUTE,
    UNCOVERED_QTY_ATTRIBUTE,
    STATUS_ATTRIBUTE,
    VERSION_ATTRIBUTE,
)


def we_owe_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """§5.15's invariant block, stated once over the stored row."""
    violations = _missing_required(item, _WE_OWE_REQUIRED_ATTRIBUTES)
    if violations:
        return violations
    violations.extend(_we_owe_quantity_violations(item))
    violations.extend(_we_owe_status_violations(item))
    return violations


def _we_owe_quantity_violations(item: Mapping[str, Any]) -> List[str]:
    """The §5.15 arithmetic: what is owed, what is gone, and the reservation inside the rest.

    Every one of these is a rule a fulfillment or a correction could otherwise break one
    write at a time — a reservation above what remains would promise the same unit to two
    buyers, and a remaining that stops reconciling against original is a We Owe list whose
    totals no longer add up.
    """
    original = int(item[ORIGINAL_QTY_ATTRIBUTE])
    fulfilled = int(item[FULFILLED_QTY_ATTRIBUTE])
    cancelled = int(item[CANCELLED_QTY_ATTRIBUTE])
    reserved = int(item[RESERVED_QTY_ATTRIBUTE])
    remaining = int(item[REMAINING_QTY_ATTRIBUTE])
    uncovered = int(item[UNCOVERED_QTY_ATTRIBUTE])
    violations: List[str] = []
    if original < fulfilled + cancelled or fulfilled + cancelled < 0:
        violations.append("originalQty must be at least fulfilledQty + cancelledQty")
    if remaining != original - fulfilled - cancelled:
        violations.append("remainingQty must equal originalQty - fulfilledQty - cancelledQty")
    if reserved < 0 or reserved > remaining:
        violations.append("reservedQty must stay between 0 and remainingQty")
    if uncovered != remaining - reserved:
        violations.append("uncoveredQty must equal remainingQty - reservedQty")
    return violations


def _we_owe_status_violations(item: Mapping[str, Any]) -> List[str]:
    """CLOSED means nothing is owed and nothing is reserved (§5.15's two-state pair).

    There are only OPEN and CLOSED because a third report state would have to say which
    of these two numbers it is talking about; the reason an obligation closed is a separate
    audit attribute, never a status.
    """
    status = str(item[STATUS_ATTRIBUTE])
    violations: List[str] = []
    if status not in {WE_OWE_STATUS_OPEN, WE_OWE_STATUS_CLOSED}:
        violations.append(f"status must be one of {WE_OWE_STATUS_OPEN}, {WE_OWE_STATUS_CLOSED}")
    elif status == WE_OWE_STATUS_CLOSED and (
        int(item[REMAINING_QTY_ATTRIBUTE]) != 0 or int(item[RESERVED_QTY_ATTRIBUTE]) != 0
    ):
        violations.append("status CLOSED requires remainingQty and reservedQty to be zero")
    if int(item[VERSION_ATTRIBUTE]) < 1:
        violations.append("version must be a positive integer")
    return violations


def build_we_owe_fulfillment_item(
    *,
    show_and_sell_id: str,
    we_owe_id: str,
    fulfillment_id: str,
    quantity: int,
    source: Any,
    actor_account_id: str,
    now_iso: str,
    inventory_movement_id: Optional[str] = None,
) -> Dict[str, Any]:
    """One append-only fulfillment record (§5.15, OWE-09).

    The record says what one write delivered and where it came from; it never restates the
    obligation's totals, because then two rows would hold the same quantity and a reader
    could not tell which one a later write updates. There is no ``version`` attribute and
    no edit path: a mistaken fulfillment is answered by a later record or by a sale
    correction, never by rewriting this one.

    The row carries no ``unitCampaignId``, and that is deliberate rather than an omission:
    ``unitCampaignId-status-index`` is the obligation list, and a history row that landed in
    it would answer a "what is still owed" query with records that owe nothing.
    """
    kind = normalize_we_owe_source(source)
    record_id = normalize_fulfillment_id(fulfillment_id)
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": we_owe_fulfillment_sk(normalize_we_owe_id(we_owe_id), record_id),
        "entityType": WE_OWE_FULFILLMENT_ENTITY_TYPE,
        WE_OWE_ID_ATTRIBUTE: normalize_we_owe_id(we_owe_id),
        FULFILLMENT_ID_ATTRIBUTE: record_id,
        FULFILLMENT_QTY_ATTRIBUTE: normalize_fulfillment_qty(quantity),
        FULFILLMENT_SOURCE_ATTRIBUTE: kind,
        ACTOR_ACCOUNT_ID_ATTRIBUTE: normalize_required_text(
            actor_account_id, ACTOR_ACCOUNT_ID_ATTRIBUTE, MAX_ID_LENGTH
        ),
        CREATED_AT_ATTRIBUTE: show_and_sell_models.normalize_moment(now_iso, CREATED_AT_ATTRIBUTE),
    }
    if inventory_movement_id is not None:
        item[FULFILLMENT_MOVEMENT_ATTRIBUTE] = inventory_models.normalize_inventory_id(
            inventory_movement_id, FULFILLMENT_MOVEMENT_ATTRIBUTE
        )
    return item


#: §5.15's required attributes on a fulfillment record.
_WE_OWE_FULFILLMENT_REQUIRED_ATTRIBUTES: Tuple[str, ...] = (
    WE_OWE_ID_ATTRIBUTE,
    FULFILLMENT_ID_ATTRIBUTE,
    FULFILLMENT_QTY_ATTRIBUTE,
    FULFILLMENT_SOURCE_ATTRIBUTE,
    ACTOR_ACCOUNT_ID_ATTRIBUTE,
    CREATED_AT_ATTRIBUTE,
)


def we_owe_fulfillment_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """What makes one fulfillment record a record of something that happened.

    The source-and-movement pairing is the half that matters for an audit: ``KERNEL_STOCK``
    names the ``InventoryMovement`` that moved the stock, and ``EXTERNAL_COUNCIL`` names
    none, because a Council that supplied a quantity changed no Unit quantity, so a movement
    row would describe a stock change that never occurred (§5.15). A reader reconciling the
    trail against the balances finds one movement per Kernel fulfillment and no unexplained
    movement anywhere else.
    """
    violations = _missing_required(item, _WE_OWE_FULFILLMENT_REQUIRED_ATTRIBUTES)
    if violations:
        return violations
    if VERSION_ATTRIBUTE in item:
        violations.append(f"{VERSION_ATTRIBUTE} would make an append-only record mutable")
    if int(item[FULFILLMENT_QTY_ATTRIBUTE]) < 1:
        violations.append("quantity must be a positive integer")
    source = str(item[FULFILLMENT_SOURCE_ATTRIBUTE])
    if source not in WE_OWE_SOURCES:
        violations.append(f"source must be one of {', '.join(sorted(WE_OWE_SOURCES))}")
    elif source == WE_OWE_SOURCE_KERNEL and not item.get(FULFILLMENT_MOVEMENT_ATTRIBUTE):
        violations.append("a KERNEL_STOCK fulfillment must name the inventory movement that moved the stock")
    elif source == WE_OWE_SOURCE_EXTERNAL and item.get(FULFILLMENT_MOVEMENT_ATTRIBUTE):
        violations.append("an EXTERNAL_COUNCIL fulfillment changed no Unit stock and must name no movement")
    return violations


def we_owe_fulfillment_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One fulfillment row as the SDL's ``WeOweFulfillment`` (§7.2)."""
    return {
        FULFILLMENT_ID_ATTRIBUTE: str(row[FULFILLMENT_ID_ATTRIBUTE]),
        WE_OWE_ID_ATTRIBUTE: str(row[WE_OWE_ID_ATTRIBUTE]),
        FULFILLMENT_QTY_ATTRIBUTE: int(row[FULFILLMENT_QTY_ATTRIBUTE]),
        FULFILLMENT_SOURCE_ATTRIBUTE: str(row[FULFILLMENT_SOURCE_ATTRIBUTE]),
        FULFILLMENT_MOVEMENT_ATTRIBUTE: row.get(FULFILLMENT_MOVEMENT_ATTRIBUTE),
        ACTOR_ACCOUNT_ID_ATTRIBUTE: str(row[ACTOR_ACCOUNT_ID_ATTRIBUTE]),
        CREATED_AT_ATTRIBUTE: str(row[CREATED_AT_ATTRIBUTE]),
    }


def put_we_owe_fulfillment_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Create one fulfillment record.

    The condition is what makes the record's own id the uniqueness guard: a retry that
    somehow reached the write again would collide with the record the first attempt
    committed rather than appending a second delivery of the same quantity.
    """
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def load_we_owe_fulfillment_or_internal(show_and_sell_id: str, we_owe_id: str, fulfillment_id: str) -> Dict[str, Any]:
    """The fulfillment record this handler just wrote.

    A missing record here is not a caller's error: the record and the obligation write
    committed in one transaction, so a read that cannot find it means the answer this
    handler is about to give would not match the rows that exist.
    """
    response = tables.show_and_sells.get_item(
        Key=we_owe_fulfillment_key(show_and_sell_id, we_owe_id, fulfillment_id), ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, Mapping):
        raise AppError(ErrorCode.INTERNAL_ERROR, "the fulfillment record could not be loaded")
    return dict(item)


def require_we_owe_version(row: Mapping[str, Any], expected_version: int) -> None:
    """Refuse a reservation or fulfillment whose caller read a stale obligation (§4.4.2, §4.4.3).

    The obligation's version is what serializes the three writers of one row — a sale
    correction, a reservation, and a fulfillment — and the write's condition is what makes a
    stale one lose its whole transaction. This check is the same rule stated before any plan
    is built, so a caller whose screen is behind learns which obligation moved instead of
    discovering it through a cancelled transaction it cannot read.
    """
    current = int(row[VERSION_ATTRIBUTE])
    if current == expected_version:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        "This obligation changed since you read it. Re-read it and try again.",
        details={
            "subcode": WE_OWE_VERSION_STALE,
            "we_owe_id": str(row[WE_OWE_ID_ATTRIBUTE]),
            "expectedVersion": expected_version,
            "currentVersion": current,
        },
    )


# --- Entry rules shared by all three mutations (§4.3.3) -----------------------------


def require_sale_state(event_row: Mapping[str, Any], now_iso: Optional[str] = None) -> str:
    """Which sale-write state this event is in: :data:`SALE_STATE_LIVE` or :data:`SALE_STATE_DRAFT`.

    The decision is the one the read path reports — :func:`show_and_sell_models.derive_event_status` —
    never the stored field: a live event's row stores ``SCHEDULED`` and reads as ``ACTIVE``
    or ``ENDED`` only once the clock reaches the interval (SSE-04's clock states, which the
    model forbids storing and the invariant rejects on a row that carries one). Switching
    on the stored field instead reads every live event as ``SCHEDULED`` and refuses every
    sale the product can create. ``ACTIVE`` and ``ENDED`` write the stock answer now
    (§4.2.2's live states); ``REOPENED`` records only the draft and leaves the effect to
    re-finalization (§8.6); every other state is refused, including ``FINALIZED``, where
    an approved version has already published the numbers a new sale would contradict.
    The refusal names the state the caller is told about, because an admin staring at a
    table needs the verdict to match what ``showAndSell`` answered two lines above.
    """
    status = show_and_sell_models.derive_event_status(event_row, now_iso)
    if status in {show_and_sell_models.STATUS_ACTIVE, show_and_sell_models.STATUS_ENDED}:
        return SALE_STATE_LIVE
    if status == show_and_sell_models.STATUS_REOPENED:
        return SALE_STATE_DRAFT
    raise AppError(
        ErrorCode.CONFLICT,
        f"Pooled sales are entered while an event is ACTIVE, ENDED, or REOPENED; this event is {status}.",
        details={"subcode": "EVENT_STATE_REFUSES_SALE", STATUS_ATTRIBUTE: status},
    )


def require_we_owe_available(event_row: Mapping[str, Any], line_items: Sequence[Mapping[str, Any]]) -> None:
    """Refuse a We Owe quantity on an event that did not enable We Owe (§7.1, SALE-M-01-03).

    ``weOweEnabled`` is a choice the Unit makes when it opens the event, and a sale is
    not allowed to make it again: an obligation the event never opted into is a promise
    no report was going to look for, and it survives into finalization as money taken
    for stock nobody owes. The refusal names the products, because the admin at a table
    with sixteen lines has to know which one to change into an immediate handoff.
    """
    if bool(event_row.get(show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE) or False):
        return
    owed = sorted({str(line[PRODUCT_ID_ATTRIBUTE]) for line in line_items if int(line[WE_OWE_QTY_ATTRIBUTE]) > 0})
    if not owed:
        return
    _refuse(
        WE_OWE_NOT_ENABLED,
        "This event does not offer We Owe; sell the quantity immediately or reopen the event "
        "with We Owe enabled: " + ", ".join(owed),
        product_ids=owed,
        show_and_sell_id=str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]),
    )


def require_sale_at_in_event(sale_at: str, event_row: Mapping[str, Any]) -> str:
    """Require the sale's instant to sit inside the event's immutable interval (§4.3.3).

    Both bounds are inclusive: a sale at the opening instant and one at the closing one
    both happened at this event. ``endAt`` is not widened for a back-dated paper entry —
    a sale after the event ended belongs to the event that is actually running, and
    letting it land here would put money in a pool that has already been counted.
    """
    moment = normalize_sale_at(sale_at)
    start_at = str(event_row[show_and_sell_models.START_AT_ATTRIBUTE])
    end_at = str(event_row[show_and_sell_models.END_AT_ATTRIBUTE])
    if moment < start_at or moment > end_at:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"saleAt must fall inside the event's interval {start_at} to {end_at}; this sale is {moment}.",
            details={"subcode": "SALE_AT_OUTSIDE_EVENT", SALE_AT_ATTRIBUTE: moment},
        )
    return moment


def sale_expected_cash_cents(sale_row: Mapping[str, Any]) -> int:
    """What this sale contributes to the drawer, by method code and nothing else (AC-31).

    A custom method named ``Cash`` and an Other note describing a split both contribute
    nothing: the display text is what the Unit called the method, and the cash drawer is
    a count of money. The classifier itself lives beside the snapshot rule it follows
    from (:func:`src.utils.sale_payment_models.expected_cash_cents`), so the two cannot
    drift; this is the sale-row-shaped door to it.
    """
    return expected_cash_cents(sale_row[PAYMENT_SNAPSHOT_ATTRIBUTE], sale_row[TOTAL_CENTS_ATTRIBUTE])


def require_sale_active(sale_row: Mapping[str, Any]) -> None:
    """Refuse to correct or void a sale that is already voided."""
    if str(sale_row.get(STATUS_ATTRIBUTE) or "") != SALE_STATUS_ACTIVE:
        raise AppError(
            ErrorCode.CONFLICT,
            "This sale is already voided; a voided sale is history and is corrected by entering a new one.",
            details={"subcode": SALE_ALREADY_VOIDED, SALE_ID_ATTRIBUTE: str(sale_row.get(SALE_ID_ATTRIBUTE, ""))},
        )


def require_sale_revision(sale_row: Mapping[str, Any], expected_revision: int) -> None:
    """Pin the correction to the revision its read was taken against (§7.1, VER-01).

    ``revision`` is the sale's own optimistic-concurrency number: a correction that
    archived revision 3 while another admin's correction was also archiving 3 would
    otherwise publish two different revision 4s, each with a different revision 3 behind
    it, and the history would stop being a chain.
    """
    stored = int(sale_row[REVISION_ATTRIBUTE])
    if stored != int(expected_revision):
        raise AppError(
            ErrorCode.CONFLICT,
            f"This sale is at revision {stored}; the correction was taken against revision {expected_revision}. "
            "Re-read the sale and correct it again.",
            details={
                "subcode": "STALE_SALE_REVISION",
                REVISION_ATTRIBUTE: stored,
                "expectedRevision": int(expected_revision),
            },
        )


# --- The per-product sale stock planner (§4.2.3) ------------------------------------


@dataclass(frozen=True)
class SaleStockChange:
    """What one product's immediate quantity does to this event's stock.

    ``immediate_delta`` is the whole quantity this write is handing over, positive for a
    sale and negative for the reversal a correction or a void produces. The allocation and
    balance numbers are targets the write sets, not amounts to add: two admins selling
    from one allocation must not each compute from their own read of ``soldQty``.
    """

    product_id: str
    immediate_delta: int
    new_sold_qty: int
    new_remaining_qty: int
    allocation_version: int
    balance_version: int
    physical_delta: int
    movement_type: str


def _refuse_no_allocation(product_id: str, show_and_sell_id: str, allocation: Optional[Mapping[str, Any]]) -> NoReturn:
    """Refuse to sell stock this event does not hold (§4.2.2's "valid stock")."""
    if allocation is not None and str(allocation.get(STATUS_ATTRIBUTE) or "") != ALLOCATION_OPEN:
        _refuse(
            INSUFFICIENT_EVENT_STOCK,
            f"{product_id}: this event's allocation is {allocation.get(STATUS_ATTRIBUTE)} and holds nothing to sell.",
            product_id=product_id,
            show_and_sell_id=show_and_sell_id,
        )
    _refuse(
        NO_EVENT_ALLOCATION,
        f"{product_id}: this event has no stock assigned, so it has nothing to sell. Assign stock first.",
        product_id=product_id,
        show_and_sell_id=show_and_sell_id,
    )


def _refuse_insufficient_stock(product_id: str, immediate_qty: int, available_qty: int) -> NoReturn:
    """Refuse a sale that asks for more than the event holds, and say how much it holds."""
    _refuse(
        INSUFFICIENT_EVENT_STOCK,
        f"{product_id}: {immediate_qty} asked for, but this event holds {available_qty} to sell.",
        product_id=product_id,
        requestedQty=immediate_qty,
        availableQty=available_qty,
    )


def plan_sale_stock(
    *,
    show_and_sell_id: str,
    product_id: str,
    immediate_qty: int,
    allocation: Optional[Mapping[str, Any]],
    balance: Optional[Mapping[str, Any]],
) -> Optional[SaleStockChange]:
    """The shared per-product sale planner (§4.2.3).

    This is the planner a live write uses: it refuses an unavailable quantity against the
    event's own open allocation and against the campaign's physical count, and returns the
    three numbers one product's write sets: the allocation's ``soldQty`` and
    ``remainingQty``, and the balance's physical quantity through ``physical_delta``. A
    ``REOPENED`` event never reaches this planner at all — its sale writes only the draft
    sale, and §8.6 gives re-finalization the job of validating and applying what was
    entered meanwhile, with that version's own planner and its own reads.

    A zero quantity answers ``None``: an unaffected line spends no allocation write, no
    balance version bump, and no movement, which is §8.6.1's "do not reverse and reapply
    unaffected lines" as a property of the plan rather than of the caller's discipline.
    """
    quantity = normalize_quantity(immediate_qty, IMMEDIATE_QTY_ATTRIBUTE)
    if quantity == 0:
        return None
    _require_coverable_stock(product_id, quantity, balance)
    if allocation is None or str(allocation.get(STATUS_ATTRIBUTE) or "") != ALLOCATION_OPEN:
        _refuse_no_allocation(product_id, show_and_sell_id, allocation)
    allocated = int(allocation[ALLOCATED_QTY])
    sold = int(allocation[SOLD_QTY])
    released = int(allocation.get(RELEASED_QTY) or 0)
    if sold + quantity > allocated - released:
        _refuse_insufficient_stock(product_id, quantity, allocated - released - sold)
    return SaleStockChange(
        product_id=inventory_models.normalize_inventory_id(product_id, PRODUCT_ID_ATTRIBUTE),
        immediate_delta=quantity,
        new_sold_qty=sold + quantity,
        new_remaining_qty=allocated - released - sold - quantity,
        allocation_version=int(allocation[VERSION_ATTRIBUTE]),
        balance_version=int(balance[VERSION_ATTRIBUTE]) if balance is not None else 0,
        physical_delta=-quantity,
        movement_type=inventory_models.EVENT_IMMEDIATE_SALE,
    )


def _require_coverable_stock(product_id: str, quantity: int, balance: Optional[Mapping[str, Any]]) -> None:
    """Refuse a quantity the campaign's shelf cannot cover.

    The floor is physical stock already promised to We Owe reservations
    (``soldInPossessionQty``): those units are counted in ``kernelPhysicalQty`` but are
    not sellable at a table (§7's ``sellableKernelQty``), so an immediate sale may take
    the rest and no more. A product with no balance row at all has nothing on any shelf,
    which is the same refusal rather than a crash.
    """
    if balance is None:
        _refuse_insufficient_stock(product_id, quantity, 0)
    available = int(balance[KERNEL_PHYSICAL_QTY]) - int(balance[SOLD_IN_POSSESSION_QTY])
    if quantity > available:
        _refuse_insufficient_stock(product_id, quantity, available)


def corrected_sale_stock_change(
    *,
    show_and_sell_id: str,
    product_id: str,
    immediate_delta: int,
    allocation: Optional[Mapping[str, Any]],
    balance: Optional[Mapping[str, Any]],
) -> Optional[SaleStockChange]:
    """Apply only a correction's ``immediateDelta`` to one product (§8.6.1 step 2).

    A negative delta hands units back: ``soldQty`` drops, ``remainingQty`` rises, and
    physical stock rises by the same number, all under one ``EVENT_IMMEDIATE_SALE``
    movement whose ``kernelPhysicalDelta`` is positive. A delta beyond what this event
    already sold on that product is refused rather than clamped — the corrected quantity
    and the stock effect are one statement, and clamping one would leave the other
    claiming a sale that never consumed stock.

    A ``REOPENED`` event never reaches this planner either, for the same reason the sale
    planner does not: its correction writes only the draft sale, and re-finalization
    replays the lines against that version's own stock reads.
    """
    delta = inventory_models.normalize_signed_delta(immediate_delta, "immediateDelta", nonzero=False)
    if delta == 0:
        return None
    if delta < 0:
        sold = _live_sold_qty(allocation)
        _refuse_overcorrected_stock(product_id, -delta, sold)
        # ``sold`` is zero unless the allocation is OPEN, and a nonzero handback
        # against zero was already refused above — reaching this line means the
        # allocation exists and is open, so the row's quantities can be read.
        allocation_row = cast(Mapping[str, Any], allocation)
        allocated = int(allocation_row[ALLOCATED_QTY])
        released = int(allocation_row.get(RELEASED_QTY) or 0)
        return SaleStockChange(
            product_id=inventory_models.normalize_inventory_id(product_id, PRODUCT_ID_ATTRIBUTE),
            immediate_delta=delta,
            new_sold_qty=sold + delta,
            new_remaining_qty=allocated - released - sold - delta,
            allocation_version=int(allocation_row[VERSION_ATTRIBUTE]),
            balance_version=int(balance[VERSION_ATTRIBUTE]) if balance is not None else 0,
            physical_delta=-delta,
            movement_type=inventory_models.EVENT_IMMEDIATE_SALE,
        )
    return plan_sale_stock(
        show_and_sell_id=show_and_sell_id,
        product_id=product_id,
        immediate_qty=delta,
        allocation=allocation,
        balance=balance,
    )


def _live_sold_qty(allocation: Optional[Mapping[str, Any]]) -> int:
    """This event's recorded sold quantity, which is the ceiling a reversal may take back."""
    if allocation is None or str(allocation.get(STATUS_ATTRIBUTE) or "") != ALLOCATION_OPEN:
        return 0
    return int(allocation[SOLD_QTY])


def _refuse_overcorrected_stock(product_id: str, handed_back: int, recorded_sold: int) -> None:
    """Refuse to hand back more than this event has recorded as sold on one product."""
    if handed_back > recorded_sold:
        _refuse_insufficient_stock(product_id, handed_back, recorded_sold)


def sale_immediate_movement_action(
    *,
    event_row: Mapping[str, Any],
    sale_id: str,
    change: SaleStockChange,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
    inventory_version: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """The one audit row for one product's immediate handoff (§5.8, §8.6).

    ``EVENT_IMMEDIATE_SALE`` is allowed to move exactly the deltas this writes: physical
    stock and the event's assigned total both move by the quantity handed over, and the
    builder refuses any delta the type does not own, so a sale cannot claim a custody or
    sold-in-possession effect it did not make. The movement names both the event and the
    sale, which is what makes "which sale took this unit" answerable from the trail, and
    it names the balance version the same transaction produced — §5.8 makes
    ``inventoryVersion`` non-null exactly when a position row moved, and one did.
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=inventory_models.new_inventory_movement_id(),
        unit_campaign_id=str(event_row[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        product_id=change.product_id,
        movement_type=change.movement_type,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        kernel_physical_delta=change.physical_delta,
        assigned_delta=-change.immediate_delta,
        show_and_sell_id=str(event_row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        sale_id=sale_id,
        inventory_version=inventory_version,
    )
    return inventory_models.put_inventory_movement_action(item)


def sale_allocation_action(
    change: SaleStockChange, allocation: Mapping[str, Any], updated_at: str
) -> Tuple[str, Dict[str, Any]]:
    """Write one product's allocation after an immediate sale, pinned to the read version.

    ``soldQty`` and ``remainingQty`` move as the pair the planner computed, never as two
    independent read-modify-writes: the allocation is the event's own claim on stock, and
    a row whose sold and remaining quantities came from different moments would stop
    reconciling against ``allocatedQty``. The version pin is the race guard — an
    assignment or another sale that moved this product after this request read it cancels
    the whole transaction — and ``allocatedQty >= :guardSold`` states §5.11's invariant in
    the database rather than only in the planner, so a hand-written allocation cannot let
    a sale sell more than the event was given.
    """
    return _versioned_update(
        {"pk": str(allocation["pk"]), "sk": str(allocation["sk"])},
        tables.inventory.table_name,
        expected_version=change.allocation_version,
        sets={
            SOLD_QTY: change.new_sold_qty,
            REMAINING_QTY: change.new_remaining_qty,
            VERSION_ATTRIBUTE: change.allocation_version + 1,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        version_attribute=VERSION_ATTRIBUTE,
        extra_conditions=((":guardSold", f"#{ALLOCATED_QTY} >= :guardSold", change.new_sold_qty, (ALLOCATED_QTY,)),),
    )


def we_owe_release_movement_action(
    *,
    unit_campaign_id: str,
    product_id: str,
    we_owe_id: str,
    release_qty: int,
    inventory_version: int,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row for a reservation this correction or void had to let go (§8.6.1).

    ``WE_OWE_RELEASE`` moves exactly ``soldPossessionDelta`` and must name the obligation
    it released, so the trail says which buyer's reservation stopped holding those units.
    The movement is written whenever the corrected remainder is smaller than the
    reservation — including when it reaches zero, which is SALE-M-03-02's "no reservation
    may remain after corrected remaining quantity reaches zero".
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=inventory_models.new_inventory_movement_id(),
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        movement_type=inventory_models.WE_OWE_RELEASE,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        sold_possession_delta=-release_qty,
        we_owe_id=we_owe_id,
        inventory_version=inventory_version,
    )
    return inventory_models.put_inventory_movement_action(item)


def we_owe_reserve_movement_action(
    *,
    unit_campaign_id: str,
    product_id: str,
    we_owe_id: str,
    reserve_qty: int,
    inventory_version: int,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row for stock a Unit set aside for one buyer's obligation (§4.4.2).

    ``WE_OWE_RESERVE`` moves only ``soldPossessionDelta``: the Kernels stay physically in the
    Unit's possession and leave sellable/unassigned stock, which is the whole of OWE-04. The
    movement names the obligation, so a reader can see whose reservation those units are.
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=inventory_models.new_inventory_movement_id(),
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        movement_type=inventory_models.WE_OWE_RESERVE,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        sold_possession_delta=reserve_qty,
        we_owe_id=we_owe_id,
        inventory_version=inventory_version,
    )
    return inventory_models.put_inventory_movement_action(item)


def we_owe_fulfill_movement_action(
    *,
    unit_campaign_id: str,
    product_id: str,
    we_owe_id: str,
    fulfillment_id: str,
    movement_id: str,
    quantity: int,
    inventory_version: int,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
) -> Tuple[str, Dict[str, Any]]:
    """The stock leaving the Kernel for a buyer who was owed it (§4.4.3, OWE-07).

    Kernel physical on hand and sold-product-in-our-possession go down together — the unit
    was already counted as sold to this buyer, and now it has also left the shelf. The
    movement names both the obligation and the fulfillment record it belongs to, which is
    the pairing §5.15 requires and the reason the two rows can be reconciled in either
    direction. An ``EXTERNAL_COUNCIL`` fulfillment writes no movement at all: nothing the
    Unit owns moved.
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=movement_id,
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        movement_type=inventory_models.WE_OWE_FULFILL,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        kernel_physical_delta=-quantity,
        sold_possession_delta=-quantity,
        we_owe_id=we_owe_id,
        fulfillment_id=fulfillment_id,
        inventory_version=inventory_version,
    )
    return inventory_models.put_inventory_movement_action(item)


# --- We Owe reservation and fulfillment arithmetic (§4.4.2, §4.4.3, §10) -----------


def we_owe_reservation_targets(
    row: Mapping[str, Any],
    target_reserved_qty: Any,
    *,
    unassigned_qty: int,
) -> WeOweTarget:
    """Where one obligation's reservation moves to, and what that hands back.

    A reservation is a target rather than a delta, so the arithmetic is "what does this
    obligation hold afterwards", and the three refusals are the three ways a target can be
    wrong:

    * above what the obligation still owes — the Unit would hold stock for a quantity nobody
      was promised (``0 <= reservedQty <= remainingQty``, §5.15);
    * above the campaign's unassigned stock — the same units would be promised to this buyer
      and still sit in an event's allocation or another buyer's reservation (OWE-04);
    * on a closed obligation — nothing is owed and nothing is held, so there is nothing for
      stock to be reserved against.

    Releasing is the same write with a lower target: the released quantity goes back to
    sellable stock through ``WE_OWE_RELEASE``, and a target of zero is how a Unit lets go of
    a whole reservation. Nothing here ever raises a reservation on its own — new receipts
    never reserve stock for an old obligation (OWE-05), and an obligation with no stock held
    against it simply reports that quantity as uncovered.
    """
    _require_open_obligation(row)
    original = int(row[ORIGINAL_QTY_ATTRIBUTE])
    fulfilled = int(row[FULFILLED_QTY_ATTRIBUTE])
    cancelled = int(row[CANCELLED_QTY_ATTRIBUTE])
    reserved = int(row[RESERVED_QTY_ATTRIBUTE])
    remaining = original - fulfilled - cancelled
    target = normalize_reservation_target(target_reserved_qty)
    if target > remaining:
        _refuse(
            RESERVATION_ABOVE_REMAINING,
            f"Only {remaining} of this obligation is still owed; a reservation cannot hold more than that.",
            we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
            remainingQty=remaining,
            requestedQty=target,
        )
    increase = target - reserved
    if increase > unassigned_qty:
        _refuse(
            RESERVATION_ABOVE_UNASSIGNED,
            f"Only {unassigned_qty} unassigned kernels are available for this product; "
            f"reserving {increase} more would take stock already assigned to an event or reserved elsewhere.",
            we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
            unassignedQty=unassigned_qty,
            requestedIncrease=increase,
        )
    closed = remaining == 0 and target == 0
    return WeOweTarget(
        we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
        line_item_id=str(row[LINE_ITEM_ID_ATTRIBUTE]),
        fulfilled_qty=fulfilled,
        cancelled_qty=cancelled,
        reserved_qty=target,
        remaining_qty=remaining,
        uncovered_qty=remaining - target,
        status=WE_OWE_STATUS_CLOSED if closed else WE_OWE_STATUS_OPEN,
        close_reason=(WE_OWE_CLOSE_CANCELLED if cancelled else WE_OWE_CLOSE_FULFILLED) if closed else None,
        release_qty=reserved - target if target < reserved else 0,
        changed=target != reserved,
    )


@dataclass(frozen=True)
class WeOweFulfillmentTarget:
    """One fulfillment: the obligation's target quantities, and exactly what moved.

    ``kernel_physical_delta`` and ``sold_possession_delta`` are the source-specific stock
    effect, stated as numbers rather than as a flag so the resolver cannot apply the wrong
    one: ``KERNEL_STOCK`` moves both by the delivered quantity and ``EXTERNAL_COUNCIL``
    moves neither. ``inventory_movement_id`` is present only for ``KERNEL_STOCK``, and it is
    minted here so the movement row and the fulfillment record can name each other (§5.15).

    The reserved quantity that a Kernel fulfillment consumes is not in ``release_qty``: the
    ``WE_OWE_FULFILL`` movement already carries the possession decrement, and writing a second
    ``WE_OWE_RELEASE`` for the same units would take them out of possession twice.
    """

    target: WeOweTarget
    fulfillment_id: str
    source: str
    quantity: int
    inventory_movement_id: Optional[str]
    kernel_physical_delta: int
    sold_possession_delta: int


def we_owe_fulfillment_targets(row: Mapping[str, Any], quantity: Any, source: Any) -> WeOweFulfillmentTarget:
    """One partial fulfillment's targets, per source (§4.4.3, OWE-07, OWE-09).

    ``KERNEL_STOCK`` may only reach the quantity stock is actually held against, and
    ``EXTERNAL_COUNCIL`` only the quantity that is not covered by a reservation. That second
    bound is the reason a covered portion has to be released before the Council supplies it:
    a Council delivering a unit the Kernel has already set aside for this same buyer would
    leave the reservation holding stock against an obligation that no longer owes anything,
    and OWE-07 requires every reserved quantity to be fulfilled or explicitly released
    before the obligation is resolved.

    The obligation closes only when the write leaves nothing owed and nothing held, and the
    close reason says which of the two endings happened. A fulfillment that leaves either
    nonzero leaves the obligation open, which is what makes partial fulfillment the normal
    case rather than a special one.
    """
    _require_open_obligation(row)
    kind = normalize_we_owe_source(source)
    amount = normalize_fulfillment_qty(quantity)
    original = int(row[ORIGINAL_QTY_ATTRIBUTE])
    fulfilled = int(row[FULFILLED_QTY_ATTRIBUTE])
    cancelled = int(row[CANCELLED_QTY_ATTRIBUTE])
    reserved = int(row[RESERVED_QTY_ATTRIBUTE])
    remaining = original - fulfilled - cancelled
    uncovered = remaining - reserved
    obligation_id = str(row[WE_OWE_ID_ATTRIBUTE])
    if amount > remaining:
        _refuse(
            FULFILLMENT_ABOVE_REMAINING,
            f"This obligation owes {remaining} more; {amount} cannot be fulfilled against it.",
            we_owe_id=obligation_id,
            remainingQty=remaining,
            requestedQty=amount,
        )
    if kind == WE_OWE_SOURCE_KERNEL:
        if amount > reserved:
            _refuse(
                FULFILLMENT_ABOVE_RESERVED,
                f"Only {reserved} kernels are reserved for this obligation; fulfill Kernel stock up to that "
                "or record the rest as EXTERNAL_COUNCIL.",
                we_owe_id=obligation_id,
                reservedQty=reserved,
                requestedQty=amount,
            )
        physical_delta = -amount
        possession_delta = -amount
        new_reserved = reserved - amount
        movement_id: Optional[str] = inventory_models.new_inventory_movement_id()
    else:
        if amount > uncovered:
            _refuse(
                FULFILLMENT_ABOVE_UNCOVERED,
                f"Only {uncovered} of this obligation is uncovered; release the reservation on the covered "
                "portion before a Council supplies it.",
                we_owe_id=obligation_id,
                uncoveredQty=uncovered,
                requestedQty=amount,
            )
        physical_delta = 0
        possession_delta = 0
        new_reserved = reserved
        movement_id = None
    new_fulfilled = fulfilled + amount
    target_remaining = original - new_fulfilled - cancelled
    closed = target_remaining == 0 and new_reserved == 0
    target = WeOweTarget(
        we_owe_id=obligation_id,
        line_item_id=str(row[LINE_ITEM_ID_ATTRIBUTE]),
        fulfilled_qty=new_fulfilled,
        cancelled_qty=cancelled,
        reserved_qty=new_reserved,
        remaining_qty=target_remaining,
        uncovered_qty=target_remaining - new_reserved,
        status=WE_OWE_STATUS_CLOSED if closed else WE_OWE_STATUS_OPEN,
        close_reason=WE_OWE_CLOSE_FULFILLED if closed else None,
        # The reserved decrement rides on the WE_OWE_FULFILL movement, never a second release.
        release_qty=0,
        changed=True,
    )
    return WeOweFulfillmentTarget(
        target=target,
        fulfillment_id=new_fulfillment_id(),
        source=kind,
        quantity=amount,
        inventory_movement_id=movement_id,
        kernel_physical_delta=physical_delta,
        sold_possession_delta=possession_delta,
    )


def _require_open_obligation(row: Mapping[str, Any]) -> None:
    """Refuse a reservation or fulfillment against an obligation that has closed.

    A CLOSED row owes nothing and holds nothing (§5.15's pair), so a write that moved either
    number would create quantity out of an audit fact. The refusal says so rather than
    reporting a version conflict: nothing raced this caller, the obligation is simply over.
    """
    if str(row.get(STATUS_ATTRIBUTE) or "") != WE_OWE_STATUS_CLOSED:
        return
    _refuse(
        WE_OWE_OBLIGATION_CLOSED,
        "This obligation is closed: it owes nothing and has no stock held against it.",
        we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
        closeReason=str(row.get(CLOSE_REASON_ATTRIBUTE) or ""),
    )


# --- We Owe correction arithmetic (§8.6.1 step 3) -----------------------------------


@dataclass(frozen=True)
class WeOweTarget:
    """Where one original obligation's quantities move to, and what that releases.

    The numbers are the §8.6.1 equations, not a delta to apply: an original obligation's
    quantity is never rewritten upward (an increase is a supplemental line and a
    supplemental obligation), and a correction may only take back the unfulfilled
    portion. ``release_qty`` is the reservation that no longer has anything owed under
    it, and it is released in the same operation as the target write.
    """

    we_owe_id: str
    line_item_id: str
    fulfilled_qty: int
    cancelled_qty: int
    reserved_qty: int
    remaining_qty: int
    uncovered_qty: int
    status: str
    close_reason: Optional[str]
    release_qty: int
    changed: bool


def we_owe_correction_targets(row: Mapping[str, Any], corrected_line_qty: int) -> WeOweTarget:
    """Compute one original obligation's corrected targets and refuse an impossible one.

    ``corrected_line_qty`` is the We Owe quantity the corrected sale assigns to the line
    this obligation came from — zero when the line was omitted from the correction, or
    when the whole sale is voided. The guard ``fulfilledQty <= correctedLineQty <=
    originalQty`` is the whole of "no line may reduce We Owe below already fulfilled
    quantity" and "an increase is entered as a supplemental obligation": both refusals
    say which, because an admin who is refused for the first reason has a decision to
    make (the Unit owes that buyer for a reason) and one who is refused for the second
    just needs to add a line.
    """
    original = int(row[ORIGINAL_QTY_ATTRIBUTE])
    fulfilled = int(row[FULFILLED_QTY_ATTRIBUTE])
    reserved = int(row[RESERVED_QTY_ATTRIBUTE])
    owed = normalize_quantity(corrected_line_qty, "correctedLineQty")
    if owed < fulfilled:
        raise _refuse(
            FULFILLED_WE_OWE_PROTECTED,
            f"This line already has {fulfilled} fulfilled; a correction or void cannot take back stock the buyer has (SALE-M-03-02).",
            we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
            fulfilledQty=fulfilled,
            requestedQty=owed,
        )
    if owed > original:
        raise _invalid(
            WE_OWE_QTY_ATTRIBUTE,
            f"an existing line's We Owe quantity cannot exceed the {original} it was entered with; add a new line for more",
        )
    target_remaining = owed - fulfilled
    target_cancelled = original - fulfilled - target_remaining
    target_reserved = min(reserved, target_remaining)
    release = reserved - target_reserved
    closed = target_remaining == 0 and target_reserved == 0
    return WeOweTarget(
        we_owe_id=str(row[WE_OWE_ID_ATTRIBUTE]),
        line_item_id=str(row[LINE_ITEM_ID_ATTRIBUTE]),
        fulfilled_qty=fulfilled,
        cancelled_qty=target_cancelled,
        reserved_qty=target_reserved,
        remaining_qty=target_remaining,
        uncovered_qty=target_remaining - target_reserved,
        status=WE_OWE_STATUS_CLOSED if closed else WE_OWE_STATUS_OPEN,
        close_reason=(WE_OWE_CLOSE_CANCELLED if target_cancelled else WE_OWE_CLOSE_FULFILLED) if closed else None,
        release_qty=release,
        changed=(
            target_cancelled != int(row[CANCELLED_QTY_ATTRIBUTE])
            or target_reserved != reserved
            or target_remaining != int(row[REMAINING_QTY_ATTRIBUTE])
        ),
    )


def we_owe_update_action(
    *,
    row: Mapping[str, Any],
    target: WeOweTarget,
    updated_at: str,
    fulfilled_qty: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Write one obligation's target quantities, pinned to the version this request read.

    Every quantity the target names is written as an absolute value rather than an
    increment, and the condition pins ``version`` to what was read: a reservation that
    landed after this read cancels the whole sale correction rather than being quietly
    over-written by it. ``closeReason`` and ``closedAt`` are set only when the obligation
    closes, and removed when a reopened edit leaves it open again, so "closed for a
    reason" and "not closed" stay distinguishable on the read.

    ``fulfilled_qty`` is the fulfillment path's one extra term (§4.4.3): a correction never
    moves a fulfilled quantity — §8.6.1 keeps it historical — so the parameter is absent
    there and present only for the write that delivered something.
    """
    expected_version = int(row[VERSION_ATTRIBUTE])
    sets: Dict[str, Any] = {
        CANCELLED_QTY_ATTRIBUTE: target.cancelled_qty,
        RESERVED_QTY_ATTRIBUTE: target.reserved_qty,
        REMAINING_QTY_ATTRIBUTE: target.remaining_qty,
        UNCOVERED_QTY_ATTRIBUTE: target.uncovered_qty,
        STATUS_ATTRIBUTE: target.status,
        VERSION_ATTRIBUTE: expected_version + 1,
        UPDATED_AT_ATTRIBUTE: updated_at,
    }
    if fulfilled_qty is not None:
        sets[FULFILLED_QTY_ATTRIBUTE] = normalize_quantity(fulfilled_qty, FULFILLED_QTY_ATTRIBUTE)
    removes: List[str] = []
    if target.close_reason is None:
        removes.extend([CLOSE_REASON_ATTRIBUTE, CLOSED_AT_ATTRIBUTE])
    else:
        sets[CLOSE_REASON_ATTRIBUTE] = normalize_we_owe_close_reason(target.close_reason)
        sets[CLOSED_AT_ATTRIBUTE] = updated_at
    return _versioned_update(
        we_owe_key(str(row[SHOW_AND_SELL_ID_ATTRIBUTE]), target.we_owe_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets=sets,
        removes=removes,
        version_attribute=VERSION_ATTRIBUTE,
    )


# --- Write actions ------------------------------------------------------------------


def _sets_expression(
    sets: Mapping[str, Any],
    removes: Sequence[str],
    names: Dict[str, str],
    values: Dict[str, Any],
) -> str:
    """Build the SET/REMOVE clause, folding null-valued sets into the removes.

    DynamoDB cannot bind a null for the list and map shapes this write carries, so a
    ``None`` here is not "set it to nothing" — it is "the row must not carry the
    attribute at all" (§5.14). Names and values register in the caller's shared maps as
    they are built, because the version pin and any extra condition live in the same
    expression document.
    """
    set_parts: List[str] = []
    removed: List[str] = list(removes)
    for attribute, value in sets.items():
        if value is None:
            removed.append(attribute)
            continue
        names[f"#{attribute}"] = attribute
        values[f":{attribute}"] = value
        set_parts.append(f"#{attribute} = :{attribute}")
    parts: List[str] = []
    if set_parts:
        parts.append("SET " + ", ".join(set_parts))
    if removed:
        for attribute in removed:
            names[f"#{attribute}"] = attribute
        parts.append("REMOVE " + ", ".join(f"#{attribute}" for attribute in removed))
    return " ".join(parts)


def _extra_condition_parts(
    extra_conditions: Sequence[Tuple[str, str, Any, Sequence[str]]],
    names: Dict[str, str],
    values: Dict[str, Any],
) -> List[str]:
    """The version pin first, then every extra fragment with the values and names it reads.

    Every condition states its check in its own fragment; a condition needs only the
    states it actually pins, so there is no value-only entry to skip over.
    """
    condition_parts = ["#version = :expectedVersion"]
    for placeholder, fragment, value, attribute_names in extra_conditions:
        values[placeholder] = value
        for attribute in attribute_names:
            names[f"#{attribute}"] = attribute
        condition_parts.append(fragment)
    return condition_parts


def _versioned_update(
    key: Mapping[str, str],
    table_name: str,
    *,
    expected_version: int,
    sets: Mapping[str, Any],
    version_attribute: str,
    removes: Sequence[str] = (),
    extra_conditions: Sequence[Tuple[str, str, Any, Sequence[str]]] = (),
) -> Tuple[str, Dict[str, Any]]:
    """One versioned update whose values may be a list or a map.

    :func:`src.utils.show_and_sell_models._conditioned_update` encodes through
    :func:`src.utils.mutations.wire_value`, which is scalar-only, and a sale row's
    ``lineItems`` is a list of maps and ``paymentMethodSnapshot`` is a map — the exact
    trap :func:`src.utils.show_and_sell_models.wire_item_value` exists for. Everything
    else is the same as every other Show & Sell write: the version pin is what makes a
    stale correction lose its whole transaction instead of overwriting the writer that
    won.

    A ``sets`` entry whose value is ``None`` becomes a ``REMOVE`` rather than a bound
    null: DynamoDB has no null in an ``ExpressionAttributeValues`` map for these types,
    and "this sale carries no buyer email" is a row without the attribute, not a row
    with an empty one (§5.14).

    ``extra_conditions`` carries ``(value placeholder, condition fragment, value,
    attribute names)``: the fragment names the placeholder plus any attribute it reads,
    and the names are registered so the fragment can address an attribute this write does
    not change — the allocation guard reads ``allocatedQty`` without writing it.
    """
    names: Dict[str, str] = {"#version": version_attribute}
    values: Dict[str, Any] = {":expectedVersion": expected_version}
    update_expression = _sets_expression(sets, list(removes), names, values)
    condition_parts = _extra_condition_parts(extra_conditions, names, values)
    return (
        "Update",
        {
            "TableName": table_name,
            "Key": wire_key(key),
            "UpdateExpression": update_expression,
            "ConditionExpression": " AND ".join(condition_parts),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": {name: wire_item_value(value) for name, value in values.items()},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def sale_event_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    product_ids: Sequence[str],
    updated_by_account_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """The live-state aggregate write for one sale: cumulative productIds plus the version pin.

    The product list and the sale/obligation/allocation rows it points at commit in one
    transaction (§8.4), so a sale of a product the event never held still becomes
    visible to the finalization walk that lists it. The state condition names the stored
    state a live answer derives from, not the answer itself: ``ACTIVE`` and ``ENDED`` are
    clock states the model refuses to store, so a live event's row carries ``SCHEDULED``
    and ``#status = :saleStateScheduled`` matches exactly the rows the resolver accepted
    while refusing ``FINALIZED``/``CANCELLED``/``REOPENED``. The version pin is what loses
    the race against a workflow that moved the event meanwhile; the state check is the
    sentence that says why a non-sale row cannot commit a sale.
    """
    return _versioned_update(
        event_metadata_key(show_and_sell_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={
            PRODUCT_IDS_ATTRIBUTE: list(product_ids),
            UPDATED_BY_ATTRIBUTE: normalize_sale_key_id(updated_by_account_id, UPDATED_BY_ATTRIBUTE),
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_AT_ATTRIBUTE: show_and_sell_models.normalize_moment(updated_at, UPDATED_AT_ATTRIBUTE),
        },
        removes=[],
        version_attribute=VERSION_ATTRIBUTE,
        extra_conditions=(
            (
                ":saleStateScheduled",
                "#status = :saleStateScheduled",
                show_and_sell_models.STATUS_SCHEDULED,
                (STATUS_ATTRIBUTE,),
            ),
        ),
    )


def put_sale_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Insert a first revision of a sale; the conditional insert is the replay guard.

    A sale row is written only at creation — every later change is a versioned update
    plus an archived revision child — so ``attribute_not_exists`` is what makes a retried
    create with a fresh id impossible to double-apply, and pairs with the marker that
    rides the same transaction (§8.9).
    """
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_sale_revision_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Archive one whole previous revision, and refuse to overwrite an archived one.

    The sort key carries the revision number, so two corrections that both believed they
    were archiving revision 3 cannot both write: the loser's condition fails and its
    whole transaction cancels. That is what keeps the history a single chain rather than
    two branches with the same number, and it is also the guard a replay would otherwise
    have to be trusted to avoid.
    """
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_we_owe_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Create one obligation; the conditional insert is its uniqueness guard."""
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def sale_revision_update_action(
    *,
    show_and_sell_id: str,
    sale_id: str,
    expected_revision: int,
    sets: Mapping[str, Any],
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Write one sale's new revision, pinned to the revision this request read.

    ``revision`` here is the sale's optimistic-concurrency attribute and is written as
    ``expected_revision + 1``, so a correction that raced another one loses at the write
    rather than overwriting it — the same shape as every other versioned write in Show &
    Sell, with the version attribute named for the row it guards.
    """
    values: Dict[str, Any] = dict(sets)
    values[UPDATED_AT_ATTRIBUTE] = updated_at
    return _versioned_update(
        sale_key(show_and_sell_id, sale_id),
        tables.show_and_sells.table_name,
        expected_version=expected_revision,
        sets=values,
        removes=[],
        version_attribute=REVISION_ATTRIBUTE,
    )


# --- Projections --------------------------------------------------------------------


def sale_line_payload(line: Mapping[str, Any]) -> Dict[str, Any]:
    """One stored line as the SDL's ``ShowAndSellSaleLine``, every number an ``int``.

    A row read back out of DynamoDB carries its quantities as ``Decimal``, and a payload
    holding a ``Decimal`` cannot be serialized into the idempotency marker — the answer a
    retry replays and the answer the caller first received have to be one answer, so the
    conversion happens on the way out instead of being left for each caller to remember.
    """
    return {
        LINE_ITEM_ID_ATTRIBUTE: str(line[LINE_ITEM_ID_ATTRIBUTE]),
        PRODUCT_ID_ATTRIBUTE: str(line[PRODUCT_ID_ATTRIBUTE]),
        PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: str(line[PRODUCT_NAME_SNAPSHOT_ATTRIBUTE]),
        UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: _whole(line[UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE]),
        IMMEDIATE_QTY_ATTRIBUTE: _whole(line[IMMEDIATE_QTY_ATTRIBUTE]),
        WE_OWE_QTY_ATTRIBUTE: _whole(line[WE_OWE_QTY_ATTRIBUTE]),
        SUBTOTAL_CENTS_ATTRIBUTE: _whole(line[SUBTOTAL_CENTS_ATTRIBUTE]),
    }


def sale_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One sale row as the SDL's ``ShowAndSellSale`` (§7.1).

    ``pk``/``sk``/``entityType``/``idempotencyKey`` are storage detail and never leave the
    handler; the buyer fields are part of the administrative answer because the admin who
    entered the sale is the only one who can read it, and a participant-safe projection
    of a sale does not exist (§5.14, SEC-04).
    """
    return {
        SALE_ID_ATTRIBUTE: str(row[SALE_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        UNIT_ID_ATTRIBUTE: str(row[UNIT_ID_ATTRIBUTE]),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: str(row[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        SALE_AT_ATTRIBUTE: str(row[SALE_AT_ATTRIBUTE]),
        ENTERED_BY_ATTRIBUTE: str(row[ENTERED_BY_ATTRIBUTE]),
        BUYER_NAME_ATTRIBUTE: row.get(BUYER_NAME_ATTRIBUTE),
        BUYER_PHONE_ATTRIBUTE: row.get(BUYER_PHONE_ATTRIBUTE),
        BUYER_EMAIL_ATTRIBUTE: row.get(BUYER_EMAIL_ATTRIBUTE),
        LINE_ITEMS_ATTRIBUTE: [sale_line_payload(line) for line in row[LINE_ITEMS_ATTRIBUTE]],
        TOTAL_CENTS_ATTRIBUTE: int(row[TOTAL_CENTS_ATTRIBUTE]),
        PAYMENT_SNAPSHOT_ATTRIBUTE: dict(row[PAYMENT_SNAPSHOT_ATTRIBUTE]),
        REVISION_ATTRIBUTE: int(row[REVISION_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row[STATUS_ATTRIBUTE]),
        VOIDED_BY_ATTRIBUTE: row.get(VOIDED_BY_ATTRIBUTE),
        VOIDED_AT_ATTRIBUTE: row.get(VOIDED_AT_ATTRIBUTE),
        CREATED_AT_ATTRIBUTE: _optional_text(row.get(CREATED_AT_ATTRIBUTE)),
        UPDATED_AT_ATTRIBUTE: _optional_text(row.get(UPDATED_AT_ATTRIBUTE)),
        "expectedCashCents": sale_expected_cash_cents(row),
    }


def sale_revision_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One archived revision as the SDL's ``ShowAndSellSaleRevision`` (§7.1's prior revision)."""
    return {
        SALE_ID_ATTRIBUTE: str(row[SALE_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        REVISION_ATTRIBUTE: int(row[REVISION_ATTRIBUTE]),
        SALE_AT_ATTRIBUTE: str(row[SALE_AT_ATTRIBUTE]),
        ENTERED_BY_ATTRIBUTE: str(row[ENTERED_BY_ATTRIBUTE]),
        BUYER_NAME_ATTRIBUTE: row.get(BUYER_NAME_ATTRIBUTE),
        BUYER_PHONE_ATTRIBUTE: row.get(BUYER_PHONE_ATTRIBUTE),
        BUYER_EMAIL_ATTRIBUTE: row.get(BUYER_EMAIL_ATTRIBUTE),
        LINE_ITEMS_ATTRIBUTE: [sale_line_payload(line) for line in row[LINE_ITEMS_ATTRIBUTE]],
        TOTAL_CENTS_ATTRIBUTE: int(row[TOTAL_CENTS_ATTRIBUTE]),
        PAYMENT_SNAPSHOT_ATTRIBUTE: dict(row[PAYMENT_SNAPSHOT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row[STATUS_ATTRIBUTE]),
        CORRECTED_BY_ATTRIBUTE: str(row[CORRECTED_BY_ATTRIBUTE]),
        CORRECTED_AT_ATTRIBUTE: str(row[CORRECTED_AT_ATTRIBUTE]),
        REASON_ATTRIBUTE: str(row[REASON_ATTRIBUTE]),
    }


def we_owe_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One obligation row as the SDL's ``WeOweObligation`` (§5.15).

    Every quantity is reported rather than left for the browser to derive, because the
    browser that adds ``original - fulfilled - cancelled`` itself is computing a second
    answer that can disagree with the row it was written from. There is no due date, no
    assignee, and no aging field here, by §5.15's design: the Unit prioritizes We Owe by
    looking at the list.
    """
    return {
        WE_OWE_ID_ATTRIBUTE: str(row[WE_OWE_ID_ATTRIBUTE]),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: str(row[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        SALE_ID_ATTRIBUTE: str(row[SALE_ID_ATTRIBUTE]),
        LINE_ITEM_ID_ATTRIBUTE: str(row[LINE_ITEM_ID_ATTRIBUTE]),
        BUYER_NAME_ATTRIBUTE: str(row[BUYER_NAME_ATTRIBUTE]),
        PRODUCT_ID_ATTRIBUTE: str(row[PRODUCT_ID_ATTRIBUTE]),
        PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: str(row[PRODUCT_NAME_SNAPSHOT_ATTRIBUTE]),
        ORIGINAL_QTY_ATTRIBUTE: int(row[ORIGINAL_QTY_ATTRIBUTE]),
        FULFILLED_QTY_ATTRIBUTE: int(row[FULFILLED_QTY_ATTRIBUTE]),
        CANCELLED_QTY_ATTRIBUTE: int(row[CANCELLED_QTY_ATTRIBUTE]),
        RESERVED_QTY_ATTRIBUTE: int(row[RESERVED_QTY_ATTRIBUTE]),
        REMAINING_QTY_ATTRIBUTE: int(row[REMAINING_QTY_ATTRIBUTE]),
        UNCOVERED_QTY_ATTRIBUTE: int(row[UNCOVERED_QTY_ATTRIBUTE]),
        VALUE_CENTS_SNAPSHOT_ATTRIBUTE: int(row[VALUE_CENTS_SNAPSHOT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row[STATUS_ATTRIBUTE]),
        CLOSE_REASON_ATTRIBUTE: row.get(CLOSE_REASON_ATTRIBUTE),
        VERSION_ATTRIBUTE: int(row[VERSION_ATTRIBUTE]),
        CREATED_AT_ATTRIBUTE: _optional_text(row.get(CREATED_AT_ATTRIBUTE)),
        CLOSED_AT_ATTRIBUTE: _optional_text(row.get(CLOSED_AT_ATTRIBUTE)),
    }


def _whole(value: Any) -> int:
    """A stored count or cent amount as the ``int`` the SDL answers.

    DynamoDB hands back every number as ``Decimal``; the payload types are ``Int!``, and a
    ``Decimal`` is not JSON-serializable, so a marker write that stored a payload built
    straight from a row would fail and a replay would silently re-derive the answer.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid("quantity", "must be a whole number")
    return int(value)


def _optional_text(value: Any) -> Optional[str]:
    """A stored timestamp as the SDL's nullable ``AWSDateTime``, or ``None``."""
    return None if value is None else str(value)
