"""The `OrderFulfillment` row and the Order line-item extension of data model §5.19.

Wave 3.3's individual-order fulfillment resolvers (fulfill, reverse, and the two
history reads) all address one partition of the ``order_fulfillments`` table laid
out in data model §6.5 — see
``docs/specs/show_sell/SHOW_AND_SELL_DATA_MODEL.md``::

    ORDER#<orderId> / FULFILLMENT#<createdAt>#<fulfillmentId>              (§6.5)
    ORDER#<orderId> / REVERSAL#<reversalOfFulfillmentId>                   (§5.19)

The Order rows themselves stay in the existing ``orders`` table and are updated
transactionally with these rows, which is why every mutation here conditions on the
Order's ``fulfillmentVersion`` rather than on an inventory version: §5.19 requires
that version to move for every fulfillment and reversal, *including* an
external-Council change that touches no inventory record.

This module owns the row shape and the key grammar, so that no handler can invent a
second spelling of a fulfillment key (a ``FULFILLMENT#`` written one way by the
mutation and another by the read is a history list that silently misses rows) or a
projection that leaks an audit field into ``ParticipantOrderFulfillment`` (API §10.2
— the participant projection is derived from the admin one by SUBTRACTION, so a
future audit field cannot reach a Scout because someone forgot to leave it out of a
list).

Like the inventory records beside it, a fulfillment row is append-only: a mistake is
corrected by a REVERSAL row linked to the original, never by editing the original.
Authorization is not this module's question — the resolvers answer who may call it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .ids import ensure_campaign_id
from .inventory_models import (
    normalize_inventory_id,
    normalize_moment,
    normalize_quantity,
    normalize_signed_delta,
)
from .mutations import wire_key, wire_value
from .order_keys import ORDER_ID_PREFIX, parse_order_id
from .pagination import query_all_items
from .unit_models import MAX_ID_LENGTH, normalize_required_text

# --- Key layout (data model §6.5) -------------------------------------------------

#: The fulfillment partition's prefix is the orders table's own order-id prefix, so
#: it is imported rather than re-spelled: two literals for ``ORDER`` are two chances
#: to drift.
PK_PREFIX: str = ORDER_ID_PREFIX

FULFILLMENT_SK_PREFIX = "FULFILLMENT"
REVERSAL_SK_PREFIX = "REVERSAL"

# --- Enums (data model §5.19) -----------------------------------------------------

RECORD_TYPE_FULFILL = "FULFILL"
RECORD_TYPE_REVERSAL = "REVERSAL"

FULFILLMENT_RECORD_TYPES: frozenset[str] = frozenset({RECORD_TYPE_FULFILL, RECORD_TYPE_REVERSAL})

SOURCE_KERNEL_STOCK = "KERNEL_STOCK"
SOURCE_SCOUT_CUSTODY = "SCOUT_CUSTODY"
SOURCE_EXTERNAL_COUNCIL = "EXTERNAL_COUNCIL"

FULFILLMENT_SOURCES: frozenset[str] = frozenset({SOURCE_KERNEL_STOCK, SOURCE_SCOUT_CUSTODY, SOURCE_EXTERNAL_COUNCIL})

#: The two sources that move a Kernel balance, and so must name the inventory
#: movement that did it: a Kernel-stock fulfillment decrements unassigned Kernel
#: stock, a Scout-custody one decrements With Scout. Without the link, the audit
#: trail would show a demand change with no stock change behind it.
#: ``EXTERNAL_COUNCIL`` is deliberately absent — it changes fulfillment and Council
#: demand and no Kernel balance, so it has no movement to name (§5.19).
SOURCE_MOVES_STOCK: frozenset[str] = frozenset({SOURCE_KERNEL_STOCK, SOURCE_SCOUT_CUSTODY})

# --- Attribute names (data model §5.19, API §10.2) --------------------------------

FULFILLMENT_ENTITY_TYPE = "OrderFulfillment"

FULFILLMENT_ID_ATTRIBUTE = "fulfillmentId"
ORDER_ID_ATTRIBUTE = "orderId"
CAMPAIGN_ID_ATTRIBUTE = "campaignId"
PROFILE_ID_ATTRIBUTE = "profileId"
UNIT_ID_ATTRIBUTE = "unitId"
UNIT_CAMPAIGN_ID_ATTRIBUTE = "unitCampaignId"
LINE_ITEM_ID_ATTRIBUTE = "lineItemId"
PRODUCT_ID_ATTRIBUTE = "productId"
RECORD_TYPE_ATTRIBUTE = "recordType"
QUANTITY_ATTRIBUTE = "quantity"
SOURCE_ATTRIBUTE = "source"
INVENTORY_MOVEMENT_ID_ATTRIBUTE = "inventoryMovementId"
REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE = "reversalOfFulfillmentId"
ACTOR_ACCOUNT_ID_ATTRIBUTE = "actorAccountId"
CREATED_AT_ATTRIBUTE = "createdAt"
ENTITY_TYPE_ATTRIBUTE = "entityType"

#: The Order row's own §5.19 extensions, which the line arithmetic below reads and
#: writes: the line list, the amount of a line already fulfilled, and the version
#: every fulfillment and reversal increments.
LINE_ITEMS_ATTRIBUTE = "lineItems"
FULFILLED_QUANTITY_ATTRIBUTE = "fulfilledQuantity"
FULFILLMENT_VERSION_ATTRIBUTE = "fulfillmentVersion"

#: The two attributes that separate ``OrderFulfillment`` from
#: ``ParticipantOrderFulfillment`` (API §10.2): who acted, and which inventory
#: movement moved the stock. The participant projection is derived by REMOVING these
#: from the admin projection, never by listing what may be shown — a future audit
#: field then cannot leak into the participant type by someone forgetting to add it
#: to a list. Membership here is the whole disclosure decision.
ADMIN_ONLY_FULFILLMENT_FIELDS: frozenset[str] = frozenset({ACTOR_ACCOUNT_ID_ATTRIBUTE, INVENTORY_MOVEMENT_ID_ATTRIBUTE})


def _invalid(field: str, rule: str) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


# --- Normalization and validation -------------------------------------------------


def normalize_fulfillment_record_type(value: Any, field: str = RECORD_TYPE_ATTRIBUTE) -> str:
    """Validate an ``OrderFulfillmentRecordType`` (§5.19's closed pair).

    Direction lives in this value and never in the sign of ``quantity``: §5.19 stores
    a positive amount on both record kinds, so a signed quantity would be a second,
    contradicting way to say which way the stock went.
    """
    if not isinstance(value, str) or value not in FULFILLMENT_RECORD_TYPES:
        raise _invalid(field, "must be FULFILL or REVERSAL")
    return value


def normalize_fulfillment_source(value: Any, field: str = SOURCE_ATTRIBUTE) -> str:
    """Validate a ``FulfillmentSource`` (§5.19's closed set)."""
    if not isinstance(value, str) or value not in FULFILLMENT_SOURCES:
        raise _invalid(field, "must be KERNEL_STOCK, SCOUT_CUSTODY, or EXTERNAL_COUNCIL")
    return value


def _optional_id(value: Any, field: str) -> Optional[str]:
    """An optional id: absent means absent, present means a key-safe id."""
    return None if value is None else normalize_inventory_id(value, field)


def _movement_link_rule(source: str, inventory_movement_id: Optional[str]) -> None:
    """A stock fulfillment must name its movement; an external one must not (§5.19).

    The required half keeps a stock change traceable to the movement that made it.
    The forbidden half matters just as much: an ``EXTERNAL_COUNCIL`` row carrying a
    movement id claims a Kernel balance moved when the data model says none did, and
    a reader of the audit trail cannot tell the difference.
    """
    if source in SOURCE_MOVES_STOCK and inventory_movement_id is None:
        raise _invalid(
            INVENTORY_MOVEMENT_ID_ATTRIBUTE,
            f"a {source} fulfillment must name the inventory movement that moved the stock",
        )
    if source == SOURCE_EXTERNAL_COUNCIL and inventory_movement_id is not None:
        raise _invalid(
            INVENTORY_MOVEMENT_ID_ATTRIBUTE,
            "an EXTERNAL_COUNCIL fulfillment moves no Kernel balance, so it has no movement to name",
        )


def _reversal_link_rule(record_type: str, reversal_of_fulfillment_id: Optional[str]) -> None:
    """The reversal link belongs to REVERSAL rows: required there, refused elsewhere.

    Required, because a reversal that does not say what it reverses cannot restore
    "the original demand and only the original stock source" (§5.19) — the original
    record is what names that source. Refused on a FULFILL row, because the link is
    also what decides which sort key the row was written under: a row whose
    ``recordType`` and key disagree about what kind of record it is cannot be read
    back honestly.
    """
    if record_type == RECORD_TYPE_REVERSAL and reversal_of_fulfillment_id is None:
        raise _invalid(REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE, "a REVERSAL must name the fulfillment it reverses")
    if record_type == RECORD_TYPE_FULFILL and reversal_of_fulfillment_id is not None:
        raise _invalid(REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE, "only a REVERSAL names the fulfillment it reverses")


# --- Key builders (data model §6.5) -----------------------------------------------


def fulfillment_partition_key(order_id: str) -> str:
    """The partition holding one Order's whole fulfillment history.

    Idempotent on purpose. This application's Order ids already carry the ``ORDER#``
    prefix — the ``orders`` table is keyed ``{campaignId, orderId}`` and the id is
    ``ORDER#<campaign>#<suffix>``, minted by ``src/utils/order_keys.py`` and
    ``tofu/application/appsync/js-resolvers/lib/order_keys.js`` — while data model
    §6.5 states the fulfillment partition as ``ORDER#<orderId>``. Prefixing blindly
    would produce ``ORDER#ORDER#<campaign>#<suffix>`` and the history read would
    address a partition nothing ever wrote. A bare id still gets the prefix, so both
    spellings that cross the resolver boundary land on one partition.
    """
    identifier = normalize_inventory_id(order_id, ORDER_ID_ATTRIBUTE)
    if identifier.startswith(f"{PK_PREFIX}#"):
        return identifier
    return f"{PK_PREFIX}#{identifier}"


def fulfillment_sort_key(created_at: str, fulfillment_id: str) -> str:
    """Sort key of one fulfillment, in the order a reader wants its history.

    ``createdAt`` is the sort dimension and the id only breaks a same-instant tie, so
    the moment is canonicalized to one UTC spelling first: a ``Z`` row and a
    ``+00:00`` row for one instant would otherwise sort apart under two writers.
    """
    moment = normalize_moment(created_at, CREATED_AT_ATTRIBUTE)
    identifier = normalize_inventory_id(fulfillment_id, FULFILLMENT_ID_ATTRIBUTE)
    return f"{FULFILLMENT_SK_PREFIX}#{moment}#{identifier}"


def reversal_sort_key(original_fulfillment_id: str) -> str:
    """Sort key of the one reversal a fulfillment can ever have (§5.19).

    Deterministic — derived from the reversed id, not from a freshly minted one — so a
    second reversal of the same fulfillment COLLIDES on the key and fails its
    conditional write instead of racing a read of "has this been reversed yet". Two
    readers that both answer "not yet" still cannot both write, which is why no lock
    row or read-then-check appears in this path; the operation's idempotency marker
    is an additional guard, not the mechanism.
    """
    original = normalize_inventory_id(original_fulfillment_id, REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE)
    return f"{REVERSAL_SK_PREFIX}#{original}"


# --- Item builder (the only place this row is built) -------------------------------


def build_fulfillment_item(
    *,
    fulfillment_id: Any,
    order_id: Any,
    campaign_id: Any,
    profile_id: Any,
    unit_id: Any,
    unit_campaign_id: Any,
    line_item_id: Any,
    product_id: Any,
    record_type: Any,
    quantity: Any,
    source: Any,
    actor_account_id: Any,
    created_at: Any,
    inventory_movement_id: Optional[Any] = None,
    reversal_of_fulfillment_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """The §5.19 append-only fulfillment or reversal row, validated as it is built.

    ``unitId``/``unitCampaignId`` are the Order's immutable originating scope and are
    null for an independent sale, so an absent scope is stored as no attribute rather
    than as an empty string, which would read as a scope that exists. The row carries
    no ``version`` (history is corrected by a linked REVERSAL, never by an edit) and
    never ``expiresAtEpoch``: on this table the TTL attribute belongs to the
    idempotency marker rows only (``MARKER_TTL_ATTRIBUTE`` in
    :mod:`src.utils.mutations`), and a TTL here would delete audit history seven days
    after the sale.
    """
    kind = normalize_fulfillment_record_type(record_type)
    origin = normalize_fulfillment_source(source)
    movement_id = _optional_id(inventory_movement_id, INVENTORY_MOVEMENT_ID_ATTRIBUTE)
    reversal_of = _optional_id(reversal_of_fulfillment_id, REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE)
    _movement_link_rule(origin, movement_id)
    _reversal_link_rule(kind, reversal_of)
    identifier = normalize_inventory_id(fulfillment_id, FULFILLMENT_ID_ATTRIBUTE)
    moment = normalize_moment(created_at, CREATED_AT_ATTRIBUTE)
    # The link's presence is what chooses the sort key, and the rules above make it
    # present exactly when ``recordType`` is REVERSAL — so the key and the type of a
    # stored row can never disagree about which kind of record it is.
    sort_key = reversal_sort_key(reversal_of) if reversal_of is not None else fulfillment_sort_key(moment, identifier)
    optional: Dict[str, Any] = {
        UNIT_ID_ATTRIBUTE: _optional_id(unit_id, UNIT_ID_ATTRIBUTE),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: _optional_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        INVENTORY_MOVEMENT_ID_ATTRIBUTE: movement_id,
        REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE: reversal_of,
    }
    return {
        "pk": fulfillment_partition_key(str(order_id)),
        "sk": sort_key,
        ENTITY_TYPE_ATTRIBUTE: FULFILLMENT_ENTITY_TYPE,
        FULFILLMENT_ID_ATTRIBUTE: identifier,
        ORDER_ID_ATTRIBUTE: normalize_inventory_id(order_id, ORDER_ID_ATTRIBUTE),
        CAMPAIGN_ID_ATTRIBUTE: normalize_inventory_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE),
        PROFILE_ID_ATTRIBUTE: normalize_inventory_id(profile_id, PROFILE_ID_ATTRIBUTE),
        LINE_ITEM_ID_ATTRIBUTE: normalize_inventory_id(line_item_id, LINE_ITEM_ID_ATTRIBUTE),
        PRODUCT_ID_ATTRIBUTE: normalize_inventory_id(product_id, PRODUCT_ID_ATTRIBUTE),
        RECORD_TYPE_ATTRIBUTE: kind,
        # §5.19: a positive amount on both record kinds. A reversal's quantity is the
        # positive amount it RESTORED; the direction comes from ``recordType`` alone.
        QUANTITY_ATTRIBUTE: normalize_quantity(quantity, QUANTITY_ATTRIBUTE, minimum=1),
        SOURCE_ATTRIBUTE: origin,
        ACTOR_ACCOUNT_ID_ATTRIBUTE: normalize_required_text(
            actor_account_id, ACTOR_ACCOUNT_ID_ATTRIBUTE, MAX_ID_LENGTH
        ),
        CREATED_AT_ATTRIBUTE: moment,
        **{name: value for name, value in optional.items() if value is not None},
    }


# --- Projections (the only place either GraphQL type is assembled) ----------------


def _count(item: Mapping[str, Any], name: str) -> int:
    """A stored count as a plain ``int``; anything that is not a count reads as 0.

    ``Decimal`` is what a DynamoDB read returns and ``int`` is what this module just
    wrote. A pre-Wave-3 line carries no ``fulfilledQuantity`` at all, and §10.2 says
    that reads as 0 rather than as an error. ``bool`` is refused on purpose: a Python
    bool IS an int and would count as 0 or 1.
    """
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return 0
    return int(value)


def _text(item: Mapping[str, Any], name: str) -> Optional[str]:
    """A stored text attribute as GraphQL sees it, or ``None`` when the row has none."""
    value = item.get(name)
    return value if isinstance(value, str) else None


def fulfillment_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    """The GraphQL ``OrderFulfillment`` view of one stored row (full audit).

    ``pk``/``sk``/``entityType`` stay out: they are storage, and a projection that
    echoes them invites a client to read meaning out of a sort key, which this
    table resolves from the row's own attributes instead (§6.3's rule, inherited).
    """
    return {
        FULFILLMENT_ID_ATTRIBUTE: _text(item, FULFILLMENT_ID_ATTRIBUTE),
        ORDER_ID_ATTRIBUTE: _text(item, ORDER_ID_ATTRIBUTE),
        CAMPAIGN_ID_ATTRIBUTE: _text(item, CAMPAIGN_ID_ATTRIBUTE),
        PROFILE_ID_ATTRIBUTE: _text(item, PROFILE_ID_ATTRIBUTE),
        UNIT_ID_ATTRIBUTE: _text(item, UNIT_ID_ATTRIBUTE),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: _text(item, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        LINE_ITEM_ID_ATTRIBUTE: _text(item, LINE_ITEM_ID_ATTRIBUTE),
        PRODUCT_ID_ATTRIBUTE: _text(item, PRODUCT_ID_ATTRIBUTE),
        RECORD_TYPE_ATTRIBUTE: _text(item, RECORD_TYPE_ATTRIBUTE),
        QUANTITY_ATTRIBUTE: _count(item, QUANTITY_ATTRIBUTE),
        SOURCE_ATTRIBUTE: _text(item, SOURCE_ATTRIBUTE),
        INVENTORY_MOVEMENT_ID_ATTRIBUTE: _text(item, INVENTORY_MOVEMENT_ID_ATTRIBUTE),
        REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE: _text(item, REVERSAL_OF_FULFILLMENT_ID_ATTRIBUTE),
        ACTOR_ACCOUNT_ID_ATTRIBUTE: _text(item, ACTOR_ACCOUNT_ID_ATTRIBUTE),
        CREATED_AT_ATTRIBUTE: _text(item, CREATED_AT_ATTRIBUTE),
    }


def participant_fulfillment_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``ParticipantOrderFulfillment`` view: the admin projection minus the audit pair.

    Derived by subtraction, so the safe projection can never gain a field through an
    omission — see :data:`ADMIN_ONLY_FULFILLMENT_FIELDS`.
    """
    return {
        name: value for name, value in fulfillment_payload(item).items() if name not in ADMIN_ONLY_FULFILLMENT_FIELDS
    }


# --- Order line arithmetic (data model §5.19 line extension) ----------------------


def _order_lines(order: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The Order row's line items as mappings; a row with no list has no lines.

    ``lineItems`` is a list attribute on the existing ``orders`` row. A row whose
    shape this module does not recognize answers as "no such line", so the caller's
    answer is ``INVALID_INPUT`` naming the line rather than a ``TypeError`` from the
    middle of a write plan.
    """
    lines = order.get(LINE_ITEMS_ATTRIBUTE)
    if not isinstance(lines, (list, tuple)):
        return []
    entries: List[Mapping[str, Any]] = []
    for entry in lines:
        if isinstance(entry, Mapping):
            entries.append(entry)
    return entries


def order_line_items(order: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The Order row's line items, as mappings (the public half of :func:`_order_lines`).

    A resolver returning an Order has to project its lines, and it must see exactly the
    lines this module's arithmetic sees — a caller that read the raw attribute would
    treat a malformed entry as a line and write a change against it.
    """
    return _order_lines(order)


def find_order_line(order: Mapping[str, Any], line_item_id: str) -> Optional[Mapping[str, Any]]:
    """The line with this ``lineItemId``, or ``None`` (the public half of :func:`_find_line`).

    The fulfillment resolvers look a line up twice — once to check the request against
    it, once to read the product it names — and one lookup rule has to answer both.
    """
    return _find_line(order, line_item_id)


def _find_line(order: Mapping[str, Any], line_item_id: str) -> Optional[Mapping[str, Any]]:
    """The line whose ``lineItemId`` matches, or ``None``.

    Matched on the attribute, never on position: §5.19 mints ``lineItemId`` precisely
    so a fulfillment can still name its line after a later edit re-orders the list. A
    pre-Wave-3 row carries no id at all, which is "no such line" rather than a guess
    about which line the caller meant.
    """
    for line in _order_lines(order):
        if line.get(LINE_ITEM_ID_ATTRIBUTE) == line_item_id:
            return line
    return None


def line_quantity_violations(order: Mapping[str, Any], line_item_id: str, requested: int) -> Optional[str]:
    """Why this per-line fulfillment is not admissible, or ``None`` when it is.

    Returns a reason instead of raising because the caller has to answer
    ``INVALID_INPUT`` carrying that reason and has staged nothing yet: raising here
    would either bury the reason that tells the Kernel which line to shorten or force
    the caller to re-derive it from the same arithmetic. The string returned is what
    goes in the GraphQL ``message``.

    The three §5.19 line rules: the line must exist, the request must be positive,
    and the line's ordered quantity less what is already fulfilled is the ceiling.
    ``fulfilledQuantity`` absent reads as 0, which is how a pre-Wave-3 Order can be
    fulfilled with no backfill.
    """
    line = _find_line(order, line_item_id)
    if line is None:
        return f"this order has no line item {line_item_id}"
    if requested < 1:
        return f"{QUANTITY_ATTRIBUTE} must be at least 1"
    outstanding = _count(line, QUANTITY_ATTRIBUTE) - _count(line, FULFILLED_QUANTITY_ATTRIBUTE)
    if requested > outstanding:
        return f"line item {line_item_id} has {outstanding} of {_count(line, QUANTITY_ATTRIBUTE)} left unfulfilled"
    return None


def apply_line_fulfillment(order: Mapping[str, Any], line_item_id: str, delta: int) -> List[Dict[str, Any]]:
    """A NEW ``lineItems`` list with one line's ``fulfilledQuantity`` moved by ``delta``.

    ``delta`` is signed — positive to fulfill, negative to reverse — and both bounds
    are enforced against the arithmetic rather than only against the pre-read: the
    count can never go below zero and never above what the line ordered (§5.19:
    ``fulfilledQuantity`` "cannot exceed ordered quantity"). Either breach is
    ``CONFLICT``, not ``INVALID_INPUT``, because the caller already validated the
    request against its own read: the row that no longer permits it moved underneath
    the request.

    The caller's row is never mutated, and every line is copied rather than edited in
    place. The mutation re-checks the ``fulfillmentVersion`` of the snapshot it read
    afterwards, and an in-place edit of that snapshot would stale its own condition
    and fail the write with a spurious conflict — the #433 lesson, learned twice in
    this codebase.
    """
    line = _find_line(order, line_item_id)
    if line is None:
        raise AppError(ErrorCode.CONFLICT, f"this order has no line item {line_item_id}")
    amount = normalize_signed_delta(delta, "delta", nonzero=True)
    updated = _count(line, FULFILLED_QUANTITY_ATTRIBUTE) + amount
    ceiling = _count(line, QUANTITY_ATTRIBUTE)
    if updated < 0 or updated > ceiling:
        raise AppError(
            ErrorCode.CONFLICT,
            f"line item {line_item_id} cannot hold {FULFILLED_QUANTITY_ATTRIBUTE} of {updated}; it orders {ceiling}",
        )
    return [
        dict(entry, **{FULFILLED_QUANTITY_ATTRIBUTE: updated}) if entry is line else dict(entry)
        for entry in _order_lines(order)
    ]


# --- Concurrency guard (data model §5.19 fulfillmentVersion) ----------------------


def fulfillment_version_condition(expected_version: int) -> Dict[str, Any]:
    """The ``TransactWriteItems`` condition pieces for the Order row's version.

    Every fulfillment and every reversal increments the Order's
    ``fulfillmentVersion``, including an external-Council change that touches no
    inventory version, so this guard is what serializes fulfill, reverse, and a line
    edit against one Order (§5.19).

    Rows written before Wave 3 carry no ``fulfillmentVersion`` attribute at all, and
    a plain equality condition against a missing attribute fails against real
    DynamoDB: an unfulfilled pre-Wave-3 Order would then be unfulfillable without a
    backfill. So the guard for version 0 is the disjunction
    ``attribute_not_exists(#fulfillmentVersion) OR #fulfillmentVersion = :zero``,
    which reads "nobody has fulfilled this yet" for both spellings of zero.
    """
    placeholder = f"#{FULFILLMENT_VERSION_ATTRIBUTE}"
    equality = f"{placeholder} = :expectedFulfillmentVersion"
    condition = f"attribute_not_exists({placeholder}) OR {equality}" if expected_version == 0 else equality
    return {
        "ConditionExpression": condition,
        "ExpressionAttributeNames": {placeholder: FULFILLMENT_VERSION_ATTRIBUTE},
        "ExpressionAttributeValues": {":expectedFulfillmentVersion": wire_value(expected_version)},
    }


# --- Identity minting and the Order row's address ---------------------------------


def new_fulfillment_id() -> str:
    """Mint one fulfillment/reversal identity (§5.19).

    A UUID, for the reason the movement ids are: two concurrent fulfillments of one
    Order must not collide on an id a writer guessed, and the id is what the
    deterministic reversal key is later derived from, so a collision would silently
    make one of two reversals impossible.
    """
    return str(uuid.uuid4())


def order_row_key(order_id: Any) -> Optional[Dict[str, str]]:
    """The ``{campaignId, orderId}`` key of the Order row this id addresses.

    The ``orders`` table is hash-keyed on ``campaignId``, so a fulfillment request
    that names only an Order still has to be resolved to that pair, and the id itself
    carries it: ``ORDER#<bare campaign id>#<suffix>`` (``src/utils/order_keys.py``).
    Deriving it from the id is what makes the follow-up read a strongly consistent
    ``GetItem`` rather than a GSI lookup — the rule this codebase applies everywhere
    an authorization decision follows a read.

    ``None`` means the value cannot address a campaign-keyed Order at all: a legacy
    ``ORDER#<uuid>`` row embeds no campaign, and guessing one would let a fulfillment
    write against whichever row the guess happened to hit.
    """
    parsed = parse_order_id(order_id)
    campaign_id = ensure_campaign_id(parsed[0]) if parsed is not None else None
    if campaign_id is None:
        return None
    return {"campaignId": campaign_id, "orderId": str(order_id)}


# --- Reads (data model §6.5 partition) --------------------------------------------


def fulfillment_rows(order_id: Any) -> List[Dict[str, Any]]:
    """Every fulfillment and reversal of one Order, in sort-key (oldest-first) order.

    Read consistently, for both callers. The audit query has to show an admin the
    fulfillment they just recorded — a history that lags their own write reads as a
    lost sale — and the reversal path is a read that decides a write, which is the
    same rule the inventory reads follow (§8.4). The partition is the whole history
    of one Order, so this stays one query with no index to be stale.
    """
    return list(
        query_all_items(
            tables.order_fulfillments,
            {
                "KeyConditionExpression": "#pk = :pk",
                "ExpressionAttributeNames": {"#pk": "pk"},
                "ExpressionAttributeValues": {":pk": fulfillment_partition_key(str(order_id))},
                "ConsistentRead": True,
            },
        )
    )


def find_fulfillment(order_id: Any, fulfillment_id: Any) -> Optional[Dict[str, Any]]:
    """The one record in this Order's history carrying ``fulfillment_id``.

    Matched on the attribute, and scoped to the Order's own partition rather than
    searched globally: an id from another Order is not found here, which is what
    makes "wrong parent" a ``NOT_FOUND`` instead of a reversal of someone else's
    fulfillment (§2.4.4's wrong-parent case).
    """
    wanted = normalize_inventory_id(fulfillment_id, FULFILLMENT_ID_ATTRIBUTE)
    for row in fulfillment_rows(order_id):
        if row.get(FULFILLMENT_ID_ATTRIBUTE) == wanted:
            return row
    return None


# --- Transaction actions ----------------------------------------------------------


def wire_line_item_value(value: Any) -> Dict[str, Any]:
    """Encode one line-item attribute in DynamoDB wire form.

    ``mutations.wire_value`` is scalar-only and would store a float price as a
    ``STRING``; the ``orders`` row's ``lineItems`` is a list of maps whose prices are
    numbers the JS write path stored as ``N``. Re-writing them as strings would
    silently change the type of every price on the row, so this encoder mirrors the
    JS types: numbers stay ``N`` (``repr`` keeps a float's exact decimal, and a read
    back of a ``Decimal`` stays exact through ``str``).

    It is total over every type a line-item map can hold — number, boolean, null, text
    — rather than only the four attributes written so far, because a fulfillment
    re-writes the WHOLE list: an attribute this encoder did not recognize would be
    stored as its ``str()`` and every reader of the row would see a string where a
    number used to be. The pin in ``tests/unit/test_order_fulfillment_models.py`` holds
    each branch.
    """
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, Decimal)):
        return {"N": str(value)}
    if isinstance(value, float):
        return {"N": repr(value)}
    if value is None:
        return {"NULL": True}
    return {"S": str(value)}


def wire_line_items(lines: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """The whole ``lineItems`` attribute in wire form (``L`` of ``M``)."""
    return {"L": [{"M": {name: wire_line_item_value(value) for name, value in line.items()}} for line in lines]}


def order_fulfillment_update_action(
    *, order: Mapping[str, Any], line_items: List[Mapping[str, Any]], expected_version: int, occurred_at: str
) -> tuple[str, Dict[str, Any]]:
    """The one conditioned ``UpdateItem`` this fulfillment makes on the Order row.

    Three attributes move together: the line list carrying the new
    ``fulfillmentQuantity``, the ``fulfillmentVersion`` incremented from the value the
    caller named, and ``updatedAt``. The version is set absolutely rather than
    incremented because ``expected_version`` is already pinned in the condition from
    :func:`fulfillment_version_condition` — the write cannot land on a row that moved,
    so ``expected + 1`` is provably the next version when it lands.

    The condition is why no read-then-write pair is needed here, and why this is the
    only write shape an Order row gets from this surface: a fulfillment never creates
    or deletes an Order, and never touches anything but these three attributes, so
    the Order's create/delete owners (the ``createOrder``/``publicCreateOrder``
    pipelines and the delete cascades) stay single.
    """
    condition = fulfillment_version_condition(expected_version)
    names = dict(condition["ExpressionAttributeNames"])
    names["#" + LINE_ITEMS_ATTRIBUTE] = LINE_ITEMS_ATTRIBUTE
    names["#" + FULFILLMENT_VERSION_ATTRIBUTE] = FULFILLMENT_VERSION_ATTRIBUTE
    names["#updatedAt"] = "updatedAt"
    values = dict(condition["ExpressionAttributeValues"])
    values[":lineItems"] = wire_line_items(line_items)
    values[":nextFulfillmentVersion"] = wire_value(expected_version + 1)
    values[":updatedAt"] = wire_value(normalize_moment(occurred_at, "updatedAt"))
    return (
        "Update",
        {
            "TableName": tables.orders.table_name,
            "Key": wire_key({"campaignId": order[CAMPAIGN_ID_ATTRIBUTE], "orderId": order[ORDER_ID_ATTRIBUTE]}),
            "UpdateExpression": (
                "SET #lineItems = :lineItems, #fulfillmentVersion = :nextFulfillmentVersion, #updatedAt = :updatedAt"
            ),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ConditionExpression": condition["ConditionExpression"],
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_fulfillment_action(item: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Append one fulfillment or reversal row, conditional on it not existing yet.

    The condition is the whole enforcement of "at most one reversal per fulfillment":
    the reversal's sort key is deterministic (:func:`reversal_sort_key`), so the
    second reversal of one fulfillment fails this condition rather than racing a
    read. Same shape as the movement append in :mod:`src.utils.inventory_models`, and
    for the same reason — history is corrected by a new linked row, never by an edit.
    """
    return (
        "Put",
        {
            "TableName": tables.order_fulfillments.table_name,
            "Item": {name: wire_value(value) for name, value in item.items()},
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )
