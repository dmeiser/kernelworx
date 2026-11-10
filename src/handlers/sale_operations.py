"""
Sale and We-Owe operations handlers (Show & Sell wave 5, spec API section 7).

Sale arithmetic (the gate-proven clean-room semantics, ADRs carried):

- IMMEDIATE handoff: `immediateQty` draws from the event allocation NOW
  (remainingQty down, soldQty up, one conditioned Update per product).
- WE-OWE consumes NO allocation: `weOweQty` mints a We-Owe obligation only
  (WEOWE# row) — zero allocation movement, zero balance movement. The
  obligation is demand, not stock.
- Prices are SNAPSHOTS from the Unit Campaign's catalog at sale time
  (integer cents); corrections re-snapshot.

Corrections are ABSOLUTE TARGETS (the clean-room doctrine): the corrected
line set replaces the old entirely; per product the allocation applies the
NET immediate delta (one conditioned Update, pre-read friendly guard);
per obligation the target is the new weOweQty (increases extend
originalQty, decreases add to cancelledQty — the corrected-obligation
re-finalization delta rule). Every correction/void writes a SALEREV# prior
revision snapshot: history is append-only, never rewritten. Voids return
all immediate stock and cancel uncovered obligation remainders.

Item layout (show_and_sells table, hash unitCampaignId):
- SALE#<saleId>: the sale (revision, status ACTIVE/VOIDED per 5.14).
- SALEREV#<saleId>#<revision>: immutable prior-revision snapshots.
- WEOWE#<weOweId>: obligations (weOweId-index lookup).
- WEOWEFULF#<weOweId>#<fulfillmentId>: fulfillment records.
- ALLOC# rows live in the INVENTORY table (wave-4 planner owns their
  target semantics; sales draw their remaining down).
"""

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
        require_strict_int,
        require_timestamp,
        require_version,
    )
    from utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        from_dynamodb_json,
        idem_expiry_epoch,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
    from utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_strict_int,
        require_timestamp,
        require_version,
    )
    from ..utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        from_dynamodb_json,
        idem_expiry_epoch,
        tables,
    )
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger
    from ..utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)

IDEM_HASH = "__IDEM__"
SALE_PREFIX = "SALE#"
SALE_REV_PREFIX = "SALEREV#"
WEOWE_PREFIX = "WEOWE#"
WEOWE_FULFILLMENT_PREFIX = "WEOWEFULFILLMENT#"
ALLOC_PREFIX = "ALLOC#"
BALANCE_PREFIX = "BALANCE#"
MOVEMENT_PREFIX = "MOVEMENT#"
EVENT_PREFIX = "EVENT#"
WEOWE_OPEN = "OPEN"
WEOWE_FULFILLED = "FULFILLED"
WEOWE_CLOSED = "CLOSED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return str(moment.isoformat()).replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _parse_ts(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise ValueError("naive timestamp")
    return parsed


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


def _marker_put(
    actor: str, scope: str, key: str, fingerprint: str, result: Optional[Dict[str, Any]], now: int
) -> Dict[str, Any]:
    return {
        "Put": {
            "TableName": tables.units.table_name,
            "Item": {
                "unitId": IDEM_HASH,
                "itemKey": _marker_item_key(actor, scope, key),
                "idemFingerprint": fingerprint,
                "idemCommittedAtEpoch": now,
                "expiresAtEpoch": idem_expiry_epoch(now),
                "idemResult": result,
            },
            "ConditionExpression": "attribute_not_exists(itemKey)",
        }
    }


def _check_marker(marker: Optional[Dict[str, Any]], fingerprint: str) -> Optional[Dict[str, Any]]:
    if marker is None:
        return None
    if marker.get("idemFingerprint") != fingerprint:
        raise AppError(ErrorCode.CONFLICT, "Idempotency key was already used with a different request")
    result = marker.get("idemResult")
    if not isinstance(result, dict):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Idempotency marker is missing its committed result")
    return cast(Dict[str, Any], from_dynamodb_json(result))


def _idempotency_begin(
    event: Dict[str, Any], args: Dict[str, Any], scope: str
) -> tuple[str, str, Optional[Dict[str, Any]]]:
    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    key = args.get("idempotencyKey")
    if key is None and isinstance(args.get("input"), dict):
        key = args["input"].get("idempotencyKey")
    replayed = _check_marker(_get_marker(caller, scope, str(key or "")), fingerprint)
    return caller, fingerprint, replayed


# ---------------------------------------------------------------------------
# Reads and projections
# ---------------------------------------------------------------------------


def _find_event(show_and_sell_id: str) -> Optional[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        IndexName="saleId-index",
        KeyConditionExpression="saleId = :sid",
        ExpressionAttributeValues={":sid": show_and_sell_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        if item.get("itemKey", "").startswith(EVENT_PREFIX):
            return dict(item)
    return None


def _load_event(show_and_sell_id: str) -> Dict[str, Any]:
    event = _find_event(show_and_sell_id)
    if event is None:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    return event


def _require_event_admin(event: Dict[str, Any], caller: str) -> None:
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": event["unitCampaignId"], "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)


def _split_alloc_key(item_key: str) -> tuple[str, str]:
    body = item_key[len(ALLOC_PREFIX) :]
    event_id, _, product_id = body.partition("#")
    return event_id, product_id


def _catalog_products(unit_campaign_id: str) -> Dict[str, Dict[str, Any]]:
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    catalog_id = uc.get("catalogId") if isinstance(uc, dict) else None
    if not isinstance(catalog_id, str):
        return {}
    catalog = tables.catalogs.get_item(Key={"catalogId": catalog_id}, ConsistentRead=True).get("Item")
    if not isinstance(catalog, dict):
        return {}
    products: Dict[str, Dict[str, Any]] = {}
    for product in catalog.get("products") or []:
        if isinstance(product, dict) and isinstance(product.get("productId"), str):
            products[product["productId"]] = product
    return products


def _product_cents(product: Dict[str, Any]) -> int:
    price = product.get("price")
    if not isinstance(price, (int, float, Decimal)) or isinstance(price, bool) or price < 0:
        raise AppError(ErrorCode.INVALID_INPUT, f"Product {product.get('productId')} has no valid price")
    return round(float(price) * 100)


def _read_alloc(unit_campaign_id: str, show_and_sell_id: str, product_id: str) -> Dict[str, Any]:
    item = tables.inventory.get_item(
        Key={
            "unitCampaignId": unit_campaign_id,
            "itemKey": f"{ALLOC_PREFIX}{show_and_sell_id}#{product_id}",
        },
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(item, dict):
        raise AppError(
            ErrorCode.CONFLICT,
            f"Product {product_id} has no allocation for this event",
            details={"reason": "INSUFFICIENT_STOCK"},
        )
    return dict(item)


def _sale_to_graphql(item: Dict[str, Any], prior_revisions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    revisions = (
        prior_revisions if prior_revisions is not None else _prior_revisions(item["unitCampaignId"], item["saleId"])
    )
    return {
        "saleId": item["saleId"],
        "showAndSellId": item["showAndSellId"],
        "unitId": item["unitId"],
        "unitCampaignId": item["unitCampaignId"],
        "saleAt": item["saleAt"],
        "enteredByAccountId": item["enteredByAccountId"],
        "buyerName": item.get("buyerName"),
        "buyerPhone": item.get("buyerPhone"),
        "buyerEmail": item.get("buyerEmail"),
        "lineItems": from_dynamodb_json(item.get("lineItems", [])),
        "totalCents": int(item.get("totalCents", 0)),
        "paymentMethodSnapshot": from_dynamodb_json(item["paymentMethodSnapshot"]),
        "revision": int(item.get("revision", 1)),
        "status": item.get("status", "ACTIVE"),
        "voidedByAccountId": item.get("voidedByAccountId"),
        "voidedAt": item.get("voidedAt"),
        "voidReason": item.get("voidReason"),
        "priorRevisions": revisions,
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }


def _prior_revisions(unit_campaign_id: str, sale_id: str) -> List[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{SALE_REV_PREFIX}{sale_id}#"},
    )
    revisions = []
    for row in response.get("Items", []):
        revisions.append(
            {
                "revision": int(row["itemKey"].rsplit("#", 1)[1]),
                "saleAt": row["saleAt"],
                "lineItems": from_dynamodb_json(row.get("lineItems", [])),
                "totalCents": int(row.get("totalCents", 0)),
                "reason": row.get("reason"),
                "createdAt": row.get("createdAt", ""),
            }
        )
    return sorted(revisions, key=lambda r: r["revision"])


def _load_sale(unit_campaign_id: str, sale_id: str) -> Dict[str, Any]:
    item = tables.show_and_sells.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{SALE_PREFIX}{sale_id}"}, ConsistentRead=True
    ).get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Sale not found")
    return dict(item)


def _load_obligation(we_owe_id: str) -> Dict[str, Any]:
    response = tables.show_and_sells.query(
        IndexName="weOweId-index",
        KeyConditionExpression="weOweId = :wid",
        ExpressionAttributeValues={":wid": we_owe_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        if item.get("itemKey", "").startswith(WEOWE_PREFIX):
            return dict(item)
    raise AppError(ErrorCode.NOT_FOUND, "We-Owe obligation not found")


def _obligation_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    fulfillments = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={
            ":uc": item["unitCampaignId"],
            ":prefix": f"{WEOWE_FULFILLMENT_PREFIX}{item['weOweId']}#",
        },
    ).get("Items", [])
    return {
        "weOweId": item["weOweId"],
        "unitCampaignId": item["unitCampaignId"],
        "showAndSellId": item["showAndSellId"],
        "saleId": item["saleId"],
        "lineItemId": item["lineItemId"],
        "buyerName": item.get("buyerName", ""),
        "productId": item["productId"],
        "productNameSnapshot": item.get("productNameSnapshot", ""),
        "originalQty": int(item.get("originalQty", 0)),
        "fulfilledQty": int(item.get("fulfilledQty", 0)),
        "cancelledQty": int(item.get("cancelledQty", 0)),
        "reservedQty": int(item.get("reservedQty", 0)),
        "remainingQty": int(item.get("remainingQty", 0)),
        "uncoveredQty": int(item.get("uncoveredQty", 0)),
        "valueCentsSnapshot": int(item.get("valueCentsSnapshot", 0)),
        "status": item.get("status", WEOWE_OPEN),
        "closeReason": item.get("closeReason"),
        "version": int(item.get("version", 0)),
        "createdAt": item.get("createdAt", ""),
        "closedAt": item.get("closedAt"),
        "fulfillments": [
            {
                "fulfillmentId": f["fulfillmentId"],
                "weOweId": f["weOweId"],
                "quantity": int(f.get("quantity", 0)),
                "source": f.get("source", ""),
                "inventoryMovementId": f.get("inventoryMovementId"),
                "actorAccountId": f.get("actorAccountId", ""),
                "createdAt": f.get("createdAt", ""),
            }
            for f in fulfillments
        ],
    }


# ---------------------------------------------------------------------------
# Sale validation helpers
# ---------------------------------------------------------------------------


def _validate_line_entries(raw_lines: Any) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "lineItems entries must be objects")
        product_id = require_bounded_str(entry, "productId", 100)
        immediate = require_strict_int(entry, "immediateQty")
        we_owe = require_strict_int(entry, "weOweQty")
        if immediate < 0 or we_owe < 0 or immediate + we_owe < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "each line needs a positive immediateQty and/or weOweQty")
        if product_id in seen:
            raise AppError(ErrorCode.INVALID_INPUT, "lineItems must not repeat a productId")
        seen.add(product_id)
        lines.append({"productId": product_id, "immediateQty": immediate, "weOweQty": we_owe})
    return lines


def _validate_sale_lines(
    args: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], Optional[str], Optional[str], Optional[str], int, str]:
    require_bounded_str(args, "showAndSellId", 100)
    expected_event_version = require_strict_int(args, "expectedEventVersion")
    if expected_event_version < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedEventVersion must not be negative")
    sale_at = require_timestamp(args, "saleAt")
    raw_lines = args.get("lineItems")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise AppError(ErrorCode.INVALID_INPUT, "lineItems must be a non-empty list")
    lines = _validate_line_entries(raw_lines)
    buyer_name = args.get("buyerName")
    if buyer_name is not None:
        buyer_name = require_bounded_str(args, "buyerName", 100)
    buyer_phone = args.get("buyerPhone")
    if buyer_phone is not None:
        buyer_phone = require_bounded_str(args, "buyerPhone", 50)
    buyer_email = args.get("buyerEmail")
    if buyer_email is not None:
        buyer_email = require_bounded_str(args, "buyerEmail", 200)
    return lines, buyer_name, buyer_phone, buyer_email, expected_event_version, sale_at


def _payment_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    raw = args.get("paymentMethod")
    if not isinstance(raw, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "paymentMethod is required")
    method_code = require_bounded_str(raw, "methodCode", 20)
    other_details = raw.get("otherDetails")
    if other_details is not None:
        other_details = require_bounded_str(raw, "otherDetails", 200)
    return {
        "methodCode": method_code,
        "displayName": method_code.title(),
        "otherDetails": other_details,
    }


def _event_bump_entry(event_item: Dict[str, Any], expected_version: int, caller: str, stamp: str) -> Dict[str, Any]:
    return {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": event_item["unitCampaignId"], "itemKey": event_item["itemKey"]},
            "UpdateExpression": "SET #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub",
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":next": expected_version + 1,
                ":expected": expected_version,
                ":ua": stamp,
                ":ub": caller,
            },
        }
    }


def _alloc_net_entry(
    unit_campaign_id: str,
    show_and_sell_id: str,
    product_id: str,
    net_remaining: int,
    net_sold: int,
    alloc_version: int,
    stamp: str,
) -> Dict[str, Any]:
    """One conditioned allocation Update applying the NET immediate delta
    (corrections-as-absolute-targets): positive net_remaining releases stock
    back, negative draws it. The condition guards the draw against races."""
    draw = max(0, -net_remaining)
    return {
        "Update": {
            "TableName": tables.inventory.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{ALLOC_PREFIX}{show_and_sell_id}#{product_id}"},
            "UpdateExpression": "ADD remainingQty :rm, soldQty :sd SET version = version + :one, updatedAt = :ua",
            "ConditionExpression": "attribute_exists(itemKey) AND version = :v AND remainingQty >= :draw",
            "ExpressionAttributeValues": {
                ":rm": net_remaining,
                ":sd": net_sold,
                ":one": 1,
                ":ua": stamp,
                ":v": alloc_version,
                ":draw": draw,
            },
        }
    }


def _movement_entry(
    unit_campaign_id: str,
    product_id: str,
    movement_type: str,
    assigned_delta: int,
    actor: str,
    stamp: str,
    show_and_sell_id: str,
    sale_id: Optional[str] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{uuid.uuid4()}",
        "productId": product_id,
        "movementType": movement_type,
        "assignedDelta": assigned_delta,
        "showAndSellId": show_and_sell_id,
        "actorAccountId": actor,
        "occurredAt": stamp,
    }
    if sale_id is not None:
        item["saleId"] = sale_id
    return {
        "Put": {
            "TableName": tables.inventory.table_name,
            "Item": item,
            "ConditionExpression": "attribute_not_exists(itemKey)",
        }
    }


def _revision_snapshot_entry(sale_item: Dict[str, Any], stamp: str, reason: Optional[str]) -> Dict[str, Any]:
    return {
        "Put": {
            "TableName": tables.show_and_sells.table_name,
            "Item": {
                "unitCampaignId": sale_item["unitCampaignId"],
                "itemKey": f"{SALE_REV_PREFIX}{sale_item['saleId']}#{sale_item['revision']}",
                "saleId": sale_item["saleId"],
                "revision": sale_item["revision"],
                "saleAt": sale_item["saleAt"],
                "lineItems": sale_item.get("lineItems", []),
                "totalCents": sale_item.get("totalCents", 0),
                "reason": reason,
                "createdAt": stamp,
            },
            "ConditionExpression": "attribute_not_exists(itemKey)",
        }
    }


def _enrich_create_lines(
    lines: List[Dict[str, Any]],
    products: Dict[str, Dict[str, Any]],
    buyer_name: Optional[str],
    unit_campaign_id: str,
    show_and_sell_id: str,
    sale_id: str,
    caller: str,
    stamp: str,
) -> tuple[List[Dict[str, Any]], int, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Snapshot prices from the catalog, mint obligation rows for we-owe
    demand (which consumes NO allocation), and plan the immediate-handoff
    allocation draws with their movements."""
    enriched_lines: List[Dict[str, Any]] = []
    obligations_out: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []
    total_cents = 0
    for line in lines:
        product = products.get(line["productId"])
        if product is None:
            raise AppError(
                ErrorCode.INVALID_INPUT, f"Product {line['productId']} not found in the Unit Campaign catalog"
            )
        unit_price_cents = _product_cents(product)
        subtotal = unit_price_cents * (line["immediateQty"] + line["weOweQty"])
        total_cents += subtotal
        enriched = {
            "lineItemId": str(uuid.uuid4()),
            "productId": line["productId"],
            "productNameSnapshot": str(product.get("productName", "")),
            "unitPriceCentsSnapshot": unit_price_cents,
            "immediateQty": line["immediateQty"],
            "weOweQty": line["weOweQty"],
            "subtotalCents": subtotal,
        }
        enriched_lines.append(enriched)
        if line["immediateQty"] > 0:
            alloc = _read_alloc(unit_campaign_id, show_and_sell_id, line["productId"])
            if int(alloc.get("remainingQty", 0)) < line["immediateQty"]:
                raise AppError(
                    ErrorCode.CONFLICT,
                    f"Not enough allocated {enriched['productNameSnapshot']} remaining for this sale",
                    details={"reason": "INSUFFICIENT_STOCK", "productId": line["productId"]},
                )
            plan.append(
                _alloc_net_entry(
                    unit_campaign_id,
                    show_and_sell_id,
                    line["productId"],
                    -line["immediateQty"],
                    line["immediateQty"],
                    int(alloc.get("version", 0)),
                    stamp,
                )
            )
            plan.append(
                _movement_entry(
                    unit_campaign_id,
                    line["productId"],
                    "SALE",
                    -line["immediateQty"],
                    caller,
                    stamp,
                    show_and_sell_id,
                    sale_id,
                )
            )
        if line["weOweQty"] > 0:
            # We-Owe consumes NO allocation (ADR): demand is recorded, stock
            # is untouched until fulfillment.
            we_owe_id = str(uuid.uuid4())
            obligation = {
                "unitCampaignId": unit_campaign_id,
                "itemKey": f"{WEOWE_PREFIX}{we_owe_id}",
                "weOweId": we_owe_id,
                "saleId": sale_id,
                "showAndSellId": show_and_sell_id,
                "lineItemId": enriched["lineItemId"],
                "buyerName": buyer_name or "",
                "productId": line["productId"],
                "productNameSnapshot": enriched["productNameSnapshot"],
                "originalQty": line["weOweQty"],
                "fulfilledQty": 0,
                "cancelledQty": 0,
                "reservedQty": 0,
                "remainingQty": line["weOweQty"],
                "uncoveredQty": line["weOweQty"],
                "valueCentsSnapshot": unit_price_cents * line["weOweQty"],
                "status": WEOWE_OPEN,
                "version": 1,
                "createdAt": stamp,
            }
            plan.append(
                {
                    "Put": {
                        "TableName": tables.show_and_sells.table_name,
                        "Item": obligation,
                        "ConditionExpression": "attribute_not_exists(itemKey)",
                    }
                }
            )
            obligations_out.append(_obligation_to_graphql(obligation))
    return enriched_lines, total_cents, obligations_out, plan


# ---------------------------------------------------------------------------
# createShowAndSellSale
# ---------------------------------------------------------------------------


def _create_sale(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    lines, buyer_name, buyer_phone, buyer_email, expected_event_version, sale_at = _validate_sale_lines(args)
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    payment = _payment_snapshot(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "createShowAndSellSale")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_event_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if current.get("status") == "CANCELLED":
        raise AppError(ErrorCode.CONFLICT, "A cancelled event cannot record sales", details={"reason": "ACTIVE_GUARD"})

    unit_campaign_id = current["unitCampaignId"]
    show_and_sell_id = current["showAndSellId"]
    products = _catalog_products(unit_campaign_id)
    now = _utcnow()
    stamp = _iso(now)
    sale_id = str(uuid.uuid4())
    plan: List[Dict[str, Any]] = []
    enriched_lines, total_cents, obligations_out, line_plan = _enrich_create_lines(
        lines, products, buyer_name, unit_campaign_id, show_and_sell_id, sale_id, caller, stamp
    )
    plan.extend(line_plan)

    sale_item: Dict[str, Any] = {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{SALE_PREFIX}{sale_id}",
        "saleId": sale_id,
        "showAndSellId": show_and_sell_id,
        "unitId": current["unitId"],
        "saleAt": sale_at,
        "enteredByAccountId": caller,
        "lineItems": enriched_lines,
        "totalCents": total_cents,
        "paymentMethodSnapshot": payment,
        "revision": 1,
        "status": "ACTIVE",
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    if buyer_name is not None:
        sale_item["buyerName"] = buyer_name
    if buyer_phone is not None:
        sale_item["buyerPhone"] = buyer_phone
    if buyer_email is not None:
        sale_item["buyerEmail"] = buyer_email
    plan.insert(
        0,
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": sale_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
    )
    plan.append(_event_bump_entry(current, expected_event_version, caller, stamp))

    result = {
        "sale": _sale_to_graphql(sale_item, prior_revisions=[]),
        "allocations": [],
        "inventoryPositions": [],
        "weOweObligations": obligations_out,
        "warnings": [],
    }
    marker = _marker_put(caller, "createShowAndSellSale", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT,
            "Stock or event state changed concurrently; retry the sale",
            details={"reason": "INSUFFICIENT_STOCK"},
        ) from None
    return result


# ---------------------------------------------------------------------------
# correctShowAndSellSale / voidShowAndSellSale (absolute targets)
# ---------------------------------------------------------------------------


def _resolve_correction_lines(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_lines = args.get("lineItems")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise AppError(ErrorCode.INVALID_INPUT, "lineItems must be a non-empty list")
    lines: List[Dict[str, Any]] = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "lineItems entries must be objects")
        line_item_id = entry.get("lineItemId")
        if line_item_id is not None and not isinstance(line_item_id, str):
            raise AppError(ErrorCode.INVALID_INPUT, "lineItemId must be a string")
        product_id = require_bounded_str(entry, "productId", 100)
        immediate = require_strict_int(entry, "immediateQty")
        we_owe = require_strict_int(entry, "weOweQty")
        if immediate < 0 or we_owe < 0 or immediate + we_owe < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "each line needs a positive immediateQty and/or weOweQty")
        lines.append(
            {"lineItemId": line_item_id, "productId": product_id, "immediateQty": immediate, "weOweQty": we_owe}
        )
    return lines


def _snapshot_corrected_line(
    line: Dict[str, Any], products: Dict[str, Dict[str, Any]], existing: Optional[Dict[str, Any]]
) -> tuple[Dict[str, Any], int]:
    product = products.get(line["productId"])
    if product is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Product {line['productId']} not found in the Unit Campaign catalog")
    if existing is not None and existing["productId"] != line["productId"]:
        raise AppError(ErrorCode.INVALID_INPUT, "lineItemId does not match the product")
    unit_price_cents = _product_cents(product)
    subtotal = unit_price_cents * (line["immediateQty"] + line["weOweQty"])
    return (
        {
            "lineItemId": line["lineItemId"] or str(uuid.uuid4()),
            "productId": line["productId"],
            "productNameSnapshot": str(product.get("productName", "")),
            "unitPriceCentsSnapshot": unit_price_cents,
            "immediateQty": line["immediateQty"],
            "weOweQty": line["weOweQty"],
            "subtotalCents": subtotal,
        },
        subtotal,
    )


def _plan_immediate_delta(
    enriched: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
    unit_campaign_id: str,
    show_and_sell_id: str,
    sale_id: str,
    caller: str,
    stamp: str,
    plan: List[Dict[str, Any]],
) -> None:
    old_immediate = int(existing.get("immediateQty", 0)) if existing else 0
    if enriched["immediateQty"] == old_immediate:
        return
    net_remaining = old_immediate - enriched["immediateQty"]
    alloc = _read_alloc(unit_campaign_id, show_and_sell_id, enriched["productId"])
    if -net_remaining > int(alloc.get("remainingQty", 0)):
        raise AppError(
            ErrorCode.CONFLICT,
            "The correction would draw more than the allocation has remaining",
            details={"reason": "INSUFFICIENT_STOCK", "productId": enriched["productId"]},
        )
    plan.append(
        _alloc_net_entry(
            unit_campaign_id,
            show_and_sell_id,
            enriched["productId"],
            net_remaining,
            -net_remaining,
            int(alloc.get("version", 0)),
            stamp,
        )
    )
    plan.append(
        _movement_entry(
            unit_campaign_id,
            enriched["productId"],
            "CORRECTION",
            net_remaining,
            caller,
            stamp,
            show_and_sell_id,
            sale_id,
        )
    )


def _plan_weowe_target(
    enriched: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
    sale: Dict[str, Any],
    unit_campaign_id: str,
    show_and_sell_id: str,
    stamp: str,
    plan: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    old_we_owe = int(existing.get("weOweQty", 0)) if existing else 0
    if existing is None:
        if enriched["weOweQty"] == 0:
            return None  # no we-owe demand on a new line: no obligation row
        obligation = _new_obligation_item(enriched, sale, unit_campaign_id, show_and_sell_id, stamp)
        plan.append(
            {
                "Put": {
                    "TableName": tables.show_and_sells.table_name,
                    "Item": obligation,
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            }
        )
        return _obligation_to_graphql(obligation)
    if enriched["weOweQty"] != old_we_owe:
        return _adjust_obligation(
            unit_campaign_id, sale["saleId"], enriched["lineItemId"], enriched["weOweQty"], stamp, plan
        )
    return _obligation_to_graphql(_find_obligation(unit_campaign_id, sale["saleId"], enriched["lineItemId"]))


def _new_obligation_item(
    enriched: Dict[str, Any], sale: Dict[str, Any], unit_campaign_id: str, show_and_sell_id: str, stamp: str
) -> Dict[str, Any]:
    we_owe_id = str(uuid.uuid4())
    return {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{WEOWE_PREFIX}{we_owe_id}",
        "weOweId": we_owe_id,
        "saleId": sale["saleId"],
        "showAndSellId": show_and_sell_id,
        "lineItemId": enriched["lineItemId"],
        "buyerName": sale.get("buyerName", ""),
        "productId": enriched["productId"],
        "productNameSnapshot": enriched["productNameSnapshot"],
        "originalQty": enriched["weOweQty"],
        "fulfilledQty": 0,
        "cancelledQty": 0,
        "reservedQty": 0,
        "remainingQty": enriched["weOweQty"],
        "uncoveredQty": enriched["weOweQty"],
        "valueCentsSnapshot": enriched["unitPriceCentsSnapshot"] * enriched["weOweQty"],
        "status": WEOWE_OPEN,
        "version": 1,
        "createdAt": stamp,
    }


def _release_dropped_line(
    old: Dict[str, Any],
    unit_campaign_id: str,
    show_and_sell_id: str,
    sale_id: str,
    caller: str,
    stamp: str,
    plan: List[Dict[str, Any]],
    obligations_out: List[Dict[str, Any]],
) -> None:
    if int(old.get("immediateQty", 0)) > 0:
        alloc = _read_alloc(unit_campaign_id, show_and_sell_id, old["productId"])
        plan.append(
            _alloc_net_entry(
                unit_campaign_id,
                show_and_sell_id,
                old["productId"],
                int(old["immediateQty"]),
                -int(old["immediateQty"]),
                int(alloc.get("version", 0)),
                stamp,
            )
        )
        plan.append(
            _movement_entry(
                unit_campaign_id,
                old["productId"],
                "CORRECTION",
                int(old["immediateQty"]),
                caller,
                stamp,
                show_and_sell_id,
                sale_id,
            )
        )
    obligations_out.append(_adjust_obligation(unit_campaign_id, sale_id, old["lineItemId"], 0, stamp, plan))


def _plan_corrected_lines(
    lines: List[Dict[str, Any]],
    old_lines: List[Dict[str, Any]],
    products: Dict[str, Dict[str, Any]],
    sale: Dict[str, Any],
    unit_campaign_id: str,
    show_and_sell_id: str,
    caller: str,
    stamp: str,
    plan: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], int, List[Dict[str, Any]], set[str]]:
    """Corrections-as-absolute-targets: the corrected line set replaces the
    old entirely. Products in BOTH get the NET immediate delta on their
    allocation (one conditioned Update) and their obligation retargeted;
    products only in the old set are fully released and cancelled."""
    old_by_id = {line["lineItemId"]: line for line in old_lines}
    new_lines: List[Dict[str, Any]] = []
    obligations_out: List[Dict[str, Any]] = []
    handled_old: set[str] = set()
    total_cents = 0
    for line in lines:
        existing = old_by_id.get(line["lineItemId"]) if line.get("lineItemId") else None
        enriched, subtotal = _snapshot_corrected_line(line, products, existing)
        total_cents += subtotal
        if existing is not None:
            handled_old.add(existing["lineItemId"])
        new_lines.append(enriched)
        _plan_immediate_delta(
            enriched, existing, unit_campaign_id, show_and_sell_id, sale["saleId"], caller, stamp, plan
        )
        we_owe_out = _plan_weowe_target(enriched, existing, sale, unit_campaign_id, show_and_sell_id, stamp, plan)
        if we_owe_out is not None:
            obligations_out.append(we_owe_out)
    for old in old_lines:
        if old["lineItemId"] not in handled_old:
            _release_dropped_line(
                old, unit_campaign_id, show_and_sell_id, sale["saleId"], caller, stamp, plan, obligations_out
            )

    return new_lines, total_cents, obligations_out, handled_old


def _correct_sale(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    sale_id = require_bounded_str(args, "saleId", 100)
    expected_revision = require_version(args, "expectedRevision")
    expected_event_version = require_strict_int(args, "expectedEventVersion")
    if expected_event_version < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedEventVersion must not be negative")
    sale_at = require_timestamp(args, "saleAt")
    reason = require_bounded_str(args, "reason", 200)
    lines = _resolve_correction_lines(args)
    payment = _payment_snapshot(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "correctShowAndSellSale")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_event_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    sale = _load_sale(current["unitCampaignId"], sale_id)
    if sale.get("showAndSellId") != show_and_sell_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sale not found")
    if sale.get("status") != "ACTIVE":
        raise AppError(ErrorCode.CONFLICT, "A voided sale cannot be corrected", details={"reason": "ACTIVE_GUARD"})
    if int(sale.get("revision", 1)) != expected_revision:
        raise AppError(ErrorCode.CONFLICT, "The sale changed concurrently", details={"reason": "VERSION_MISMATCH"})

    unit_campaign_id = current["unitCampaignId"]
    products = _catalog_products(unit_campaign_id)
    old_lines = from_dynamodb_json(sale.get("lineItems", []))

    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = [_revision_snapshot_entry(sale, stamp, reason)]
    new_lines, total_cents, obligations_out, handled_old = _plan_corrected_lines(
        lines, old_lines, products, sale, unit_campaign_id, show_and_sell_id, caller, stamp, plan
    )

    merged = {
        **sale,
        "saleAt": sale_at,
        "lineItems": new_lines,
        "totalCents": total_cents,
        "paymentMethodSnapshot": payment,
        "revision": expected_revision + 1,
        "updatedAt": stamp,
    }
    plan.append(_sale_update_entry(merged, expected_revision))
    plan.append(_event_bump_entry(current, expected_event_version, caller, stamp))
    result = {
        "sale": _sale_to_graphql(
            merged,
            prior_revisions=[
                *(_prior_revisions(unit_campaign_id, sale_id)),
                {
                    "revision": sale["revision"],
                    "saleAt": sale["saleAt"],
                    "lineItems": from_dynamodb_json(sale.get("lineItems", [])),
                    "totalCents": int(sale.get("totalCents", 0)),
                    "reason": reason,
                    "createdAt": stamp,
                },
            ],
        ),
        "allocations": [],
        "inventoryPositions": [],
        "weOweObligations": obligations_out,
        "warnings": [],
    }
    marker = _marker_put(caller, "correctShowAndSellSale", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable_or_stock(plan, marker)
    return result


def _adjust_obligation(
    unit_campaign_id: str, sale_id: str, line_item_id: str, target_we_owe: int, stamp: str, plan: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Corrected-obligation absolute target: increases extend originalQty,
    decreases add to cancelledQty (never below the fulfilled portion)."""
    obligation = _find_obligation(unit_campaign_id, sale_id, line_item_id)
    original = int(obligation.get("originalQty", 0))
    fulfilled = int(obligation.get("fulfilledQty", 0))
    cancelled = int(obligation.get("cancelledQty", 0))
    outstanding_target = max(target_we_owe - fulfilled, 0)
    new_original = fulfilled + outstanding_target if outstanding_target > (original - cancelled) else original
    new_cancelled = cancelled
    if outstanding_target < (original - cancelled):
        new_cancelled = original - outstanding_target
    remaining = max(new_original - fulfilled - new_cancelled, 0)
    reserved = min(int(obligation.get("reservedQty", 0)), remaining)
    status = WEOWE_OPEN if remaining > 0 else (WEOWE_FULFILLED if fulfilled > 0 else WEOWE_CLOSED)
    merged = {
        **obligation,
        "originalQty": new_original,
        "cancelledQty": new_cancelled,
        "remainingQty": remaining,
        "reservedQty": reserved,
        "uncoveredQty": max(remaining - reserved, 0),
        "status": status,
        "version": int(obligation.get("version", 0)) + 1,
        "updatedAt": stamp,
    }
    plan.append(
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": obligation["itemKey"]},
                "UpdateExpression": (
                    "SET #originalQty = :oq, #cancelledQty = :cq, #remainingQty = :rq, #reservedQty = :rs, "
                    "#uncoveredQty = :uq, #status = :st, #version = :next, #updatedAt = :ua"
                ),
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": {
                    "#originalQty": "originalQty",
                    "#cancelledQty": "cancelledQty",
                    "#remainingQty": "remainingQty",
                    "#reservedQty": "reservedQty",
                    "#uncoveredQty": "uncoveredQty",
                    "#status": "status",
                    "#version": "version",
                    "#updatedAt": "updatedAt",
                },
                "ExpressionAttributeValues": {
                    ":oq": new_original,
                    ":cq": new_cancelled,
                    ":rq": remaining,
                    ":rs": reserved,
                    ":uq": max(remaining - reserved, 0),
                    ":st": status,
                    ":next": int(obligation.get("version", 0)) + 1,
                    ":expected": int(obligation.get("version", 0)),
                    ":ua": stamp,
                },
            }
        }
    )
    return _obligation_to_graphql(merged)


def _find_obligation(unit_campaign_id: str, sale_id: str, line_item_id: str) -> Dict[str, Any]:
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": WEOWE_PREFIX},
    )
    for item in response.get("Items", []):
        if item.get("saleId") == sale_id and item.get("lineItemId") == line_item_id:
            return dict(item)
    raise AppError(ErrorCode.NOT_FOUND, "We-Owe obligation not found for the corrected line")


def _sale_update_entry(merged: Dict[str, Any], expected_revision: int) -> Dict[str, Any]:
    return {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": merged["unitCampaignId"], "itemKey": f"{SALE_PREFIX}{merged['saleId']}"},
            "UpdateExpression": (
                "SET #saleAt = :sa, #lineItems = :li, #totalCents = :tc, #paymentMethodSnapshot = :pm, "
                "#revision = :next, #updatedAt = :ua"
            ),
            "ConditionExpression": "#revision = :expected AND #status = :active",
            "ExpressionAttributeNames": {
                "#saleAt": "saleAt",
                "#lineItems": "lineItems",
                "#totalCents": "totalCents",
                "#paymentMethodSnapshot": "paymentMethodSnapshot",
                "#revision": "revision",
                "#updatedAt": "updatedAt",
                "#status": "status",
            },
            "ExpressionAttributeValues": {
                ":sa": merged["saleAt"],
                ":li": merged["lineItems"],
                ":tc": merged["totalCents"],
                ":pm": merged["paymentMethodSnapshot"],
                ":next": expected_revision + 1,
                ":expected": expected_revision,
                ":active": "ACTIVE",
                ":ua": merged["updatedAt"],
            },
        }
    }


def _execute_replayable_or_stock(plan: List[Dict[str, Any]], marker: Dict[str, Any]) -> None:
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT,
            "Stock or sale state changed concurrently; re-read and retry",
            details={"reason": "INSUFFICIENT_STOCK"},
        ) from None


def _void_sale(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    sale_id = require_bounded_str(args, "saleId", 100)
    expected_revision = require_version(args, "expectedRevision")
    expected_event_version = require_strict_int(args, "expectedEventVersion")
    if expected_event_version < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedEventVersion must not be negative")
    reason = require_bounded_str(args, "reason", 200)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "voidShowAndSellSale")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_event_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    sale = _load_sale(current["unitCampaignId"], sale_id)
    if sale.get("showAndSellId") != show_and_sell_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sale not found")
    if sale.get("status") != "ACTIVE":
        raise AppError(ErrorCode.CONFLICT, "The sale is already voided", details={"reason": "ALREADY_VOIDED"})
    if int(sale.get("revision", 1)) != expected_revision:
        raise AppError(ErrorCode.CONFLICT, "The sale changed concurrently", details={"reason": "VERSION_MISMATCH"})

    unit_campaign_id = current["unitCampaignId"]
    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = [_revision_snapshot_entry(sale, stamp, reason)]
    obligations_out: List[Dict[str, Any]] = []
    for old in from_dynamodb_json(sale.get("lineItems", [])):
        if int(old.get("immediateQty", 0)) > 0:
            alloc = _read_alloc(unit_campaign_id, show_and_sell_id, old["productId"])
            plan.append(
                _alloc_net_entry(
                    unit_campaign_id,
                    show_and_sell_id,
                    old["productId"],
                    int(old["immediateQty"]),
                    -int(old["immediateQty"]),
                    int(alloc.get("version", 0)),
                    stamp,
                )
            )
            plan.append(
                _movement_entry(
                    unit_campaign_id,
                    old["productId"],
                    "VOID_RETURN",
                    int(old["immediateQty"]),
                    caller,
                    stamp,
                    show_and_sell_id,
                    sale_id,
                )
            )
        obligations_out.append(_adjust_obligation(unit_campaign_id, sale_id, old["lineItemId"], 0, stamp, plan))
    merged = {
        **sale,
        "status": "VOIDED",
        "voidedByAccountId": caller,
        "voidedAt": stamp,
        "voidReason": reason,
        "revision": expected_revision + 1,
        "updatedAt": stamp,
    }
    plan.append(
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{SALE_PREFIX}{sale_id}"},
                "UpdateExpression": (
                    "SET #status = :voided, #voidedByAccountId = :vb, #voidedAt = :va, #voidReason = :vr, "
                    "#revision = :next, #updatedAt = :ua"
                ),
                "ConditionExpression": "#revision = :expected AND #status = :active",
                "ExpressionAttributeNames": {
                    "#status": "status",
                    "#voidedByAccountId": "voidedByAccountId",
                    "#voidedAt": "voidedAt",
                    "#voidReason": "voidReason",
                    "#revision": "revision",
                    "#updatedAt": "updatedAt",
                },
                "ExpressionAttributeValues": {
                    ":voided": "VOIDED",
                    ":vb": caller,
                    ":va": stamp,
                    ":vr": reason,
                    ":next": expected_revision + 1,
                    ":expected": expected_revision,
                    ":active": "ACTIVE",
                    ":ua": stamp,
                },
            }
        }
    )
    plan.append(_event_bump_entry(current, expected_event_version, caller, stamp))
    result = {
        "sale": _sale_to_graphql(merged),
        "allocations": [],
        "inventoryPositions": [],
        "weOweObligations": obligations_out,
        "warnings": [],
    }
    marker = _marker_put(caller, "voidShowAndSellSale", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable_or_stock(plan, marker)
    return result


# ---------------------------------------------------------------------------
# We-Owe operations
# ---------------------------------------------------------------------------


def _set_reservation(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    we_owe_id = require_bounded_str(args, "weOweId", 100)
    target_reserved = require_strict_int(args, "targetReservedQty")
    if target_reserved < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "targetReservedQty must not be negative")
    expected_version = require_version(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "setWeOweReservation")
    if replayed is not None:
        return replayed
    obligation = _load_obligation(we_owe_id)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": obligation["unitCampaignId"], "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    if int(obligation.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "The obligation changed concurrently", details={"reason": "VERSION_MISMATCH"}
        )
    remaining = int(obligation.get("remainingQty", 0))
    if target_reserved > remaining:
        raise AppError(
            ErrorCode.CONFLICT,
            "The reservation target exceeds the obligation's remaining quantity",
            details={"reason": "RESERVATION_EXCEEDS_REMAINING"},
        )

    now = _utcnow()
    stamp = _iso(now)
    merged = {
        **obligation,
        "reservedQty": target_reserved,
        "uncoveredQty": remaining - target_reserved,
        "version": expected_version + 1,
        "updatedAt": stamp,
    }
    update = {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": obligation["unitCampaignId"], "itemKey": obligation["itemKey"]},
            "UpdateExpression": "SET #reservedQty = :rs, #uncoveredQty = :uq, #version = :next, #updatedAt = :ua",
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#reservedQty": "reservedQty",
                "#uncoveredQty": "uncoveredQty",
                "#version": "version",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":rs": target_reserved,
                ":uq": remaining - target_reserved,
                ":next": expected_version + 1,
                ":expected": expected_version,
                ":ua": stamp,
            },
        }
    }
    result = {
        "obligation": _obligation_to_graphql(merged),
        "inventoryPosition": _position_projection(obligation["unitCampaignId"], obligation["productId"]),
    }
    marker = _marker_put(caller, "setWeOweReservation", key, fingerprint, result, _epoch(now))
    _execute_replayable_or_stock([update, marker], marker)
    return result


