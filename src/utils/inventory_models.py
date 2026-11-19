"""Inventory balances, movements, allocations, and custody rows (delivery checklist §2.1).

Stage 2 lays the four inventory records down at the physical key shapes of data
model §6.3, all on the one ``inventory`` table::

    UNIT_CAMPAIGN#<unitCampaignId> / PRODUCT#<productId>#BALANCE                              (§5.7)
    UNIT_CAMPAIGN#<unitCampaignId> / PRODUCT#<productId>#EVENT#<showAndSellId>                (§5.11)
    UNIT_CAMPAIGN#<unitCampaignId> / PRODUCT#<productId>#CUSTODY#<profileId>                  (§5.9)
    UNIT_CAMPAIGN#<unitCampaignId> / PRODUCT#<productId>#MOVEMENT#<occurredAt>#<movementId>   (§5.8)

One campaign partition is what makes "what do we have right now" a single
consistent query, and the ``PRODUCT#<productId>#`` prefix is what scopes a stock
operation to one product without leaving the partition. Because the id sits
between two ``#`` delimiters, an id that contains ``#`` would carve the sort key
and address a different row kind: every id that goes into these keys is therefore
required to be ``#``-free (:func:`normalize_inventory_id`), which is a storage
law, not an authorization rule.

The balance row is a mutable aggregate carrying a ``version``; the movement row is
append-only and carries NO ``version`` (:data:`MOVEMENT_ROW_ATTRIBUTES` never
includes one) — corrections are new linked movements, never an edit of history
(§5.8). Allocations and custody rows are the authoritative records the derived
quantities in §7 are computed FROM; nothing here stores a derived value, because
a stored copy is a second source of truth that drifts the moment a concurrent
writer moves the row it was computed from.

This module owns persistence shapes, validation, the §4 invariants, and the pure
§7 arithmetic. It answers no question about WHO may call it: authorization is the
resolvers' job (:mod:`src.handlers.unit_operations` + :mod:`src.utils.unit_auth`).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, cast

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .mutations import wire_key, wire_value
from .pagination import query_all_items
from .unit_models import MAX_ID_LENGTH, normalize_required_text

# --- Key layout (data model §6.3) ------------------------------------------------

INVENTORY_PK_PREFIX = "UNIT_CAMPAIGN"
PRODUCT_SK_PREFIX = "PRODUCT"
BALANCE_SK_SUFFIX = "BALANCE"
ALLOCATION_SK_MARKER = "EVENT"
CUSTODY_SK_MARKER = "CUSTODY"
MOVEMENT_SK_MARKER = "MOVEMENT"

# --- Enums (data model §4, §5.8, §5.11) ------------------------------------------

RECEIPT = "RECEIPT"
STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
COUNCIL_ON_ORDER_ADJUST = "COUNCIL_ON_ORDER_ADJUST"
EVENT_ASSIGN = "EVENT_ASSIGN"
EVENT_MANUAL_REDUCE = "EVENT_MANUAL_REDUCE"
EVENT_AUTO_REDUCE = "EVENT_AUTO_REDUCE"
EVENT_IMMEDIATE_SALE = "EVENT_IMMEDIATE_SALE"
EVENT_RELEASE = "EVENT_RELEASE"
EVENT_RETURN_RECONCILE = "EVENT_RETURN_RECONCILE"
EVENT_RE_FINALIZE_ADJUST = "EVENT_RE_FINALIZE_ADJUST"
SCOUT_ISSUE = "SCOUT_ISSUE"
SCOUT_SALE_CONSUME = "SCOUT_SALE_CONSUME"
SCOUT_RETURN = "SCOUT_RETURN"
INDIVIDUAL_FULFILL = "INDIVIDUAL_FULFILL"
WE_OWE_RESERVE = "WE_OWE_RESERVE"
WE_OWE_RELEASE = "WE_OWE_RELEASE"
WE_OWE_FULFILL = "WE_OWE_FULFILL"
REVERSAL = "REVERSAL"

INVENTORY_MOVEMENT_TYPES: frozenset[str] = frozenset(
    {
        RECEIPT,
        STOCK_ADJUSTMENT,
        COUNCIL_ON_ORDER_ADJUST,
        EVENT_ASSIGN,
        EVENT_MANUAL_REDUCE,
        EVENT_AUTO_REDUCE,
        EVENT_IMMEDIATE_SALE,
        EVENT_RELEASE,
        EVENT_RETURN_RECONCILE,
        EVENT_RE_FINALIZE_ADJUST,
        SCOUT_ISSUE,
        SCOUT_SALE_CONSUME,
        SCOUT_RETURN,
        INDIVIDUAL_FULFILL,
        WE_OWE_RESERVE,
        WE_OWE_RELEASE,
        WE_OWE_FULFILL,
        REVERSAL,
    }
)

ALLOCATION_OPEN = "OPEN"
ALLOCATION_RELEASED = "RELEASED"
ALLOCATION_CANCELLED = "CANCELLED"

ALLOCATION_STATUSES: frozenset[str] = frozenset({ALLOCATION_OPEN, ALLOCATION_RELEASED, ALLOCATION_CANCELLED})

# §5.11 state machine, stated once so no caller can invent a transition. A
# RELEASED allocation is a finalization outcome and a CANCELLED one is an event
# cancellation; both are terminal — "CANCELLED is the allocation's terminal state
# for event cancellation; RELEASED is reserved for finalization release" — and a
# reopened event gets a NEW allocation record rather than a resurrected one.
ALLOCATION_TRANSITIONS: dict[str, frozenset[str]] = {
    ALLOCATION_OPEN: frozenset({ALLOCATION_RELEASED, ALLOCATION_CANCELLED}),
    ALLOCATION_RELEASED: frozenset(),
    ALLOCATION_CANCELLED: frozenset(),
}

# --- Attribute names (data model §5.7-§5.9, §5.11) --------------------------------

KERNEL_PHYSICAL_QTY = "kernelPhysicalQty"
SOLD_IN_POSSESSION_QTY = "soldInPossessionQty"
COUNCIL_ON_ORDER_QTY = "councilOnOrderQty"
WITH_SCOUT_QTY = "withScoutQty"
ALLOCATED_QTY = "allocatedQty"
SOLD_QTY = "soldQty"
RELEASED_QTY = "releasedQty"
REMAINING_QTY = "remainingQty"

VERSION_ATTRIBUTE = "version"
CREATED_AT_ATTRIBUTE = "createdAt"
UPDATED_AT_ATTRIBUTE = "updatedAt"
ENTITY_TYPE_ATTRIBUTE = "entityType"

# The three balance-shaped rows one product prefix holds, plus the audit trail that
# shares it (§5.7, §5.9, §5.11). A read that buckets a partition by these values is
# how a position is assembled without a second round trip per row kind.
BALANCE_ENTITY_TYPE = "InventoryBalance"
CUSTODY_ENTITY_TYPE = "ScoutCustodyBalance"
ALLOCATION_ENTITY_TYPE = "EventInventoryAllocation"
MOVEMENT_ENTITY_TYPE = "InventoryMovement"

_SECTION_BY_ENTITY_TYPE: dict[str, str] = {
    BALANCE_ENTITY_TYPE: "balance",
    ALLOCATION_ENTITY_TYPE: "allocations",
    CUSTODY_ENTITY_TYPE: "custody",
}
UNIT_CAMPAIGN_ID_ATTRIBUTE = "unitCampaignId"
PRODUCT_ID_ATTRIBUTE = "productId"
PROFILE_ID_ATTRIBUTE = "profileId"
CAMPAIGN_ID_ATTRIBUTE = "campaignId"
SHOW_AND_SELL_ID_ATTRIBUTE = "showAndSellId"

#: The state attribute of an allocation or custody-shaped row (§9.2). It shares a name
#: with the event's own ``status``, and that is deliberate: :func:`_status` and
#: :func:`normalize_allocation_status` both read it, and a second spelling of the same
#: attribute is how a filter starts matching nothing.
STATUS_ATTRIBUTE = "status"

BALANCE_QUANTITY_ATTRIBUTES: frozenset[str] = frozenset(
    {KERNEL_PHYSICAL_QTY, SOLD_IN_POSSESSION_QTY, COUNCIL_ON_ORDER_QTY}
)
CUSTODY_QUANTITY_ATTRIBUTES: frozenset[str] = frozenset({WITH_SCOUT_QTY})
ALLOCATION_QUANTITY_ATTRIBUTES: frozenset[str] = frozenset({ALLOCATED_QTY, SOLD_QTY, RELEASED_QTY, REMAINING_QTY})

KERNEL_PHYSICAL_DELTA = "kernelPhysicalDelta"
SOLD_POSSESSION_DELTA = "soldPossessionDelta"
WITH_SCOUT_DELTA = "withScoutDelta"
ASSIGNED_DELTA = "assignedDelta"
COUNCIL_ON_ORDER_DELTA = "councilOnOrderDelta"

MOVEMENT_DELTA_ATTRIBUTES: frozenset[str] = frozenset(
    {
        KERNEL_PHYSICAL_DELTA,
        SOLD_POSSESSION_DELTA,
        WITH_SCOUT_DELTA,
        ASSIGNED_DELTA,
        COUNCIL_ON_ORDER_DELTA,
    }
)

MOVEMENT_ID_ATTRIBUTE = "movementId"
MOVEMENT_TYPE_ATTRIBUTE = "movementType"
SALE_ID_ATTRIBUTE = "saleId"
ORDER_ID_ATTRIBUTE = "orderId"
WE_OWE_ID_ATTRIBUTE = "weOweId"
FULFILLMENT_ID_ATTRIBUTE = "fulfillmentId"
FINALIZATION_ID_ATTRIBUTE = "finalizationId"
REASON_ATTRIBUTE = "reason"
ACTOR_ACCOUNT_ID_ATTRIBUTE = "actorAccountId"
OCCURRED_AT_ATTRIBUTE = "occurredAt"
INVENTORY_VERSION_ATTRIBUTE = "inventoryVersion"
IDEMPOTENCY_KEY_ATTRIBUTE = "idempotencyKey"

#: Which delta attributes each movement type is allowed to move (§5.8's meaning of
#: each type). A movement carrying a delta its type does not own is a silent second
#: path into a balance — the row would claim a stock effect the operation never
#: made — so the builder refuses it rather than storing an audit record that lies.
MOVEMENT_ALLOWED_DELTAS: dict[str, frozenset[str]] = {
    RECEIPT: frozenset({KERNEL_PHYSICAL_DELTA}),
    STOCK_ADJUSTMENT: frozenset({KERNEL_PHYSICAL_DELTA}),
    COUNCIL_ON_ORDER_ADJUST: frozenset({COUNCIL_ON_ORDER_DELTA}),
    EVENT_ASSIGN: frozenset({ASSIGNED_DELTA}),
    EVENT_MANUAL_REDUCE: frozenset({ASSIGNED_DELTA}),
    EVENT_AUTO_REDUCE: frozenset({ASSIGNED_DELTA}),
    EVENT_IMMEDIATE_SALE: frozenset({KERNEL_PHYSICAL_DELTA, WITH_SCOUT_DELTA, ASSIGNED_DELTA}),
    EVENT_RELEASE: frozenset({ASSIGNED_DELTA}),
    EVENT_RETURN_RECONCILE: frozenset({KERNEL_PHYSICAL_DELTA, ASSIGNED_DELTA}),
    EVENT_RE_FINALIZE_ADJUST: frozenset({KERNEL_PHYSICAL_DELTA, ASSIGNED_DELTA}),
    SCOUT_ISSUE: frozenset({KERNEL_PHYSICAL_DELTA, WITH_SCOUT_DELTA}),
    SCOUT_SALE_CONSUME: frozenset({WITH_SCOUT_DELTA}),
    SCOUT_RETURN: frozenset({KERNEL_PHYSICAL_DELTA, WITH_SCOUT_DELTA}),
    INDIVIDUAL_FULFILL: frozenset({KERNEL_PHYSICAL_DELTA, WITH_SCOUT_DELTA}),
    WE_OWE_RESERVE: frozenset({SOLD_POSSESSION_DELTA}),
    WE_OWE_RELEASE: frozenset({SOLD_POSSESSION_DELTA}),
    WE_OWE_FULFILL: frozenset({KERNEL_PHYSICAL_DELTA, SOLD_POSSESSION_DELTA}),
    # A reversal mirrors whatever the reversed movement moved, so no delta set can
    # be stated for it; the caller that writes the reversal is the one that knows
    # the original movement's shape.
    REVERSAL: frozenset(MOVEMENT_DELTA_ATTRIBUTES),
}

#: The source link each movement type must name (§5.8's "when applicable" made
#: checkable). An event movement with no event, or a custody movement with no
#: Scout, is an audit record that cannot be traced to what it came from.
MOVEMENT_REQUIRED_LINKS: dict[str, frozenset[str]] = {
    RECEIPT: frozenset(),
    STOCK_ADJUSTMENT: frozenset(),
    COUNCIL_ON_ORDER_ADJUST: frozenset(),
    EVENT_ASSIGN: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    EVENT_MANUAL_REDUCE: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    EVENT_AUTO_REDUCE: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    EVENT_IMMEDIATE_SALE: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE, SALE_ID_ATTRIBUTE}),
    EVENT_RELEASE: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    EVENT_RETURN_RECONCILE: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    EVENT_RE_FINALIZE_ADJUST: frozenset({SHOW_AND_SELL_ID_ATTRIBUTE}),
    # Issuing to a Scout and taking stock back are custody acts, not event acts
    # (spec CUST-01, CUST-06): stock moves from the Kernel's shelf to the Scout's
    # trunk outside any Show & Sell, so the Scout is the only source the row can
    # name. Requiring an event here would leave the two operations that create and
    # undo a custody with nothing legal to write.
    SCOUT_ISSUE: frozenset({PROFILE_ID_ATTRIBUTE}),
    SCOUT_SALE_CONSUME: frozenset({PROFILE_ID_ATTRIBUTE, SALE_ID_ATTRIBUTE}),
    SCOUT_RETURN: frozenset({PROFILE_ID_ATTRIBUTE}),
    INDIVIDUAL_FULFILL: frozenset({ORDER_ID_ATTRIBUTE, FULFILLMENT_ID_ATTRIBUTE}),
    WE_OWE_RESERVE: frozenset({WE_OWE_ID_ATTRIBUTE}),
    WE_OWE_RELEASE: frozenset({WE_OWE_ID_ATTRIBUTE}),
    WE_OWE_FULFILL: frozenset({WE_OWE_ID_ATTRIBUTE, FULFILLMENT_ID_ATTRIBUTE}),
    REVERSAL: frozenset({FULFILLMENT_ID_ATTRIBUTE}),
}

#: Every attribute a movement row may carry. A ``version`` attribute here would
#: turn an append-only audit record into a mutable aggregate, so this set is the
#: append-only contract in data form (:func:`movement_row_violations`).
MOVEMENT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        ENTITY_TYPE_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        MOVEMENT_ID_ATTRIBUTE,
        PRODUCT_ID_ATTRIBUTE,
        MOVEMENT_TYPE_ATTRIBUTE,
        PROFILE_ID_ATTRIBUTE,
        SHOW_AND_SELL_ID_ATTRIBUTE,
        SALE_ID_ATTRIBUTE,
        ORDER_ID_ATTRIBUTE,
        WE_OWE_ID_ATTRIBUTE,
        FULFILLMENT_ID_ATTRIBUTE,
        FINALIZATION_ID_ATTRIBUTE,
        REASON_ATTRIBUTE,
        ACTOR_ACCOUNT_ID_ATTRIBUTE,
        OCCURRED_AT_ATTRIBUTE,
        INVENTORY_VERSION_ATTRIBUTE,
        IDEMPOTENCY_KEY_ATTRIBUTE,
    }
    | MOVEMENT_DELTA_ATTRIBUTES
)

# --- Limits (API contract §3.1, §3.4) --------------------------------------------

MAX_QUANTITY = 1_000_000
MAX_REASON_LENGTH = 500
MAX_DATE_RANGE_DAYS = 366
MAX_POSITION_PRODUCT_IDS = 15

_MOMENT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def _invalid(field: str, rule: str) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


# --- Normalization and validation ------------------------------------------------


def new_inventory_movement_id() -> str:
    """A stable movement identity, generated before the write (§5.8).

    The id rides in the movement's sort key, so it must exist before the row is
    addressed — and it is a UUID rather than a counter, because two concurrent
    movements for one product must not collide on a key the writer guessed.
    """
    return str(uuid.uuid4())


def normalize_inventory_id(value: Any, field: str) -> str:
    """Validate an id that will sit inside a composite sort key (§6.3).

    A ``#`` INSIDE an id is allowed, because that is how this application already
    spells them: a catalog product is ``<catalogId>#prod-N`` and a Scout profile is
    ``PROFILE#<uuid>``. Refusing ``#`` would make the inventory surface unable to
    name the products it exists to count. What is refused is an EMPTY segment — a
    leading, trailing, or doubled ``#`` — because the sort-key markers are
    ``#``-delimited and an empty segment lets two different rows collide on one key.
    A key whose product segment could be ambiguous is resolved by reading the row's
    own ``productId`` attribute, never by splitting its sort key.
    """
    text = normalize_required_text(value, field, MAX_ID_LENGTH)
    if "#" in text:
        if text.startswith("#") or text.endswith("#") or "##" in text:
            raise _invalid(field, "must not contain an empty # segment")
    return text


def _integer(value: Any, field: str) -> int:
    """Read an integer in either spelling a value arrives in.

    ``Decimal`` is what a DynamoDB read returns and ``int`` is what GraphQL gives
    a caller; ``bool`` is refused on purpose, because a Python bool IS an int and
    would store a quantity of 0 or 1 from a caller that meant a flag.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid(field, "must be an integer")
    try:
        return int(value)
    except ArithmeticError, ValueError:
        raise _invalid(field, "must be an integer") from None


