"""
Order operations handlers: custody-mode createOrder and individual
fulfillment/reversal (Show & Sell wave 3, impact map 3.2 + r2 C-1).

CUSTODY CREATE (r2 C-1 architecture): the AppSync pipeline keeps the
existing JS steps for the NONE path — no JS port. A router function invokes
this Lambda for every createOrder; the handler answers ``{"__continue__":
True}`` for NONE/absent mode (the pipeline then runs the legacy
create_order_fn exactly as pinned by the golden oracles) and executes the
custody transaction for CONSUME_SCOUT_CUSTODY, whose result the router
early-returns, skipping the legacy write step.

The custody transaction (ONE TransactWriteItems):
  Put order row (with OrderOrigin, fulfillmentVersion 0, stable line ids,
      fulfilledQuantity 0 — the wave-3 additive shape)
  per-line Update of the Scout's CUSTODY row (with-Scout -= qty, version
      + sufficiency conditioned)
  Put MOVEMENT row (SALE, with-Scout delta)
  Update the campaign's denormalized totals (the JS sync step is skipped by
      the early return, so the totals ride inside the same transaction)
  Put the idempotency marker (committed-replay equality)

The order-id grammar is ORDER#<campaign-without-prefix>#<suffix> (one
owner: js-resolvers/lib/order_keys.js #534); the Python side mirrors it
and the JS parser reads these ids back.

FULFILL / REVERSE: append-only order_fulfillments rows
(REVERSAL#<originalId> deterministic ids), line fulfilledQuantity updated
inside the order row under fulfillmentVersion optimistic concurrency, and
kernel-stock source moves mirrored in unit inventory.
"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_strict_int,
    )
    from utils.auth import check_profile_access
    from utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        from_dynamodb_json,
        idem_expiry_epoch,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, strip_prefix
    from utils.logging import get_logger
    from utils.unit_auth import require_unit_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_strict_int,
    )
    from ..utils.auth import check_profile_access
    from ..utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        from_dynamodb_json,
        idem_expiry_epoch,
        tables,
    )
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id, strip_prefix
    from ..utils.logging import get_logger
    from ..utils.unit_auth import require_unit_admin

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)

IDEM_HASH = "__IDEM__"
MOVEMENT_PREFIX = "MOVEMENT#"
BALANCE_PREFIX = "BALANCE#"
CUSTODY_PREFIX = "CUSTODY#"

CONTINUE = {"__continue__": True}
FULFILLMENT_MODE_CUSTODY = "CONSUME_SCOUT_CUSTODY"
SOURCES = ("KERNEL_STOCK", "SCOUT_CUSTODY", "EXTERNAL_COUNCIL")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return str(moment.isoformat()).replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _fingerprint(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _require_caller(event: Dict[str, Any]) -> str:
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller)


def _marker_item_key(actor: str, scope: str, key: str) -> str:
    return f"{actor}#{scope}#{key}"


def _get_marker(actor: str, scope: str, key: str) -> Optional[Dict[str, Any]]:
    response = tables.units.get_item(
        Key={"unitId": IDEM_HASH, "itemKey": _marker_item_key(actor, scope, key)},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


class _MarkerJsonEncoder(json.JSONEncoder):
    """Money fields are Decimals at transaction time (the boto3 client
    rejects floats); the marker result must still serialize deterministically
    for the committed-replay read."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _marker_put(
    actor: str, scope: str, key: str, fingerprint: str, result: Optional[Dict[str, Any]], now: int
) -> Dict[str, Any]:
    # Order results carry Decimal money, which moto's transaction layer (and
    # JSON generally) cannot embed as nested maps; the result rides as a JSON
    # string and is parsed back on replay (idemResultJson). Markers whose
    # results are natively JSON-safe (the other Show & Sell handlers) keep
    # the plain idemResult form.
    item: Dict[str, Any] = {
        "unitId": IDEM_HASH,
        "itemKey": _marker_item_key(actor, scope, key),
        "idemFingerprint": fingerprint,
        "idemCommittedAtEpoch": now,
        "expiresAtEpoch": idem_expiry_epoch(now),
    }
    if result is not None:
        item["idemResultJson"] = json.dumps(result, cls=_MarkerJsonEncoder, sort_keys=True)
    return {
        "Put": {
            "TableName": tables.units.table_name,
            "Item": item,
            "ConditionExpression": "attribute_not_exists(itemKey)",
        }
    }


def _check_marker(marker: Optional[Dict[str, Any]], fingerprint: str) -> Optional[Dict[str, Any]]:
    if marker is None:
        return None
    if marker.get("idemFingerprint") != fingerprint:
        raise AppError(ErrorCode.CONFLICT, "Idempotency key was already used with a different request")
    raw = marker.get("idemResultJson")
    if isinstance(raw, str):
        return cast(Dict[str, Any], json.loads(raw))
    result = marker.get("idemResult")
    if not isinstance(result, dict):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Idempotency marker is missing its committed result")
    return cast(Dict[str, Any], from_dynamodb_json(result))


def _execute_replayable(plan: List[Dict[str, Any]], marker: Optional[Dict[str, Any]]) -> None:
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if marker is not None and plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise


# ---------------------------------------------------------------------------
# Order-key grammar (#534 JS-owned; Python mirror)
# ---------------------------------------------------------------------------


def build_order_key(campaign_id: str, suffix: str) -> str:
    campaign_without_prefix = strip_prefix(campaign_id)
    return f"ORDER#{campaign_without_prefix}#{suffix}"


def parse_order_key(order_id: str) -> Optional[Dict[str, str]]:
    if not isinstance(order_id, str) or not order_id.startswith("ORDER#"):
        return None
    parts = order_id.split("#")
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return {"campaignId": f"CAMPAIGN#{parts[1]}", "suffix": parts[2]}


# ---------------------------------------------------------------------------
# Line enrichment (mirrors lib/line_items.js integer-cents math exactly)
# ---------------------------------------------------------------------------


def _price_cents(product: Dict[str, Any]) -> int:
    """Unit price in integer cents (mirrors lib/line_items.js math)."""
    price = product.get("price")
    if not isinstance(price, (int, float, Decimal)) or isinstance(price, bool) or price < 0:
        raise AppError(ErrorCode.INVALID_INPUT, f"Product {product.get('productId')} has no valid price")
    return round(float(price) * 100)


def _enrich_line_items(
    line_items: List[Dict[str, Any]], catalog: Dict[str, Any]
) -> tuple[List[Dict[str, Any]], Decimal]:
    products = {
        p["productId"]: p
        for p in (catalog.get("products") or [])
        if isinstance(p, dict) and isinstance(p.get("productId"), str)
    }
    enriched: List[Dict[str, Any]] = []
    total_cents = 0
    for line in line_items:
        quantity = line.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise AppError(ErrorCode.INVALID_INPUT, f"Quantity must be at least 1 (got {quantity})")
        product = products.get(line.get("productId"))
        if product is None:
            raise AppError(ErrorCode.INVALID_INPUT, f"Product {line.get('productId')} not found in catalog")
        price_cents = _price_cents(product)
        line_cents = price_cents * quantity
        total_cents += line_cents
        enriched.append(
            {
                "lineItemId": str(uuid.uuid4()),
                "productId": product["productId"],
                "productName": product.get("productName"),
                "quantity": quantity,
                # Legacy money is Float dollars; the wire form of a transaction
                # Put is the boto3 CLIENT, which serializes Decimals but rejects
                # floats. str() keeps the short repr so 0.1 + 0.2 math matches
                # the JS pipeline's golden oracles.
                "pricePerUnit": Decimal(str(price_cents / 100)),
                "subtotal": Decimal(str(line_cents / 100)),
                "fulfilledQuantity": 0,
            }
        )
    return enriched, Decimal(str(total_cents / 100))


# ---------------------------------------------------------------------------
# Custody createOrder
# ---------------------------------------------------------------------------


def _allocate_consumption(enriched: List[Dict[str, Any]], available: Dict[str, int]) -> Dict[str, int]:
    """Deterministic spec-8.5 allocation: lines consume in order against the
    product's remaining availability; per-line take is min(quantity, left).
    Mutates each line's fulfilledQuantity to its consumed amount and returns
    per-product consumption totals."""
    remaining = dict(available)
    consumed_totals: Dict[str, int] = {}
    for line in enriched:
        product_id = line["productId"]
        take = min(line["quantity"], remaining.get(product_id, 0))
        remaining[product_id] = remaining.get(product_id, 0) - take
        consumed_totals[product_id] = consumed_totals.get(product_id, 0) + take
        line["fulfilledQuantity"] = take
    return consumed_totals


def _unit_campaign_for_custody(campaign: Dict[str, Any]) -> str:
    unit_campaign_id = campaign.get("unitCampaignKey")
    if not isinstance(unit_campaign_id, str) or not unit_campaign_id:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "CONSUME_SCOUT_CUSTODY requires a Campaign joined to a Unit Campaign",
        )
    return unit_campaign_id


def _validate_custody_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic validation for custody createOrder (convention rule 1):
    every failure here depends only on the request, never on table state."""
    resolved: Dict[str, Any] = {}
    resolved["customerName"] = require_bounded_str(args, "customerName", 100)
    resolved["campaignId"] = require_bounded_str(args, "campaignId", 100)
    resolved["profileId"] = require_bounded_str(args, "profileId", 100)
    resolved["paymentMethod"] = require_bounded_str(args, "paymentMethod", 50)
    order_date = args.get("orderDate")
    if not isinstance(order_date, str) or not order_date.strip():
        raise AppError(ErrorCode.INVALID_INPUT, "Order date is required")
    resolved["orderDate"] = order_date
    line_items = args.get("lineItems")
    if not isinstance(line_items, list) or not line_items:
        raise AppError(ErrorCode.INVALID_INPUT, "Order must have at least one line item")
    resolved["lineItems"] = line_items
    idem_key = args.get("idempotencyKey")
    if idem_key is not None:
        idem_key = require_idempotency_key(args)
    resolved["idempotencyKey"] = idem_key
    return resolved


def _read_custody_holds(unit_campaign_id: str, profile_id: str, products: List[str]) -> Dict[str, int]:
    """Consistent read of the with-Scout holdings for each product (one read
    per product), naming insufficiency BEFORE the transaction."""
    holds: Dict[str, int] = {}
    for product_id in products:
        if product_id in holds:
            continue
        item = (
            tables.inventory.get_item(
                Key={
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"{CUSTODY_PREFIX}{profile_id}#{product_id}",
                },
                ConsistentRead=True,
            ).get("Item")
            or {}
        )
        holds[product_id] = int(item.get("withScoutQty", 0))
    return holds


def _custody_create_plan(
    *,
    order_item: Dict[str, Any],
    unit_campaign_id: str,
    profile_id: str,
    draw_totals: Dict[str, int],
    caller: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """Order Put + per-product custody draw/movement + campaign totals. The
    custody draw aggregates per product: two order lines for the same product
    must produce ONE custody update (a transaction cannot address one key
    twice — and per-line draws could over-draw a single sufficiency check)."""
    plan: List[Dict[str, Any]] = [
        {
            "Put": {
                "TableName": tables.orders.table_name,
                "Item": order_item,
                "ConditionExpression": "attribute_not_exists(orderId)",
            }
        }
    ]
    for product_id, draw in draw_totals.items():
        plan.append(
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{CUSTODY_PREFIX}{profile_id}#{product_id}",
                    },
                    "UpdateExpression": "ADD withScoutQty :neg SET version = version + :one",
                    "ConditionExpression": "attribute_exists(itemKey) AND withScoutQty >= :min",
                    "ExpressionAttributeValues": {":neg": -draw, ":one": 1, ":min": draw},
                }
            }
        )
        plan.append(
            {
                "Put": {
                    "TableName": tables.inventory.table_name,
                    "Item": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{uuid.uuid4()}",
                        "productId": product_id,
                        "movementType": "SALE",
                        "withScoutDelta": -draw,
                        "orderId": order_item["orderId"],
                        "actorAccountId": caller,
                        "occurredAt": stamp,
                    },
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            }
        )
    plan.append(
        {
            "Update": {
                "TableName": tables.campaigns.table_name,
                "Key": {"profileId": order_item["profileId"], "campaignId": order_item["campaignId"]},
                "UpdateExpression": "ADD #totalOrders :count, #totalRevenue :revenue",
                "ConditionExpression": "attribute_exists(campaignId)",
                "ExpressionAttributeNames": {"#totalOrders": "totalOrders", "#totalRevenue": "totalRevenue"},
                "ExpressionAttributeValues": {":count": 1, ":revenue": round(order_item["totalAmount"], 2)},
            }
        }
    )
    return plan


def _stash_campaign_and_catalog(event: Dict[str, Any], profile_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    stash = event.get("stash") or {}
    campaign = stash.get("campaign")
    catalog = stash.get("catalog")
    if not isinstance(campaign, dict) or campaign.get("profileId") != profile_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Campaign does not belong to the specified profile")
    if not isinstance(catalog, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "Catalog could not be loaded for this campaign")
    return campaign, catalog


def _draw_totals(enriched: List[Dict[str, Any]]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for line in enriched:
        totals[line["productId"]] = totals.get(line["productId"], 0) + line["quantity"]
    return totals


def _create_time_fulfillments(
    enriched: List[Dict[str, Any]],
    resolved: Dict[str, Any],
    order_id: str,
    unit_campaign_id: str,
    caller: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """ADR 0002 on the custody path: consumed Scout custody IS a fulfillment.
    Each line that consumed stock gets a SCOUT_CUSTODY record with quantity
    equal to the CONSUMED amount (spec 8.5 min-consumption), written IN THE
    SAME TRANSACTION. Unconsumed lines get no record and stay unfulfilled."""
    return [
        {
            "fulfillmentId": str(uuid.uuid4()),
            "orderId": order_id,
            "campaignId": resolved["campaignId"],
            "profileId": resolved["profileId"],
            "unitId": None,
            "unitCampaignId": unit_campaign_id,
            "lineItemId": line["lineItemId"],
            "productId": line["productId"],
            "recordType": "FULFILLMENT",
            "quantity": int(line["fulfilledQuantity"]),
            "source": "SCOUT_CUSTODY",
            "reversalOfFulfillmentId": None,
            "actorAccountId": caller,
            "createdAt": stamp,
        }
        for line in enriched
        if int(line["fulfilledQuantity"]) > 0
    ]


def _stamp_order_extras(order_item: Dict[str, Any], args: Dict[str, Any]) -> None:
    if args.get("customerPhone"):
        order_item["customerPhone"] = args["customerPhone"]
    if args.get("customerAddress"):
        order_item["customerAddress"] = args["customerAddress"]
    if args.get("notes"):
        order_item["notes"] = args["notes"]


def _raise_custody_cancel(
    exc: TransactionCancelledError, plan: List[Dict[str, Any]], marker: Optional[Dict[str, Any]]
) -> None:
    """Map a custody-create cancellation to its domain error (never returns)."""
    if marker is not None and plan.index(marker) in exc.failed_indexes:
        raise AppError(
            ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
        ) from None
    # A custody sufficiency or totals condition lost the race after the
    # pre-read: name it instead of surfacing a bare cancellation.
    raise AppError(
        ErrorCode.CONFLICT,
        "Stock or campaign state changed concurrently; retry the order",
        details={"reason": "INSUFFICIENT_CUSTODY"},
    ) from None


def _custody_response_item(
    order_item: Dict[str, Any], create_time_fulfillments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """The committed-replay result is the FULL response: the normalized order
    plus the parent-supplied Order.fulfillments participant-safe projection
    (impact map 3.2: the field resolves from the parent when supplied, so the
    mutation response carries no admin-only fields)."""
    response_item = cast(Dict[str, Any], from_dynamodb_json(order_item))
    response_item["fulfillments"] = [
        {
            "fulfillmentId": f["fulfillmentId"],
            "orderId": f["orderId"],
            "campaignId": f["campaignId"],
            "profileId": f["profileId"],
            "lineItemId": f["lineItemId"],
            "productId": f["productId"],
            "recordType": f["recordType"],
            "quantity": f["quantity"],
            "source": f["source"],
            "createdAt": f["createdAt"],
        }
        for f in create_time_fulfillments
    ]
    return response_item


def _route_mode(args: Dict[str, Any]) -> Optional[str]:
    """Resolve the custody router's mode decision: None means the pipeline
    should CONTINUE to the legacy NONE writer; a returned string is the mode
    this Lambda must execute (unknown modes are refused loudly)."""
    mode = args.get("fulfillmentMode")
    if mode is None or mode == "NONE":
        return None
    if mode != FULFILLMENT_MODE_CUSTODY:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown fulfillmentMode: {mode}")
    return mode


def _fulfillment_puts(create_time_fulfillments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "Put": {
                "TableName": tables.order_fulfillments.table_name,
                "Item": fulfillment,
                "ConditionExpression": "attribute_not_exists(fulfillmentId)",
            }
        }
        for fulfillment in create_time_fulfillments
    ]


def custody_create_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Router entry: answer CONTINUE for the NONE path; run the custody
    transaction for CONSUME_SCOUT_CUSTODY. Invoked as a pipeline step, so
    the earlier pipeline steps (profile WRITE auth, campaign + catalog
    loads) have already run; their results arrive in stash."""
    args = (event.get("arguments") or {}).get("input") or {}
    if _route_mode(args) is None:
        return dict(CONTINUE)

    resolved = _validate_custody_input(args)
    caller = _require_caller(event)
    campaign, catalog = _stash_campaign_and_catalog(event, resolved["profileId"])

    fingerprint = _fingerprint({**args, "actor": caller})
    marker_scope = "createOrderCustody"
    idem_key = resolved["idempotencyKey"]
    if idem_key is not None:
        replayed = _check_marker(_get_marker(caller, marker_scope, idem_key), fingerprint)
        if replayed is not None:
            return replayed

    unit_campaign_id = _unit_campaign_for_custody(campaign)
    enriched, total_amount = _enrich_line_items(resolved["lineItems"], catalog)

    # Spec 8.5 min-consumption (QA divergence + SS-SM-04 partial-sale oracle):
    # custody consumption per product is min(ordered, available). A shortfall
    # NEVER blocks the order: the consumed portion fulfills, the remainder
    # stays unfulfilled, custody never goes negative.
    available = _read_custody_holds(unit_campaign_id, resolved["profileId"], list(_draw_totals(enriched)))
    consumed_totals = _allocate_consumption(enriched, available)

    now = _utcnow()
    stamp = _iso(now)
    order_id = build_order_key(resolved["campaignId"], str(uuid.uuid4()))
    create_time_fulfillments = _create_time_fulfillments(enriched, resolved, order_id, unit_campaign_id, caller, stamp)

    order_item: Dict[str, Any] = {
        "orderId": order_id,
        "profileId": resolved["profileId"],
        "campaignId": resolved["campaignId"],
        "customerName": resolved["customerName"],
        "orderDate": resolved["orderDate"],
        "paymentMethod": resolved["paymentMethod"],
        "lineItems": enriched,
        "totalAmount": total_amount,
        "origin": {
            "kind": "UNIT_CAMPAIGN",
            "unitCampaignId": unit_campaign_id,
            "sourceCampaignId": resolved["campaignId"],
        },
        "fulfillmentVersion": 0,
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    _stamp_order_extras(order_item, args)

    plan = _custody_create_plan(
        order_item=order_item,
        unit_campaign_id=unit_campaign_id,
        profile_id=resolved["profileId"],
        draw_totals=consumed_totals,
        caller=caller,
        stamp=stamp,
    )
    plan.extend(_fulfillment_puts(create_time_fulfillments))
    # The committed-replay result is the FULL response (parent-supplied
    # Order.fulfillments included), computed before the commit — every value
    # is deterministic at plan time, and the marker/effect write atomically.
    response_item = _custody_response_item(order_item, create_time_fulfillments)
    marker: Optional[Dict[str, Any]] = None
    if idem_key is not None:
        marker = _marker_put(caller, marker_scope, idem_key, fingerprint, response_item, _epoch(now))
        plan.append(marker)

    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        _raise_custody_cancel(exc, plan, marker)
    return response_item


# ---------------------------------------------------------------------------
# Fulfillment / reversal
# ---------------------------------------------------------------------------


def _load_order(order_id: str) -> Dict[str, Any]:
    key = parse_order_key(order_id)
    if key is None:
        raise AppError(ErrorCode.NOT_FOUND, "Order not found")
    item = tables.orders.get_item(Key={"campaignId": key["campaignId"], "orderId": order_id}, ConsistentRead=True).get(
        "Item"
    )
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Order not found")
    return dict(item)


def _authorize_fulfillment(order: Dict[str, Any], caller: str) -> None:
    if check_profile_access(caller, order["profileId"], "WRITE"):
        return
    origin = order.get("origin") or {}
    unit_campaign_id = origin.get("unitCampaignId")
    if isinstance(unit_campaign_id, str) and unit_campaign_id:
        uc = tables.unit_campaigns.get_item(
            Key={"unitCampaignId": unit_campaign_id, "itemKey": "METADATA"}, ConsistentRead=True
        ).get("Item")
        if isinstance(uc, dict):
            try:
                require_unit_admin(tables.units, uc["unitId"], caller)
                return
            except AppError:
                pass
    raise AppError(ErrorCode.FORBIDDEN, "You do not have access to fulfill this order")


def _load_order_for_fulfillment(
    order_id: str, caller: str, expected_version: int
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Shared load-and-guard for fulfill/reverse: order exists, caller may
    act, fulfillmentVersion matches."""
    order = _load_order(order_id)
    _authorize_fulfillment(order, caller)
    if int(order.get("fulfillmentVersion", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "Fulfillment state changed concurrently", details={"reason": "VERSION_MISMATCH"}
        )
    lines = order.get("lineItems") or []
    if not isinstance(lines, list):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Order lineItems is malformed")
    return order, lines


def _require_fulfillment_version(args: Dict[str, Any]) -> int:
    expected_version = require_strict_int(args, "expectedFulfillmentVersion")
    if expected_version < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedFulfillmentVersion must not be negative")
    return int(expected_version)


def _find_line_index(lines: List[Dict[str, Any]], line_item_id: str) -> int:
    for index, line in enumerate(lines):
        if line.get("lineItemId") == line_item_id:
            return index
    raise AppError(ErrorCode.NOT_FOUND, "Line item not found")


def _kernel_fulfill_entries(
    unit_campaign_id: str,
    product_id: str,
    quantity: int,
    order_id: str,
    caller: str,
    stamp: str,
    movement_id: str,
) -> List[Dict[str, Any]]:
    """Inventory balance draw + movement for a KERNEL_STOCK fulfillment."""
    return [
        {
            "Update": {
                "TableName": tables.inventory.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"},
                "UpdateExpression": "ADD kernelPhysicalQty :neg SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "attribute_exists(itemKey) AND kernelPhysicalQty >= :min",
                "ExpressionAttributeValues": {
                    ":neg": -quantity,
                    ":one": 1,
                    ":min": quantity,
                    ":ua": stamp,
                },
            }
        },
        {
            "Put": {
                "TableName": tables.inventory.table_name,
                "Item": {
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{movement_id}",
                    "productId": product_id,
                    "movementType": "FULFILL",
                    "kernelPhysicalDelta": -quantity,
                    "orderId": order_id,
                    "actorAccountId": caller,
                    "occurredAt": stamp,
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
    ]


def _kernel_fulfill_context(
    origin: Dict[str, Any],
    product_id: str,
    quantity: int,
    order_id: str,
    caller: str,
    stamp: str,
    movement_id: str,
) -> Optional[tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """KERNEL_STOCK fulfillments draw unit inventory in the same transaction.
    Returns (entries, projected position) or None when the order has no unit
    origin (kernel draw is impossible; caller treats it as no inventory leg)."""
    unit_campaign_id = origin.get("unitCampaignId")
    if not isinstance(unit_campaign_id, str) or not unit_campaign_id:
        return None
    balance = tables.inventory.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"},
        ConsistentRead=True,
    ).get("Item")
    balance_version = int(balance.get("version", 0)) if isinstance(balance, dict) else 0
    kernel_qty = int(balance.get("kernelPhysicalQty", 0)) if isinstance(balance, dict) else 0
    if kernel_qty - quantity < 0:
        raise AppError(
            ErrorCode.CONFLICT, "Not enough kernel stock to fulfill", details={"reason": "INSUFFICIENT_STOCK"}
        )
    position = {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "balance": {
            "unitCampaignId": unit_campaign_id,
            "productId": product_id,
            "kernelPhysicalQty": kernel_qty - quantity,
            "soldInPossessionQty": int(balance.get("soldInPossessionQty", 0)) if isinstance(balance, dict) else 0,
            "councilOnOrderQty": int(balance.get("councilOnOrderQty", 0)) if isinstance(balance, dict) else 0,
            "version": balance_version + 1,
        },
    }
    return _kernel_fulfill_entries(
        unit_campaign_id, product_id, quantity, order_id, caller, stamp, movement_id
    ), position


def fulfill_individual_order_line(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    order_id = require_bounded_str(args, "orderId", 100)
    line_item_id = require_bounded_str(args, "lineItemId", 100)
    quantity = require_strict_int(args, "quantity")
    if quantity < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")
    source = require_str_enum(args, "source", SOURCES)
    expected_version = _require_fulfillment_version(args)
    key = require_idempotency_key(args)

    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "fulfillOrderLine", key), fingerprint)
    if replayed is not None:
        return replayed

    order, lines = _load_order_for_fulfillment(order_id, caller, expected_version)
    index = _find_line_index(lines, line_item_id)
    line = lines[index]
    already = int(line.get("fulfilledQuantity", 0))
    if already + quantity > int(line["quantity"]):
        raise AppError(
            ErrorCode.CONFLICT,
            "Fulfillment would exceed the ordered quantity",
            details={"reason": "FULFILLMENT_INVALIDATED"},
        )

    now = _utcnow()
    stamp = _iso(now)
    movement_id = str(uuid.uuid4())
    origin = order.get("origin") or {}
    fulfillment = {
        "fulfillmentId": str(uuid.uuid4()),
        "orderId": order_id,
        "campaignId": order["campaignId"],
        "profileId": order["profileId"],
        "unitId": None,
        "unitCampaignId": origin.get("unitCampaignId"),
        "lineItemId": line_item_id,
        "productId": line["productId"],
        "recordType": "FULFILLMENT",
        "quantity": quantity,
        "source": source,
        "reversalOfFulfillmentId": None,
        "actorAccountId": caller,
        "createdAt": stamp,
    }
    plan: List[Dict[str, Any]] = [
        {
            "Put": {
                "TableName": tables.order_fulfillments.table_name,
                "Item": fulfillment,
                "ConditionExpression": "attribute_not_exists(fulfillmentId)",
            }
        },
        {
            "Update": {
                "TableName": tables.orders.table_name,
                "Key": {"campaignId": order["campaignId"], "orderId": order_id},
                "UpdateExpression": (
                    f"SET lineItems[{index}].fulfilledQuantity = :fq, fulfillmentVersion = :next, updatedAt = :ua"
                ),
                "ConditionExpression": "fulfillmentVersion = :expected",
                "ExpressionAttributeValues": {
                    ":fq": already + quantity,
                    ":next": expected_version + 1,
                    ":expected": expected_version,
                    ":ua": stamp,
                },
            }
        },
    ]
    inventory_position: Optional[Dict[str, Any]] = None
    if source == "KERNEL_STOCK":
        kernel = _kernel_fulfill_context(origin, line["productId"], quantity, order_id, caller, stamp, movement_id)
        if kernel is not None:
            entries, inventory_position = kernel
            plan.extend(entries)
            fulfillment["inventoryMovementId"] = movement_id

    updated_order = dict(order)
    updated_lines = [dict(line_item) for line_item in lines]
    updated_lines[index] = {**line, "fulfilledQuantity": already + quantity}
    updated_order["lineItems"] = updated_lines
    updated_order["fulfillmentVersion"] = expected_version + 1
    updated_order["updatedAt"] = stamp
    result = {
        "order": from_dynamodb_json(updated_order),
        "fulfillment": from_dynamodb_json(fulfillment),
        "reversal": None,
        "inventoryPosition": inventory_position,
    }
    marker = _marker_put(caller, "fulfillOrderLine", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable(plan, marker)
    return result


def _reversal_inventory_entries(
    original: Dict[str, Any], order: Dict[str, Any], quantity: int, order_id: str, caller: str, stamp: str
) -> List[Dict[str, Any]]:
    """Inventory legs of a reversal: KERNEL_STOCK returns to the unit balance;
    SCOUT_CUSTODY returns to the Scout's custody (the draw ran at
    create/fulfill time; conservation runs both directions). EXTERNAL_COUNCIL
    and unit-less fulfillments have no inventory leg."""
    unit_campaign_id = original.get("unitCampaignId")
    if not isinstance(unit_campaign_id, str) or not unit_campaign_id:
        return []
    if original.get("source") == "KERNEL_STOCK":
        return [
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{BALANCE_PREFIX}{original['productId']}",
                    },
                    "UpdateExpression": "ADD kernelPhysicalQty :q SET version = version + :one, updatedAt = :ua",
                    "ConditionExpression": "attribute_exists(itemKey)",
                    "ExpressionAttributeValues": {":q": quantity, ":one": 1, ":ua": stamp},
                }
            }
        ]
    if original.get("source") == "SCOUT_CUSTODY":
        profile_id_for_custody = str(order["profileId"])
        return [
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{CUSTODY_PREFIX}{profile_id_for_custody}#{original['productId']}",
                    },
                    "UpdateExpression": "ADD withScoutQty :q SET version = version + :one, updatedAt = :ua",
                    "ConditionExpression": "attribute_exists(itemKey)",
                    "ExpressionAttributeValues": {":q": quantity, ":one": 1, ":ua": stamp},
                }
            },
            {
                "Put": {
                    "TableName": tables.inventory.table_name,
                    "Item": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{uuid.uuid4()}",
                        "productId": original["productId"],
                        "movementType": "REVERSAL_RETURN",
                        "withScoutDelta": quantity,
                        "orderId": order_id,
                        "actorAccountId": caller,
                        "occurredAt": stamp,
                    },
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            },
        ]
    return []


def reverse_individual_order_fulfillment(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    order_id = require_bounded_str(args, "orderId", 100)
    original_fulfillment_id = require_bounded_str(args, "fulfillmentId", 100)
    expected_version = _require_fulfillment_version(args)
    key = require_idempotency_key(args)

    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "reverseFulfillment", key), fingerprint)
    if replayed is not None:
        return replayed

    order, lines = _load_order_for_fulfillment(order_id, caller, expected_version)
    original = tables.order_fulfillments.get_item(
        Key={"orderId": order_id, "fulfillmentId": original_fulfillment_id}, ConsistentRead=True
    ).get("Item")
    if not isinstance(original, dict) or original.get("recordType") != "FULFILLMENT":
        raise AppError(ErrorCode.NOT_FOUND, "Fulfillment not found")
    if original.get("reversedAt"):
        raise AppError(ErrorCode.CONFLICT, "Fulfillment was already reversed", details={"reason": "ALREADY_REVERSED"})

    quantity = int(original["quantity"])
    line_item_id = str(original["lineItemId"])
    index = _find_line_index(lines, line_item_id)
    line = lines[index]
    already = int(line.get("fulfilledQuantity", 0))
    if already - quantity < 0:
        raise AppError(
            ErrorCode.CONFLICT,
            "Reversal would drive fulfilled quantity negative",
            details={"reason": "FULFILLMENT_INVALIDATED"},
        )

    now = _utcnow()
    stamp = _iso(now)
    reversal = {
        "fulfillmentId": f"REVERSAL#{original_fulfillment_id}",
        "orderId": order_id,
        "campaignId": order["campaignId"],
        "profileId": order["profileId"],
        "unitId": None,
        "unitCampaignId": original.get("unitCampaignId"),
        "lineItemId": line_item_id,
        "productId": original["productId"],
        "recordType": "REVERSAL",
        "quantity": quantity,
        "source": original["source"],
        "reversalOfFulfillmentId": original_fulfillment_id,
        "actorAccountId": caller,
        "createdAt": stamp,
    }
    plan: List[Dict[str, Any]] = [
        {
            "Put": {
                "TableName": tables.order_fulfillments.table_name,
                "Item": reversal,
                "ConditionExpression": "attribute_not_exists(fulfillmentId)",
            }
        },
        {
            "Update": {
                "TableName": tables.order_fulfillments.table_name,
                "Key": {"orderId": order_id, "fulfillmentId": original_fulfillment_id},
                "UpdateExpression": "SET reversedAt = :ra, reversedByAccountId = :rb",
                "ConditionExpression": "attribute_not_exists(reversedAt)",
                "ExpressionAttributeValues": {":ra": stamp, ":rb": caller},
            }
        },
        {
            "Update": {
                "TableName": tables.orders.table_name,
                "Key": {"campaignId": order["campaignId"], "orderId": order_id},
                "UpdateExpression": (
                    f"SET lineItems[{index}].fulfilledQuantity = :fq, fulfillmentVersion = :next, updatedAt = :ua"
                ),
                "ConditionExpression": "fulfillmentVersion = :expected",
                "ExpressionAttributeValues": {
                    ":fq": already - quantity,
                    ":next": expected_version + 1,
                    ":expected": expected_version,
                    ":ua": stamp,
                },
            }
        },
    ]
    plan.extend(_reversal_inventory_entries(original, order, quantity, order_id, caller, stamp))

    updated_order = dict(order)
    updated_lines = [dict(line) for line in lines]
    updated_lines[index] = {**line, "fulfilledQuantity": already - quantity}
    updated_order["lineItems"] = updated_lines
    updated_order["fulfillmentVersion"] = expected_version + 1
    updated_order["updatedAt"] = stamp
    result = {
        "order": from_dynamodb_json(updated_order),
        "fulfillment": None,
        "reversal": from_dynamodb_json(reversal),
        "inventoryPosition": None,
    }
    marker = _marker_put(caller, "reverseFulfillment", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable(plan, marker)
    return result


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "createOrder": custody_create_order,
    "fulfillIndividualOrderLine": fulfill_individual_order_line,
    "reverseIndividualOrderFulfillment": reverse_individual_order_fulfillment,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch an order operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported order operation: {field_name}")
    return operation(event, context)