def _kernel_fulfill_entries(
    unit_campaign_id: str,
    obligation: Dict[str, Any],
    we_owe_id: str,
    quantity: int,
    source: str,
    caller: str,
    stamp: str,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """KERNEL_STOCK fulfillments draw the unit balance and record the
    movement; other sources have no inventory leg."""
    if source != "KERNEL_STOCK":
        return [], None
    balance = (
        tables.inventory.get_item(
            Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{obligation['productId']}"},
            ConsistentRead=True,
        ).get("Item")
        or {}
    )
    if int(balance.get("kernelPhysicalQty", 0)) < quantity:
        raise AppError(
            ErrorCode.CONFLICT, "Not enough kernel stock to fulfill", details={"reason": "INSUFFICIENT_STOCK"}
        )
    movement_id = str(uuid.uuid4())
    entries: List[Dict[str, Any]] = [
        {
            "Update": {
                "TableName": tables.inventory.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{obligation['productId']}"},
                "UpdateExpression": "ADD kernelPhysicalQty :neg SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "attribute_exists(itemKey) AND kernelPhysicalQty >= :min AND version = :bv",
                "ExpressionAttributeValues": {
                    ":neg": -quantity,
                    ":one": 1,
                    ":ua": stamp,
                    ":min": quantity,
                    ":bv": int(balance.get("version", 0)),
                },
            }
        },
        {
            "Put": {
                "TableName": tables.inventory.table_name,
                "Item": {
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{movement_id}",
                    "productId": obligation["productId"],
                    "movementType": "WEOWE_FULFILL",
                    "kernelPhysicalDelta": -quantity,
                    "weOweId": we_owe_id,
                    "actorAccountId": caller,
                    "occurredAt": stamp,
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
    ]
    return entries, movement_id


def _fulfilled_obligation_merged(
    obligation: Dict[str, Any], quantity: int, remaining: int, expected_version: int, stamp: str
) -> Dict[str, Any]:
    new_fulfilled = int(obligation.get("fulfilledQty", 0)) + quantity
    new_remaining = remaining - quantity
    new_status = WEOWE_FULFILLED if new_remaining == 0 else WEOWE_OPEN
    return {
        **obligation,
        "fulfilledQty": new_fulfilled,
        "remainingQty": new_remaining,
        "uncoveredQty": max(new_remaining - int(obligation.get("reservedQty", 0)), 0),
        "status": new_status,
        "closedAt": stamp if new_remaining == 0 else obligation.get("closedAt"),
        "version": expected_version + 1,
        "updatedAt": stamp,
    }


def _fulfill_we_owe(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    we_owe_id = require_bounded_str(args, "weOweId", 100)
    quantity = require_strict_int(args, "quantity")
    if quantity < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")
    source = require_bounded_str(args, "source", 50)
    expected_version = require_version(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "fulfillWeOwe")
    if replayed is not None:
        return replayed
    obligation = _load_obligation(we_owe_id)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": obligation["unitCampaignId"], "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    if int(obligation.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "The obligation changed concurrently", details={"reason": "VERSION_MISMATCH"}
        )
    remaining = int(obligation.get("remainingQty", 0))
    if quantity > remaining:
        raise AppError(
            ErrorCode.CONFLICT,
            "The fulfillment exceeds the obligation's remaining quantity",
            details={"reason": "FULFILLMENT_EXCEEDS_REMAINING"},
        )

    unit_campaign_id = obligation["unitCampaignId"]
    now = _utcnow()
    stamp = _iso(now)
    plan, movement_id = _kernel_fulfill_entries(
        unit_campaign_id, obligation, we_owe_id, quantity, source, caller, stamp
    )

    merged = _fulfilled_obligation_merged(obligation, quantity, remaining, expected_version, stamp)
    plan.append(
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": obligation["itemKey"]},
                "UpdateExpression": (
                    "SET #fulfilledQty = :fq, #remainingQty = :rq, #uncoveredQty = :uq, #status = :st, "
                    "#version = :next, #updatedAt = :ua" + (", #closedAt = :ca" if merged["remainingQty"] == 0 else "")
                ),
                "ConditionExpression": "#version = :expected AND #status = :open",
                "ExpressionAttributeNames": {
                    "#fulfilledQty": "fulfilledQty",
                    "#remainingQty": "remainingQty",
                    "#uncoveredQty": "uncoveredQty",
                    "#status": "status",
                    "#version": "version",
                    "#updatedAt": "updatedAt",
                    **({"#closedAt": "closedAt"} if merged["remainingQty"] == 0 else {}),
                },
                "ExpressionAttributeValues": {
                    ":fq": merged["fulfilledQty"],
                    ":rq": merged["remainingQty"],
                    ":uq": merged["uncoveredQty"],
                    ":st": merged["status"],
                    ":next": expected_version + 1,
                    ":expected": expected_version,
                    ":open": WEOWE_OPEN,
                    ":ua": stamp,
                    **({":ca": stamp} if merged["remainingQty"] == 0 else {}),
                },
            }
        }
    )
    fulfillment = {
        "fulfillmentId": str(uuid.uuid4()),
        "weOweId": we_owe_id,
        "quantity": quantity,
        "source": source,
        "inventoryMovementId": movement_id,
        "actorAccountId": caller,
        "createdAt": stamp,
    }
    plan.append(
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": {
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"{WEOWE_FULFILLMENT_PREFIX}{we_owe_id}#{fulfillment['fulfillmentId']}",
                    **fulfillment,
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        }
    )
    result = {
        "obligation": _obligation_to_graphql(merged),
        "fulfillment": fulfillment,
        "inventoryPosition": (
            _position_projection(unit_campaign_id, obligation["productId"], kernel_delta=-quantity)
            if source == "KERNEL_STOCK"
            else None
        ),
    }
    marker = _marker_put(caller, "fulfillWeOwe", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable_or_stock(plan, marker)
    return result


def _position_projection(unit_campaign_id: str, product_id: str, kernel_delta: int = 0) -> Dict[str, Any]:
    from src.utils.inventory_derived import derive_position

    balance = (
        tables.inventory.get_item(
            Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"}, ConsistentRead=True
        ).get("Item")
        or {}
    )
    return derive_position(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        kernel_physical_qty=int(balance.get("kernelPhysicalQty", 0)) + kernel_delta,
        sold_in_possession_qty=int(balance.get("soldInPossessionQty", 0)),
        council_on_order_qty=int(balance.get("councilOnOrderQty", 0)),
        balance_version=int(balance.get("version", 0)) + (1 if kernel_delta else 0),
        allocations=[],
        custody_rows=[],
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _list_sales(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    status = args.get("status")
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": current["unitCampaignId"], ":prefix": SALE_PREFIX},
    )
    items = [
        _sale_to_graphql(item)
        for item in response.get("Items", [])
        if item.get("showAndSellId") == show_and_sell_id and (status is None or item.get("status") == status)
    ]
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _get_obligation(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    we_owe_id = require_bounded_str(args, "weOweId", 100)
    caller = _require_caller(event)
    obligation = _load_obligation(we_owe_id)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": obligation["unitCampaignId"], "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    return _obligation_to_graphql(obligation)


def _obligation_matches(
    item: Dict[str, Any],
    status: Optional[str],
    show_and_sell_id: Optional[str],
    product_id: Optional[str],
    buyer_name: Optional[str],
) -> bool:
    if status is not None and item.get("status") != status:
        return False
    if show_and_sell_id is not None and item.get("showAndSellId") != show_and_sell_id:
        return False
    if product_id is not None and item.get("productId") != product_id:
        return False
    if buyer_name is not None and buyer_name.lower() not in str(item.get("buyerName", "")).lower():
        return False
    return True


def _list_obligations(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    status = args.get("status")
    show_and_sell_id = args.get("showAndSellId")
    product_id = args.get("productId")
    buyer_name = args.get("buyerName")
    caller = _require_caller(event)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": WEOWE_PREFIX},
    )
    items = [
        _obligation_to_graphql(item)
        for item in response.get("Items", [])
        if _obligation_matches(item, status, show_and_sell_id, product_id, buyer_name)
    ]
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "createShowAndSellSale": _create_sale,
    "correctShowAndSellSale": _correct_sale,
    "voidShowAndSellSale": _void_sale,
    "setWeOweReservation": _set_reservation,
    "fulfillWeOwe": _fulfill_we_owe,
    "showAndSellSales": _list_sales,
    "weOweObligation": _get_obligation,
    "weOweObligations": _list_obligations,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch a sale or We-Owe operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported sale operation: {field_name}")
    return operation(event, context)