def normalize_quantity(value: Any, field: str, *, minimum: int = 0) -> int:
    """Validate a quantity as an integer in ``minimum``..:data:`MAX_QUANTITY`."""
    number = _integer(value, field)
    if number < minimum:
        raise _invalid(field, f"must be at least {minimum}")
    if number > MAX_QUANTITY:
        raise _invalid(field, f"must be at most {MAX_QUANTITY}")
    return number


def normalize_signed_delta(value: Any, field: str, *, nonzero: bool) -> int:
    """Validate a signed adjustment, bounded by :data:`MAX_QUANTITY` in magnitude."""
    number = _integer(value, field)
    if abs(number) > MAX_QUANTITY:
        raise _invalid(field, f"must be between -{MAX_QUANTITY} and {MAX_QUANTITY}")
    if nonzero and number == 0:
        raise _invalid(field, "must not be zero")
    return number


def normalize_reason(value: Any, field: str, *, required: bool) -> Optional[str]:
    """Validate the audit reason (§5.8: required for manual adjustments)."""
    if value is None:
        if required:
            raise _invalid(field, "is required")
        return None
    if not isinstance(value, str):
        raise _invalid(field, "must be a string")
    text = value.strip()
    if not text:
        if required:
            raise _invalid(field, "is required")
        return None
    if len(text) > MAX_REASON_LENGTH:
        raise _invalid(field, f"must be at most {MAX_REASON_LENGTH} characters")
    return text


def normalize_moment(value: Any, field: str) -> str:
    """Canonicalize an ISO-8601 instant to the one UTC spelling every writer uses.

    Lexicographic sort is chronological only if the spelling is fixed, and
    ``occurredAt`` sits inside the movement sort key: a ``Z`` row and a
    ``+00:00`` row for the same instant would sort apart and a date filter would
    miss one of them. A zone-less value is refused rather than assumed to be UTC,
    because an assumed zone is a wrong timestamp that no later read can detect.
    """
    if not isinstance(value, str) or not _MOMENT_PATTERN.fullmatch(value.strip()):
        raise _invalid(field, "must be an ISO 8601 date-time with a time zone")
    # The pattern above is what makes the zone mandatory, so a parse that yields a
    # naive instant is not reachable here. The parse itself still has to be
    # guarded: the pattern accepts a shape like ``2026-02-30``, which no calendar
    # has.
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise _invalid(field, "must be an ISO 8601 date-time with a time zone") from None
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_date_range(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Validate a ``DateRangeFilter``: end after start, at most 366 days wide.

    The cap is a read-cost and correctness rule, not a UI preference (§3.1): the
    movement history is one partition per campaign, and an unbounded range turns
    an audit screen into a full-partition scan.
    """
    if value is None:
        return (None, None)
    if not isinstance(value, Mapping):
        raise _invalid("dateRange", "must be an object")
    start_at = None if value.get("startAt") is None else normalize_moment(value["startAt"], "dateRange.startAt")
    end_at = None if value.get("endAt") is None else normalize_moment(value["endAt"], "dateRange.endAt")
    if start_at is not None and end_at is not None:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
        if end <= start:
            raise _invalid("dateRange.endAt", "must be after dateRange.startAt")
        if end - start > timedelta(days=MAX_DATE_RANGE_DAYS):
            raise _invalid("dateRange", f"must span at most {MAX_DATE_RANGE_DAYS} days")
    return (start_at, end_at)


def normalize_product_ids(value: Any) -> List[str]:
    """Validate the optional ``productIds`` position filter (max 15, no duplicates).

    The cap bounds the read: one position query per product, so 15 products is the
    widest single call the API contract allows (§4.1 ``INV-Q-01-02``).
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise _invalid("productIds", "must be a list of product ids")
    ids = [normalize_inventory_id(item, "productIds") for item in value]
    if len(ids) > MAX_POSITION_PRODUCT_IDS:
        raise _invalid("productIds", f"must contain at most {MAX_POSITION_PRODUCT_IDS} products")
    if len(set(ids)) != len(ids):
        raise _invalid("productIds", "must not repeat a product")
    return ids


def normalize_return_items(value: Any) -> list[tuple[str, int]]:
    """Validate a ``returnStockFromScout`` batch: (productId, quantity) pairs.

    Three rules the atomic return depends on (§2.3.2):

    - non-empty — an empty batch is a click that would write a marker and a
      movement for nothing, and the caller would be told its return succeeded;
    - a positive quantity per product — a return of zero or a negative quantity is
      an issue wearing a return's clothes, and the movement type would lie;
    - no repeated product — one custody row per (product, Scout), so two entries
      for one product are two writes to the same row, which DynamoDB forbids in one
      transaction anyway. Rejecting the request is the honest answer.

    The pairs come back in the order the caller sent them: the batch's movements and
    its result follow that order, which is what makes a retry of a committed return
    answer with the same list.
    """
    if not isinstance(value, (list, tuple)) or not value:
        raise _invalid("items", "must contain at least one product to return")
    items: list[tuple[str, int]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise _invalid("items", "each item needs a productId and a quantity")
        product_id = normalize_inventory_id(entry.get("productId"), "productId")
        quantity = normalize_quantity(entry.get("quantity"), "quantity", minimum=1)
        items.append((product_id, quantity))
    if len({product_id for product_id, _quantity in items}) != len(items):
        raise _invalid("items", "must not repeat a product")
    return items


def normalize_movement_type(value: Any, field: str = "movementType") -> str:
    """Validate an ``InventoryMovementType`` (§5.8 closed set)."""
    if not isinstance(value, str) or value not in INVENTORY_MOVEMENT_TYPES:
        raise _invalid(field, "must be a known inventory movement type")
    return value


def normalize_allocation_status(value: Any, field: str = "status") -> str:
    """Validate an ``AllocationStatus`` (§4: OPEN / RELEASED / CANCELLED)."""
    if not isinstance(value, str) or value not in ALLOCATION_STATUSES:
        raise _invalid(field, "must be OPEN, RELEASED, or CANCELLED")
    return value


def require_allocation_transition(current: Any, target: Any) -> None:
    """Require an allocation state change to be one §5.11 allows.

    A released or cancelled allocation is finished: re-opening it would let a
    later finalization count stock that was already returned to the pool, and the
    movements that released it would no longer describe the balance.
    """
    from_status = normalize_allocation_status(current, "allocation status")
    to_status = normalize_allocation_status(target, "allocation status")
    if to_status not in ALLOCATION_TRANSITIONS[from_status]:
        raise _invalid("status", f"cannot move an allocation from {from_status} to {to_status}")


# --- Key builders (data model §6.3) ----------------------------------------------


def inventory_pk(unit_campaign_id: str) -> str:
    """Partition key holding one Unit Campaign's whole inventory footprint."""
    return f"{INVENTORY_PK_PREFIX}#{normalize_inventory_id(unit_campaign_id, 'unitCampaignId')}"


def balance_sk(product_id: str) -> str:
    """Sort key of one product's balance row."""
    return f"{PRODUCT_SK_PREFIX}#{normalize_inventory_id(product_id, 'productId')}#{BALANCE_SK_SUFFIX}"


def allocation_sk(product_id: str, show_and_sell_id: str) -> str:
    """Sort key of one (product, event) allocation."""
    product = normalize_inventory_id(product_id, "productId")
    event = normalize_inventory_id(show_and_sell_id, "showAndSellId")
    return f"{PRODUCT_SK_PREFIX}#{product}#{ALLOCATION_SK_MARKER}#{event}"


def custody_sk(product_id: str, profile_id: str) -> str:
    """Sort key of one (product, Scout) custody row."""
    product = normalize_inventory_id(product_id, "productId")
    profile = normalize_inventory_id(profile_id, "profileId")
    return f"{PRODUCT_SK_PREFIX}#{product}#{CUSTODY_SK_MARKER}#{profile}"


def movement_sk(product_id: str, occurred_at: str, movement_id: str) -> str:
    """Sort key of one append-only movement.

    ``occurredAt`` is part of the key so one product's history comes back in
    business-time order without a sort, and the movement id closes the key so two
    movements stamped in the same instant are still two distinct rows.
    """
    product = normalize_inventory_id(product_id, "productId")
    moment = normalize_moment(occurred_at, OCCURRED_AT_ATTRIBUTE)
    identifier = normalize_inventory_id(movement_id, MOVEMENT_ID_ATTRIBUTE)
    return f"{PRODUCT_SK_PREFIX}#{product}#{MOVEMENT_SK_MARKER}#{moment}#{identifier}"


def product_scope_prefix(product_id: str) -> str:
    """The ``PRODUCT#<productId>#`` prefix that scopes a query to one product."""
    return f"{PRODUCT_SK_PREFIX}#{normalize_inventory_id(product_id, 'productId')}#"


def product_movement_prefix(product_id: str) -> str:
    """The ``PRODUCT#<productId>#MOVEMENT#`` prefix: one product's history only."""
    return f"{product_scope_prefix(product_id)}{MOVEMENT_SK_MARKER}#"


def balance_key(unit_campaign_id: str, product_id: str) -> Dict[str, str]:
    """The balance row's key pair."""
    return {"pk": inventory_pk(unit_campaign_id), "sk": balance_sk(product_id)}


def custody_key(unit_campaign_id: str, product_id: str, profile_id: str) -> Dict[str, str]:
    """The custody row's key pair: one identity per (§5.9) campaign/product/Scout."""
    return {"pk": inventory_pk(unit_campaign_id), "sk": custody_sk(product_id, profile_id)}


# --- Item builders (the only place these items are built) ------------------------


def build_inventory_balance_item(
    *,
    unit_campaign_id: Any,
    product_id: Any,
    kernel_physical_qty: Any = 0,
    sold_in_possession_qty: Any = 0,
    council_on_order_qty: Any = 0,
    now_iso: Any,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.7 balance row for one product, validated against the §4.1 invariants.

    A balance row always carries every quantity attribute, zero included. Arithmetic
    update expressions and condition expressions on a missing attribute fail against
    real DynamoDB, so a row that "means" zero by omitting the attribute would make
    the next adjustment fail instead of apply.
    """
    physical = normalize_quantity(kernel_physical_qty, KERNEL_PHYSICAL_QTY)
    in_possession = normalize_quantity(sold_in_possession_qty, SOLD_IN_POSSESSION_QTY)
    on_order = normalize_quantity(council_on_order_qty, COUNCIL_ON_ORDER_QTY)
    stamp = normalize_moment(now_iso, CREATED_AT_ATTRIBUTE)
    aggregate_version = normalize_quantity(version, VERSION_ATTRIBUTE, minimum=1)
    item: Dict[str, Any] = {
        "pk": inventory_pk(str(unit_campaign_id)),
        "sk": balance_sk(str(product_id)),
        ENTITY_TYPE_ATTRIBUTE: BALANCE_ENTITY_TYPE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(unit_campaign_id, "unitCampaignId"),
        PRODUCT_ID_ATTRIBUTE: normalize_inventory_id(product_id, "productId"),
        KERNEL_PHYSICAL_QTY: physical,
        SOLD_IN_POSSESSION_QTY: in_possession,
        COUNCIL_ON_ORDER_QTY: on_order,
        VERSION_ATTRIBUTE: aggregate_version,
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
    }
    violations = balance_invariant_violations(item)
    if violations:
        raise _invalid(KERNEL_PHYSICAL_QTY, f"would break the inventory invariants: {'; '.join(violations)}")
    return item


def _movement_deltas(
    kind: str,
    *,
    kernel_physical_delta: int,
    sold_possession_delta: int,
    with_scout_delta: int,
    assigned_delta: int,
    council_on_order_delta: int,
) -> Dict[str, int]:
    """The five §5.8 delta attributes, validated against what ``kind`` may move.

    A movement carrying a delta its type does not own is a silent second path into a
    balance: the audit row would claim a stock effect the operation never made, and
    the reconciliation that reads the trail would agree with the lie.
    """
    raw = {
        KERNEL_PHYSICAL_DELTA: kernel_physical_delta,
        SOLD_POSSESSION_DELTA: sold_possession_delta,
        WITH_SCOUT_DELTA: with_scout_delta,
        ASSIGNED_DELTA: assigned_delta,
        COUNCIL_ON_ORDER_DELTA: council_on_order_delta,
    }
    deltas = {name: _integer(value, name) for name, value in raw.items()}
    outside = sorted(name for name, value in deltas.items() if value and name not in MOVEMENT_ALLOWED_DELTAS[kind])
    if outside:
        raise _invalid(
            MOVEMENT_TYPE_ATTRIBUTE,
            f"{kind} movements carry no {', '.join(outside)}; §5.8 gives that delta to another type",
        )
    for name, value in deltas.items():
        if abs(value) > MAX_QUANTITY:
            raise _invalid(name, f"must be between -{MAX_QUANTITY} and {MAX_QUANTITY}")
    return deltas


def _movement_links(
    kind: str,
    *,
    profile_id: Optional[str],
    show_and_sell_id: Optional[str],
    sale_id: Optional[str],
    order_id: Optional[str],
    we_owe_id: Optional[str],
    fulfillment_id: Optional[str],
    finalization_id: Optional[str],
) -> Dict[str, str]:
    """The source links a movement of ``kind`` must name, validated (§5.8).

    An event movement with no event, or a custody movement with no Scout, is a
    record that cannot be traced to what caused it, which is the whole reason the
    movement trail exists.
    """
    raw = {
        PROFILE_ID_ATTRIBUTE: profile_id,
        SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_id,
        SALE_ID_ATTRIBUTE: sale_id,
        ORDER_ID_ATTRIBUTE: order_id,
        WE_OWE_ID_ATTRIBUTE: we_owe_id,
        FULFILLMENT_ID_ATTRIBUTE: fulfillment_id,
        FINALIZATION_ID_ATTRIBUTE: finalization_id,
    }
    missing = sorted(name for name in MOVEMENT_REQUIRED_LINKS[kind] if raw[name] is None)
    if missing:
        raise _invalid(
            MOVEMENT_TYPE_ATTRIBUTE,
            f"{kind} movements must name {', '.join(missing)}; §5.8 makes them traceable",
        )
    return {name: normalize_inventory_id(value, name) for name, value in raw.items() if value is not None}


def build_inventory_movement_item(
    *,
    movement_id: Any,
    unit_campaign_id: Any,
    product_id: Any,
    movement_type: Any,
    actor_account_id: Any,
    occurred_at: Any,
    idempotency_key: Any,
    kernel_physical_delta: int = 0,
    sold_possession_delta: int = 0,
    with_scout_delta: int = 0,
    assigned_delta: int = 0,
    council_on_order_delta: int = 0,
    profile_id: Optional[str] = None,
    show_and_sell_id: Optional[str] = None,
    sale_id: Optional[str] = None,
    order_id: Optional[str] = None,
    we_owe_id: Optional[str] = None,
    fulfillment_id: Optional[str] = None,
    finalization_id: Optional[str] = None,
    reason: Optional[str] = None,
    inventory_version: Optional[int] = None,
) -> Dict[str, Any]:
    """The §5.8 append-only movement record.

    The row carries no ``version`` and is never updated: history is corrected by a
    new linked movement. ``inventoryVersion`` is the resulting balance version, so
    an audit reader can line the movement up against the aggregate it produced, and
    ``idempotencyKey`` is stored so a replay is recognizable as the same request
    even after the marker has expired.
    """
    kind = normalize_movement_type(movement_type)
    deltas = _movement_deltas(
        kind,
        kernel_physical_delta=kernel_physical_delta,
        sold_possession_delta=sold_possession_delta,
        with_scout_delta=with_scout_delta,
        assigned_delta=assigned_delta,
        council_on_order_delta=council_on_order_delta,
    )
    moment = normalize_moment(occurred_at, OCCURRED_AT_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": inventory_pk(str(unit_campaign_id)),
        "sk": movement_sk(str(product_id), moment, str(movement_id)),
        ENTITY_TYPE_ATTRIBUTE: MOVEMENT_ENTITY_TYPE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(unit_campaign_id, "unitCampaignId"),
        MOVEMENT_ID_ATTRIBUTE: normalize_inventory_id(movement_id, MOVEMENT_ID_ATTRIBUTE),
        PRODUCT_ID_ATTRIBUTE: normalize_inventory_id(product_id, "productId"),
        MOVEMENT_TYPE_ATTRIBUTE: kind,
        OCCURRED_AT_ATTRIBUTE: moment,
        ACTOR_ACCOUNT_ID_ATTRIBUTE: normalize_required_text(
            actor_account_id, ACTOR_ACCOUNT_ID_ATTRIBUTE, MAX_ID_LENGTH
        ),
        IDEMPOTENCY_KEY_ATTRIBUTE: normalize_required_text(idempotency_key, IDEMPOTENCY_KEY_ATTRIBUTE, 128),
        **deltas,
        **_movement_links(
            kind,
            profile_id=profile_id,
            show_and_sell_id=show_and_sell_id,
            sale_id=sale_id,
            order_id=order_id,
            we_owe_id=we_owe_id,
            fulfillment_id=fulfillment_id,
            finalization_id=finalization_id,
        ),
    }
    if reason is not None:
        item[REASON_ATTRIBUTE] = normalize_reason(reason, REASON_ATTRIBUTE, required=True)
    if inventory_version is not None:
        item[INVENTORY_VERSION_ATTRIBUTE] = normalize_quantity(
            inventory_version, INVENTORY_VERSION_ATTRIBUTE, minimum=1
        )
    return item


def build_event_inventory_allocation_item(
    *,
    unit_campaign_id: Any,
    product_id: Any,
    show_and_sell_id: Any,
    start_at: Any,
    end_at: Any,
    allocated_qty: Any,
    status: Any = ALLOCATION_OPEN,
    sold_qty: Any = 0,
    released_qty: Any = 0,
    now_iso: Any,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.11 allocation row, with ``remainingQty`` derived, not supplied.

    ``remainingQty`` is stored because every consumer of "what is still assigned"
    must see the same number, but it is computed here from the three authoritative
    counts: a caller that passed its own ``remainingQty`` could store an allocation
    whose residue contradicts its own parts.
    """
    allocated = normalize_quantity(allocated_qty, ALLOCATED_QTY)
    sold = normalize_quantity(sold_qty, SOLD_QTY)
    released = normalize_quantity(released_qty, RELEASED_QTY)
    stamp = normalize_moment(now_iso, CREATED_AT_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": inventory_pk(str(unit_campaign_id)),
        "sk": allocation_sk(str(product_id), str(show_and_sell_id)),
        ENTITY_TYPE_ATTRIBUTE: ALLOCATION_ENTITY_TYPE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(unit_campaign_id, "unitCampaignId"),
        PRODUCT_ID_ATTRIBUTE: normalize_inventory_id(product_id, "productId"),
        SHOW_AND_SELL_ID_ATTRIBUTE: normalize_inventory_id(show_and_sell_id, "showAndSellId"),
        "startAt": normalize_moment(start_at, "startAt"),
        "endAt": normalize_moment(end_at, "endAt"),
        "status": normalize_allocation_status(status),
        ALLOCATED_QTY: allocated,
        SOLD_QTY: sold,
        RELEASED_QTY: released,
        REMAINING_QTY: allocated - sold - released,
        VERSION_ATTRIBUTE: normalize_quantity(version, VERSION_ATTRIBUTE, minimum=1),
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
    }
    violations = allocation_invariant_violations(item)
    if violations:
        raise _invalid(ALLOCATED_QTY, f"would break the allocation invariants: {'; '.join(violations)}")
    return item


def build_scout_custody_balance_item(
    *,
    unit_campaign_id: Any,
    product_id: Any,
    profile_id: Any,
    campaign_id: Any,
    with_scout_qty: Any = 0,
    now_iso: Any,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.9 custody row: one identity per (campaign, product, Scout).

    ``campaignId`` is stored with the row because custody belongs to the Scout
    Campaign that is actually selling: the same Scout in two Unit Campaigns holds
    two custodies, and a sale against one must never consume the other.
    """
    item: Dict[str, Any] = {
        "pk": inventory_pk(str(unit_campaign_id)),
        "sk": custody_sk(str(product_id), str(profile_id)),
        ENTITY_TYPE_ATTRIBUTE: CUSTODY_ENTITY_TYPE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(unit_campaign_id, "unitCampaignId"),
        PRODUCT_ID_ATTRIBUTE: normalize_inventory_id(product_id, "productId"),
        PROFILE_ID_ATTRIBUTE: normalize_inventory_id(profile_id, "profileId"),
        CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(campaign_id, "campaignId"),
        # §5.9's only rule for a custody row is ``withScoutQty >= 0``, and
        # ``normalize_quantity`` refuses a negative outright, so the builder cannot
        # produce a row :func:`custody_invariant_violations` would reject. That
        # checker audits rows already in the table, where a bad write from another
        # stage would show up.
        WITH_SCOUT_QTY: normalize_quantity(with_scout_qty, WITH_SCOUT_QTY),
        VERSION_ATTRIBUTE: normalize_quantity(version, VERSION_ATTRIBUTE, minimum=1),
        CREATED_AT_ATTRIBUTE: normalize_moment(now_iso, CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE),
    }
    return item


# --- Invariants (§4.1-§4.4, §5.8) ------------------------------------------------


def _count(item: Mapping[str, Any], name: str) -> int:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return 0
    return int(value)


def balance_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """Every §4.1 violation in one balance row, named for the caller."""
    violations: List[str] = []
    physical = _count(item, KERNEL_PHYSICAL_QTY)
    in_possession = _count(item, SOLD_IN_POSSESSION_QTY)
    if in_possession < 0:
        violations.append(f"{SOLD_IN_POSSESSION_QTY} is negative")
    if physical < in_possession:
        violations.append(f"{KERNEL_PHYSICAL_QTY} is below {SOLD_IN_POSSESSION_QTY}")
    if _count(item, COUNCIL_ON_ORDER_QTY) < 0:
        violations.append(f"{COUNCIL_ON_ORDER_QTY} is negative")
    return violations


def custody_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """Every §5.9 custody violation (``withScoutQty >= 0``)."""
    return [f"{WITH_SCOUT_QTY} is negative"] if _count(item, WITH_SCOUT_QTY) < 0 else []


def allocation_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """Every §5.11 allocation equation violation."""
    violations: List[str] = []
    allocated = _count(item, ALLOCATED_QTY)
    sold = _count(item, SOLD_QTY)
    released = _count(item, RELEASED_QTY)
    remaining = _count(item, REMAINING_QTY)
    if allocated < sold:
        violations.append(f"{ALLOCATED_QTY} is below {SOLD_QTY}")
    if released < 0:
        violations.append(f"{RELEASED_QTY} is negative")
    if remaining != allocated - sold - released:
        violations.append(f"{REMAINING_QTY} does not equal {ALLOCATED_QTY} - {SOLD_QTY} - {RELEASED_QTY}")
    if remaining < 0:
        violations.append(f"{REMAINING_QTY} is negative")
    return violations


def movement_row_violations(item: Mapping[str, Any]) -> List[str]:
    """Why one movement row is not an append-only §5.8 record, or empty if it is.

    Two rules carry the contract: no attribute outside the §5.8 set — a ``version``
    attribute in particular, which is what makes a row look mutable — and no
    attribute outside that set at all, which is how a quantity no one reviewed
    would otherwise reach the audit trail.
    """
    violations = [f"unexpected attribute {name}" for name in sorted(set(item) - MOVEMENT_ROW_ATTRIBUTES)]
    if VERSION_ATTRIBUTE in item:
        violations.append(f"{VERSION_ATTRIBUTE} would make an append-only movement mutable")
    return violations


# --- Derived quantities (§7) -----------------------------------------------------


def sellable_kernel_qty(balance: Optional[Mapping[str, Any]]) -> int:
    """``kernelPhysicalQty - soldInPossessionQty`` (§7)."""
    if balance is None:
        return 0
    return _count(balance, KERNEL_PHYSICAL_QTY) - _count(balance, SOLD_IN_POSSESSION_QTY)


def assigned_open_qty(allocations: Iterable[Mapping[str, Any]]) -> int:
    """Sum of ``remainingQty`` over OPEN allocations (§7).

    Only OPEN allocations count as assigned: a released or cancelled allocation's
    stock is back in the pool, and counting it again is how a reopened event would
    appear to hold stock it no longer does.
    """
    return sum(
        _count(allocation, REMAINING_QTY) for allocation in allocations if _status(allocation) == ALLOCATION_OPEN
    )


def _status(item: Mapping[str, Any]) -> str:
    value = item.get(STATUS_ATTRIBUTE)
    return value if isinstance(value, str) else ""


def unassigned_kernel_qty(balance: Optional[Mapping[str, Any]], allocations: Iterable[Mapping[str, Any]]) -> int:
    """``max(0, sellable - assignedOpen)`` (§7)."""
    return max(0, sellable_kernel_qty(balance) - assigned_open_qty(allocations))


def assignment_overage_qty(balance: Optional[Mapping[str, Any]], allocations: Iterable[Mapping[str, Any]]) -> int:
    """``max(0, assignedOpen - sellable)`` (§7): the over-assignment a Kernel must see.

    Kept separate from ``unassignedKernelQty`` rather than clamped away: overage is
    a condition to report and correct, and a single clamped number would hide which
    side of the line a campaign is on.
    """
    return max(0, assigned_open_qty(allocations) - sellable_kernel_qty(balance))


def with_scout_qty(custody_rows: Iterable[Mapping[str, Any]]) -> int:
    """Sum of custody ``withScoutQty`` for one product (§7)."""
    return sum(_count(row, WITH_SCOUT_QTY) for row in custody_rows)


def total_unit_owned_undelivered_qty(
    balance: Optional[Mapping[str, Any]], custody_rows: Iterable[Mapping[str, Any]]
) -> int:
    """``kernelPhysicalQty + withScoutQty`` (§7).

    Council-on-order is not added — it is expected supply, not stock on hand — and
    assigned stock is NOT subtracted, because an assignment is still Kernel
    physical stock until it is sold or adjusted.
    """
    physical = 0 if balance is None else _count(balance, KERNEL_PHYSICAL_QTY)
    return physical + with_scout_qty(custody_rows)


def derived_inventory_quantities(
    balance: Optional[Mapping[str, Any]],
    allocations: Iterable[Mapping[str, Any]],
    custody_rows: Iterable[Mapping[str, Any]],
) -> Dict[str, int]:
    """Every §7 derived quantity for one product, computed from raw rows.

    One call, one set of reads, one arithmetic path: the mutation result and the
    list query both answer from here, so the two can never disagree about what
    "sellable" means for the same product.
    """
    allocation_rows = list(allocations)
    custody = list(custody_rows)
    return {
        "sellableKernelQty": sellable_kernel_qty(balance),
        "assignedOpenQty": assigned_open_qty(allocation_rows),
        "unassignedKernelQty": unassigned_kernel_qty(balance, allocation_rows),
        "assignmentOverageQty": assignment_overage_qty(balance, allocation_rows),
        "withScoutQty": with_scout_qty(custody),
        "totalUnitOwnedUndeliveredQty": total_unit_owned_undelivered_qty(balance, custody),
    }


# --- Reads (consistent where a mutation conditions on the result) ----------------


def read_inventory_balance(unit_campaign_id: str, product_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one product's balance (§8.4)."""
    response = tables.inventory.get_item(Key=balance_key(unit_campaign_id, product_id), ConsistentRead=True)
    item = response.get("Item")
    return cast(Optional[Dict[str, Any]], dict(item) if isinstance(item, dict) else None)


def exact_product_rows(rows: Iterable[Mapping[str, Any]], product_id: str) -> List[Dict[str, Any]]:
    """Keep the rows whose own ``productId`` attribute is exactly this product.

    ``PRODUCT#<productId>#`` is a sort-key range, not an identity test. Product ids carry
    ``#`` inside them (``CATALOG#fixture-default#prod-1``, and §6.3 resolves an ambiguous
    segment from the row's own attribute rather than a split of its key), so the range that
    finds one product also finds every row of a product spelled ``<productId>#<extra>``.
    Reading a range as if it were an identity is how a write to the first product lands on
    the second one's row: the position, the allocation, and the audit trail then disagree
    about which product moved. The movement reader already refuses that class
    (:func:`list_inventory_movements` filters an exact ``productId`` alongside its key
    prefix); this is the same predicate for the balance, allocation and custody rows.
    """
    wanted = normalize_inventory_id(product_id, "productId")
    return [dict(row) for row in rows if str(row.get(PRODUCT_ID_ATTRIBUTE)) == wanted]


def read_inventory_product_rows(unit_campaign_id: str, product_id: str) -> List[Dict[str, Any]]:
    """Every row under one product prefix: balance, allocations, custody, movements.

    One consistent query answers a position for that product, which is what §8.4
    requires before a stock write: the balance and the open allocations that compete
    with it must come from the same read. The range is then narrowed to this exact
    product — a prefix read is not an identity test, and a nested product id shares the
    range of its own prefix parent (:func:`exact_product_rows`).
    """
    return exact_product_rows(
        query_all_items(
            tables.inventory,
            {
                "KeyConditionExpression": "#pk = :pk and begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
                "ExpressionAttributeValues": {
                    ":pk": inventory_pk(unit_campaign_id),
                    ":prefix": product_scope_prefix(product_id),
                },
                "ConsistentRead": True,
            },
        ),
        product_id,
    )


def read_campaign_inventory_rows(unit_campaign_id: str) -> List[Dict[str, Any]]:
    """Every inventory row of one Unit Campaign, in sort-key order (§6.3 rationale)."""
    return list(
        query_all_items(
            tables.inventory,
            {
                "KeyConditionExpression": "#pk = :pk",
                "ExpressionAttributeNames": {"#pk": "pk"},
                "ExpressionAttributeValues": {":pk": inventory_pk(unit_campaign_id)},
                "ConsistentRead": True,
            },
        )
    )


def read_scout_custody(unit_campaign_id: str, product_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one Scout's custody of one product (§5.9).

    The read is consistent because an issue or return conditions on the row it
    reads: a custody ``version`` is what serializes issue, sale and return for one
    Scout (§5.9), and an eventually consistent read would let two returns of the
    last two Kernels both believe they hold them.
    """
    response = tables.inventory.get_item(Key=custody_key(unit_campaign_id, product_id, profile_id), ConsistentRead=True)
    item = response.get("Item")
    return cast(Optional[Dict[str, Any]], dict(item) if isinstance(item, dict) else None)


def _filter_rows(
    rows: Sequence[Mapping[str, Any]], filters: Sequence[tuple[str, Optional[str]]]
) -> List[Dict[str, Any]]:
    """Keep the rows whose own attribute equals each requested value.

    The filters are (attribute, value) pairs and an unset filter is skipped, which is how
    one helper serves every optional filter of the campaign-scoped reads. Copying each row
    on the way out keeps the caller's rows its own: a caller that sorts or annotates a page
    must not annotate a dict the model still holds.
    """
    kept: List[Dict[str, Any]] = [dict(row) for row in rows]
    for attribute, value in filters:
        if value is not None:
            kept = [row for row in kept if row.get(attribute) == value]
    return kept


def campaign_custody_rows(
    unit_campaign_id: str, *, profile_id: Optional[str] = None, product_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """One campaign's custody rows, in sort-key order (product first, then Scout).

    The campaign partition is the right scope for both custody reads: the admin
    board asks "what does this campaign have out with Scouts", and the participant
    read asks the same question for one Scout. Filtering on the row's own
    ``profileId``/``productId`` attributes rather than by the partition's ``profileId``
    GSI is deliberate — an issue and the read that answers it must agree, and a
    GSI is eventually consistent.
    """
    rows = [
        row
        for row in read_campaign_inventory_rows(unit_campaign_id)
        if row.get(ENTITY_TYPE_ATTRIBUTE) == CUSTODY_ENTITY_TYPE
    ]
    return _filter_rows(rows, ((PROFILE_ID_ATTRIBUTE, profile_id), (PRODUCT_ID_ATTRIBUTE, product_id)))


def campaign_allocation_rows(
    unit_campaign_id: str,
    *,
    product_id: Optional[str] = None,
    show_and_sell_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """One campaign's ``EventInventoryAllocation`` rows, in sort-key order (§6.3).

    The product id is the first component of an allocation's sort key, so the campaign read
    answers allocations grouped per product, which is the order the assignment screen and
    the browser-side overage arithmetic want (DATA-Q-03). The filters are applied to the
    rows this read already returned rather than through a ``FilterExpression``, for the same
    reason :func:`campaign_custody_rows` states: the read that decides what a mutation may
    write and the read that answers about it have to be the same read, and an index lags a
    write.

    ``status`` is validated before it is compared, so an unknown spelling is
    ``INVALID_INPUT`` rather than an empty page that looks like "no allocations".
    """
    wanted = None if status is None else normalize_allocation_status(status)
    rows = [
        row
        for row in read_campaign_inventory_rows(unit_campaign_id)
        if row.get(ENTITY_TYPE_ATTRIBUTE) == ALLOCATION_ENTITY_TYPE
    ]
    return _filter_rows(
        rows,
        (
            (PRODUCT_ID_ATTRIBUTE, product_id),
            (SHOW_AND_SELL_ID_ATTRIBUTE, show_and_sell_id),
            (STATUS_ATTRIBUTE, wanted),
        ),
    )


def product_inventory_sections(rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Bucket campaign rows under one product prefix into balance/allocations/custody.

    Movements are excluded: the position is a balance question, and a product with
    a long history would otherwise pay for its whole audit trail on every read.
    """
    sections: Dict[str, List[Dict[str, Any]]] = {"balance": [], "allocations": [], "custody": []}
    for row in rows:
        kind = _SECTION_BY_ENTITY_TYPE.get(str(row.get(ENTITY_TYPE_ATTRIBUTE)))
        if kind is not None:
            sections[kind].append(cast(Dict[str, Any], dict(row)))
    return sections


def list_inventory_movements(
    unit_campaign_id: str,
    *,
    product_id: Optional[str] = None,
    movement_type: Optional[str] = None,
    show_and_sell_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """One campaign's movement history, with §5.8 filters applied by the read.

    A product filter rides in the key condition, because movements are keyed by
    product then time and that range is the whole point of the key. The remaining
    filters are attribute filters on the partition read: at Show & Sell scale a
    campaign's audit history is one partition's worth of rows, and filtering after
    the key range is cheaper and always correct, unlike an index read that may be
    behind the write being audited.

    Which rows are movements is decided by the ``entityType`` attribute, never by
    the sort key. DynamoDB rejects a Query whose ``FilterExpression`` names a key
    attribute of the table or index it is reading — ``ValidationException: Filter
    Expression can only contain non-primary key attributes: Primary key attribute:
    sk`` — so the ``contains(#sk, '#MOVEMENT#')`` filter this read used to carry
    failed EVERY deployed call, campaign-populated or empty, while moto accepted
    it and the local suite stayed green. On the service the key attributes belong
    in the key condition; only non-key attributes may be filtered.
    """
    names = {"#pk": "pk"}
    values: Dict[str, Any] = {":pk": inventory_pk(unit_campaign_id)}
    filters: List[str] = []
    # The discriminator every row of this table carries. Handing a balance,
    # allocation or custody row to a movement projection is an internal fault, not
    # an empty page, so this filter is unconditional.
    names[f"#{ENTITY_TYPE_ATTRIBUTE}"] = ENTITY_TYPE_ATTRIBUTE
    values[":movementEntityType"] = MOVEMENT_ENTITY_TYPE
    filters.append(f"#{ENTITY_TYPE_ATTRIBUTE} = :movementEntityType")
    if product_id is not None:
        # One product's audit trail is a contiguous sort-key range, so the marker
        # belongs in the key condition, where naming a key attribute is allowed and
        # the balance, allocation and custody rows of that product are never read.
        values[":prefix"] = product_movement_prefix(product_id)
        key_condition = "#pk = :pk and begins_with(#sk, :prefix)"
        names["#sk"] = "sk"
        # A key prefix is never an exact product match: product ids carry ``#``
        # inside them, so the range for ``A`` also holds the rows of a product
        # spelled ``A#<marker>`` (§6.3 resolves an ambiguous segment from the row's
        # own attribute, never from a split of its sort key).
        names[f"#{PRODUCT_ID_ATTRIBUTE}"] = PRODUCT_ID_ATTRIBUTE
        values[":movementProductId"] = normalize_inventory_id(product_id, "productId")
        filters.append(f"#{PRODUCT_ID_ATTRIBUTE} = :movementProductId")
    else:
        # A campaign-wide history read: the partition is the campaign, and no key
        # condition can name the middle of a sort key, so every row kind of the
        # partition is read and the ``entityType`` filter discards the rest.
        key_condition = "#pk = :pk"
    if movement_type is not None:
        names["#movementType"] = MOVEMENT_TYPE_ATTRIBUTE
        values[":movementType"] = movement_type
        filters.append("#movementType = :movementType")
    if show_and_sell_id is not None:
        names["#showAndSellId"] = SHOW_AND_SELL_ID_ATTRIBUTE
        values[":showAndSellId"] = show_and_sell_id
        filters.append("#showAndSellId = :showAndSellId")
    if profile_id is not None:
        names["#profileId"] = PROFILE_ID_ATTRIBUTE
        values[":profileId"] = profile_id
        filters.append("#profileId = :profileId")
    if start_at is not None:
        names["#occurredAt"] = OCCURRED_AT_ATTRIBUTE
        values[":startAt"] = start_at
        filters.append("#occurredAt >= :startAt")
    if end_at is not None:
        names["#occurredAt"] = OCCURRED_AT_ATTRIBUTE
        values[":endAt"] = end_at
        filters.append("#occurredAt <= :endAt")
    query: Dict[str, Any] = {
        "KeyConditionExpression": key_condition,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
        # The ``entityType`` filter is unconditional, so every history read carries one.
        "FilterExpression": " and ".join(filters),
    }
    rows = query_all_items(tables.inventory, query)
    # Newest-first is a business-time order, and the key order is product-first:
    # a campaign-wide page would otherwise show one product's whole history before
    # the next product's most recent change. The read is already bounded to one
    # campaign partition, so ordering the collected rows is both cheap and honest.
    return sorted(
        (cast(Dict[str, Any], dict(row)) for row in rows),
        key=lambda row: (str(row.get(OCCURRED_AT_ATTRIBUTE, "")), str(row.get(MOVEMENT_ID_ATTRIBUTE, ""))),
    )


def inventory_position_rows(unit_campaign_id: str, product_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """The balance, allocation, and custody rows behind one product's position."""
    return product_inventory_sections(read_inventory_product_rows(unit_campaign_id, product_id))


def campaign_product_sections(
    unit_campaign_id: str, product_ids: Optional[Sequence[str]] = None
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Every product's position rows, keyed by product id in sort-key order.

    Without an explicit product list the whole partition is read once — the
    campaign partition holds one balance, a handful of allocations and custody
    rows, and the audit trail per product, so one read beats N product queries.
    With a list, each product prefix is read on its own: a caller asking for
    three products pays for three small ranges instead of the campaign's whole
    history, and a product with no rows simply contributes an empty section, which
    is what makes a zero position answerable before the first receipt.
    """
    if product_ids:
        return {str(pid): inventory_position_rows(unit_campaign_id, str(pid)) for pid in product_ids}
    sections: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in read_campaign_inventory_rows(unit_campaign_id):
        kind = _SECTION_BY_ENTITY_TYPE.get(str(row.get(ENTITY_TYPE_ATTRIBUTE)))
        if kind is None:
            # A movement row shares the partition but answers an audit question,
            # and the position must not pay for the audit trail.
            continue
        # The product comes from the row's own attribute, never from its sort key:
        # this application spells product ids with `#` inside them
        # (`CATALOG#fixture-default#prod-1`), so a split of `PRODUCT#<productId>#BALANCE`
        # would name the catalog rather than the product, and two products of one
        # catalog would merge into one position.
        product_id = row.get(PRODUCT_ID_ATTRIBUTE)
        if not isinstance(product_id, str) or not product_id:
            continue
        bucket = sections.setdefault(product_id, {"balance": [], "allocations": [], "custody": []})
        bucket[kind].append(dict(row))
    return dict(sorted(sections.items()))


# --- Transaction actions ---------------------------------------------------------


def put_inventory_balance_action(item: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Create a balance that does not exist yet.

    The condition is what makes the first-write path race-safe: two concurrent
    first receipts of the same product cannot both create the row, and the loser
    retries against the row the winner wrote instead of silently starting from
    zero again on top of it.
    """
    return (
        "Put",
        {
            "TableName": tables.inventory.table_name,
            "Item": {name: wire_value(value) for name, value in item.items()},
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_inventory_movement_action(item: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Append a movement.

    Conditional on the row being absent: a movement id is generated per request,
    so the condition only ever fails for a genuine id collision, and it is what
    keeps "append-only" literal — this is the only write shape a movement row gets.
    """
    return (
        "Put",
        {
            "TableName": tables.inventory.table_name,
            "Item": {name: wire_value(value) for name, value in item.items()},
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def inventory_balance_delta_action(
    *,
    unit_campaign_id: str,
    product_id: str,
    existing: Optional[Mapping[str, Any]],
    expected_version: int,
    kernel_physical_delta: int = 0,
    council_on_order_delta: int = 0,
    now_iso: str,
) -> tuple[str, Dict[str, Any]]:
    """One versioned balance change with the §4.1 floor carried into the condition.

    The floor is in the CONDITION, not only in the pre-read check. A balance read
    followed by an unconditional write is the lost-update bug in another form: two
    Kernels reducing the same product both pass their own check and the second
    drives physical below what is reserved for We Owe.

    DynamoDB allows arithmetic only in an ``UpdateExpression``, never in a condition,
    so the floor is stated as a bound on the attribute this request read:
    ``kernelPhysicalQty + delta >= reserved`` is the same statement as
    ``kernelPhysicalQty >= reserved - delta``, and the right-hand side is a number
    this handler computes. Taking ``reserved`` from this request's own read is safe
    rather than stale-looking, because every writer of any balance quantity
    increments ``version`` and the same condition pins ``version`` to what this
    request read: a reservation that landed after the read cancels this plan whole,
    so no condition here is ever evaluated against a balance that moved underneath
    it. A positive delta needs no bound — the read already satisfied the invariant
    and raising physical cannot break it.
    """
    names = {
        "#version": VERSION_ATTRIBUTE,
        "#updatedAt": UPDATED_AT_ATTRIBUTE,
    }
    values: Dict[str, Any] = {
        ":expectedVersion": wire_value(expected_version),
        ":one": wire_value(1),
        ":updatedAt": wire_value(normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)),
    }
    sets = ["#version = #version + :one", "#updatedAt = :updatedAt"]
    conditions = ["#version = :expectedVersion"]
    if kernel_physical_delta:
        names[f"#{KERNEL_PHYSICAL_QTY}"] = KERNEL_PHYSICAL_QTY
        values[":kernelDelta"] = wire_value(kernel_physical_delta)
        sets.append(f"#{KERNEL_PHYSICAL_QTY} = #{KERNEL_PHYSICAL_QTY} + :kernelDelta")
        stock_floor = -kernel_physical_delta
        if stock_floor > 0:
            values[":kernelFloor"] = wire_value(stock_floor)
            conditions.append(f"#{KERNEL_PHYSICAL_QTY} >= :kernelFloor")
        reserved_floor = _count(existing or {}, SOLD_IN_POSSESSION_QTY) - kernel_physical_delta
        if reserved_floor > 0:
            values[":reservedFloor"] = wire_value(reserved_floor)
            conditions.append(f"#{KERNEL_PHYSICAL_QTY} >= :reservedFloor")
    if council_on_order_delta:
        names[f"#{COUNCIL_ON_ORDER_QTY}"] = COUNCIL_ON_ORDER_QTY
        values[":councilDelta"] = wire_value(council_on_order_delta)
        sets.append(f"#{COUNCIL_ON_ORDER_QTY} = #{COUNCIL_ON_ORDER_QTY} + :councilDelta")
        council_floor = -council_on_order_delta
        if council_floor > 0:
            values[":councilFloor"] = wire_value(council_floor)
            conditions.append(f"#{COUNCIL_ON_ORDER_QTY} >= :councilFloor")
    return (
        "Update",
        {
            "TableName": tables.inventory.table_name,
            "Key": wire_key(balance_key(unit_campaign_id, product_id)),
            "UpdateExpression": "SET " + ", ".join(sets),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ConditionExpression": " AND ".join(conditions),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_scout_custody_action(item: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Create the custody row a Scout does not have yet for this product.

    ``attribute_not_exists`` is the race guard, the same shape as the first receipt
    of a product: two concurrent issues to one Scout for one product cannot both
    start from zero, and the loser cancels its whole transaction instead of
    overwriting the row the winner wrote.
    """
    return (
        "Put",
        {
            "TableName": tables.inventory.table_name,
            "Item": {name: wire_value(value) for name, value in item.items()},
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def scout_custody_delta_action(
    *,
    unit_campaign_id: str,
    product_id: str,
    profile_id: str,
    existing: Optional[Mapping[str, Any]],
    expected_version: int,
    with_scout_delta: int,
    now_iso: str,
) -> tuple[str, Dict[str, Any]]:
    """One versioned custody change whose §5.9 floor rides in the condition.

    ``version`` is what §5.9 gives a custody row so that issue, sale and return for
    one Scout serialize; pinning it here is what makes "the Scout holds three" a
    statement about the row this request read rather than about a row that moved
    underneath it. ``withScoutQty >= -delta`` closes the other half: two returns of
    the same three Kernels cannot both succeed, and With Scout can never go negative
    (CUST-04). As in :func:`inventory_balance_delta_action`, DynamoDB allows no
    arithmetic inside a condition, so the bound is stated against the value this
    request read — and it is safe rather than stale because the version pin cancels
    the plan whole if anything else moved the row.
    """
    names = {
        "#version": VERSION_ATTRIBUTE,
        "#updatedAt": UPDATED_AT_ATTRIBUTE,
        f"#{WITH_SCOUT_QTY}": WITH_SCOUT_QTY,
    }
    values: Dict[str, Any] = {
        ":expectedVersion": wire_value(expected_version),
        ":one": wire_value(1),
        ":updatedAt": wire_value(normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)),
        ":scoutDelta": wire_value(with_scout_delta),
    }
    sets = [
        "#version = #version + :one",
        "#updatedAt = :updatedAt",
        f"#{WITH_SCOUT_QTY} = #{WITH_SCOUT_QTY} + :scoutDelta",
    ]
    conditions = ["#version = :expectedVersion"]
    custody_floor = -with_scout_delta
    if custody_floor > 0:
        values[":scoutFloor"] = wire_value(custody_floor)
        conditions.append(f"#{WITH_SCOUT_QTY} >= :scoutFloor")
    return (
        "Update",
        {
            "TableName": tables.inventory.table_name,
            "Key": wire_key(custody_key(unit_campaign_id, product_id, profile_id)),
            "UpdateExpression": "SET " + ", ".join(sets),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ConditionExpression": " AND ".join(conditions),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )
