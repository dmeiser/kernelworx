"""
Event operations handlers: Show & Sell events, slots, signups, work
confirmation, and the allocation planner (Show & Sell wave 4, checklist
3.1-3.4; spec API section 6 / DATA_MODEL section 9).

Event lifecycle (spec 9.1): status is DERIVED from the interval and the
clock — SCHEDULED before startAt, ACTIVE within [startAt, endAt), ENDED at
or after endAt — except CANCELLED/FINALIZED/REOPENED which are stored.
Times are immutable once set (the update input has no time fields; the
record of that contract is docs/investigations/show-sell-idempotency-
convention.md's sibling notes and the SDL shape itself).

Item layout (show_and_sells table, hash unitCampaignId):
- EVENT#<showAndSellId>: the event metadata + stored status.
- SLOT#<showAndSellId>#<slotId>: work slots (arbitrary durations, 20-cap).
- SIGNUP#<slotId>#<profileId>: roster signups (sequence contract).
- IDEM markers (hash __IDEM__ in the units table, as everywhere).
Allocations live in the INVENTORY table as ALLOC#<showAndSellId>#<productId>
rows (the wave-3 position reader already aggregates them).

Allocation semantics are TARGETS, never deltas, with the interval evaluator
in utils.allocation (ADR 0003 carrier: sequential events may over-assign
with a warning; overlapping events hard-block when the concurrent peak
exceeds sellable stock; sold-stock protection rejects targets below sold).
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.allocation import (
        OpenAllocationView,
        evaluate_assignment,
        plan_targets,
        validate_plan_line,
    )
    from utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_strict_int,
        require_timestamp,
        require_version,
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
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
    from utils.pagination import decode_cursor, encode_cursor, validate_page_limit
    from utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.allocation import (
        OpenAllocationView,
        evaluate_assignment,
        plan_targets,
        validate_plan_line,
    )
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_strict_int,
        require_timestamp,
        require_version,
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
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger
    from ..utils.pagination import decode_cursor, encode_cursor, validate_page_limit
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
EVENT_PREFIX = "EVENT#"
SLOT_PREFIX = "SLOT#"
SIGNUP_PREFIX = "SIGNUP#"
MOVEMENT_PREFIX = "MOVEMENT#"
ALLOC_PREFIX = "ALLOC#"
MAX_ACTIVE_SLOTS = 20  # spec 3.3
SIGNUP_ACTIVE = "ACTIVE"
SIGNUP_CANCELLED = "CANCELLED"
STORED_CANCELLED = "CANCELLED"
SPLIT_METHODS = ("EQUAL", "TIME_WORKED")


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


def _event_bump_entry(event_item: Dict[str, Any], expected_version: int, caller: str, stamp: str) -> Dict[str, Any]:
    """The optimistic-concurrency event version bump every event mutation
    shares (slot edits, allocation, work confirmation, cancel)."""
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


def _marker_scope_key(args: Dict[str, Any]) -> str:
    """The idempotency key lives at args.idempotencyKey for flat-argument
    mutations and args.input.idempotencyKey for input-wrapped ones; treating
    both as one namespace would replay unrelated requests against each
    other (found by the wave-4 slot race probe)."""
    key = args.get("idempotencyKey")
    if key is None and isinstance(args.get("input"), dict):
        key = args["input"].get("idempotencyKey")
    return str(key or "")


def _idempotency_begin(
    event: Dict[str, Any], args: Dict[str, Any], scope: str
) -> tuple[str, str, Optional[Dict[str, Any]]]:
    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, scope, _marker_scope_key(args)), fingerprint)
    return caller, fingerprint, replayed


def _execute_replayable(plan: List[Dict[str, Any]], marker: Dict[str, Any]) -> None:
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _derive_status(item: Dict[str, Any], now: datetime) -> str:
    stored = str(item.get("status", "SCHEDULED"))
    if stored in (STORED_CANCELLED, "FINALIZED", "REOPENED"):
        return stored
    start = _parse_ts(item["startAt"])
    end = _parse_ts(item["endAt"])
    if now < start:
        return "SCHEDULED"
    if now < end:
        return "ACTIVE"
    return "ENDED"


def _find_event(show_and_sell_id: str) -> Optional[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        IndexName="saleId-index",
        KeyConditionExpression="saleId = :sid",
        ExpressionAttributeValues={":sid": show_and_sell_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        if item.get("itemKey") == f"{EVENT_PREFIX}{show_and_sell_id}":
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


def _slots_for(show_and_sell_id: str, unit_campaign_id: str) -> List[Dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    response = tables.show_and_sells.query(
        KeyConditionExpression=Key("unitCampaignId").eq(unit_campaign_id)
        & Key("itemKey").begins_with(f"{SLOT_PREFIX}{show_and_sell_id}#"),
    )
    return [
        _slot_to_graphql(item)
        for item in response.get("Items", [])
        if item.get("itemKey", "").startswith(f"{SLOT_PREFIX}{show_and_sell_id}#")
    ]


def _slot_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "showAndSellId": item["showAndSellId"],
        "slotId": item["slotId"],
        "label": item.get("label"),
        "startAt": item["startAt"],
        "endAt": item["endAt"],
        "capacity": int(item.get("capacity", 0)),
        "activeSignupCount": int(item.get("activeSignupCount", 0)),
        "version": int(item.get("version", 0)),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }


def _event_to_graphql(item: Dict[str, Any], now: datetime, include_slots: bool = True) -> Dict[str, Any]:
    result = {
        "showAndSellId": item["showAndSellId"],
        "unitId": item["unitId"],
        "unitCampaignId": item["unitCampaignId"],
        "locationName": item["locationName"],
        "address": item.get("address"),
        "startAt": item["startAt"],
        "endAt": item["endAt"],
        "status": _derive_status(item, now),
        "splitMethod": item["splitMethod"],
        "weOweEnabled": bool(item.get("weOweEnabled", False)),
        "productIds": sorted(_event_product_ids(item["unitCampaignId"], item["showAndSellId"])),
        "version": int(item.get("version", 0)),
        "createdByAccountId": item["createdByAccountId"],
        "createdAt": item["createdAt"],
        "updatedByAccountId": item.get("updatedByAccountId", item["createdByAccountId"]),
        "updatedAt": item["updatedAt"],
        "cancelledByAccountId": item.get("cancelledByAccountId"),
        "cancelledAt": item.get("cancelledAt"),
        "cancellationReason": item.get("cancellationReason"),
    }
    if include_slots:
        slots = _slots_for(item["showAndSellId"], item["unitCampaignId"])
        result["slots"] = slots
        result["slotCount"] = len(slots)
    return result


def _event_product_ids(unit_campaign_id: str, show_and_sell_id: str) -> List[str]:
    response = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{ALLOC_PREFIX}{show_and_sell_id}#"},
    )
    return [
        i["itemKey"].rsplit("#", 1)[1]
        for i in response.get("Items", [])
        if i.get("itemKey", "").startswith(ALLOC_PREFIX)
    ]


# ---------------------------------------------------------------------------
# Mutations: event lifecycle
# ---------------------------------------------------------------------------


def _resolve_event_create_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate createShowAndSell input (deterministic, pre-marker)."""
    resolved: Dict[str, Any] = {}
    resolved["unitCampaignId"] = require_bounded_str(args, "unitCampaignId", 100)
    resolved["locationName"] = require_bounded_str(args, "locationName", 100)
    start_at = require_timestamp(args, "startAt")
    end_at = require_timestamp(args, "endAt")
    if _parse_ts(end_at) <= _parse_ts(start_at):
        raise AppError(ErrorCode.INVALID_INPUT, "endAt must be after startAt")
    resolved["startAt"] = start_at
    resolved["endAt"] = end_at
    split_method = args.get("splitMethod") or "EQUAL"
    if args.get("splitMethod") is not None:
        split_method = require_str_enum(args, "splitMethod", SPLIT_METHODS)
    resolved["splitMethod"] = split_method
    we_owe_enabled = args.get("weOweEnabled")
    if we_owe_enabled is not None and not isinstance(we_owe_enabled, bool):
        raise AppError(ErrorCode.INVALID_INPUT, "weOweEnabled must be a boolean")
    resolved["weOweEnabled"] = we_owe_enabled
    resolved["idempotencyKey"] = require_idempotency_key(args)
    address = args.get("address")
    if address is not None:
        address = require_bounded_str(args, "address", 200)
    resolved["address"] = address
    return resolved


def _create_show_and_sell(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    args = event.get("arguments", {}).get("input") or {}
    resolved = _resolve_event_create_input(args)
    unit_campaign_id = resolved["unitCampaignId"]
    location_name = resolved["locationName"]
    start_at = resolved["startAt"]
    end_at = resolved["endAt"]
    split_method = resolved["splitMethod"]
    we_owe_enabled = resolved["weOweEnabled"]
    key = resolved["idempotencyKey"]

    caller, fingerprint, replayed = _idempotency_begin(event, args, "createShowAndSell")
    if replayed is not None:
        return replayed
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)

    now = _utcnow()
    stamp = _iso(now)
    show_and_sell_id = str(uuid.uuid4())
    item = {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{EVENT_PREFIX}{show_and_sell_id}",
        "showAndSellId": show_and_sell_id,
        "saleId": show_and_sell_id,  # saleId-index lookup carrier
        "unitId": uc["unitId"],
        "locationName": location_name,
        "startAt": start_at,
        "endAt": end_at,
        "status": "SCHEDULED",
        "splitMethod": split_method,
        "weOweEnabled": bool(we_owe_enabled or False),
        "version": 1,
        "createdByAccountId": caller,
        "createdAt": stamp,
        "updatedByAccountId": caller,
        "updatedAt": stamp,
    }
    if args.get("address"):
        item["address"] = require_bounded_str(args, "address", 200)
    marker = _marker_put(caller, "createShowAndSell", key, fingerprint, None, _epoch(now))
    plan = [
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        marker,
    ]
    _execute_replayable(plan, marker)
    result = _event_to_graphql(item, now)
    plan[1]["Put"]["Item"]["idemResult"] = result
    tables.units.put_item(Item=plan[1]["Put"]["Item"])
    return result


def _resolve_event_update_fields(args: Dict[str, Any]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    resolved["showAndSellId"] = require_bounded_str(args, "showAndSellId", 100)
    resolved["expectedVersion"] = require_version(args)
    resolved["idempotencyKey"] = require_idempotency_key(args)
    location_name = args.get("locationName")
    if location_name is not None:
        location_name = require_bounded_str(args, "locationName", 100)
    resolved["locationName"] = location_name
    address = args.get("address")
    if address is not None:
        address = require_bounded_str(args, "address", 200)
    resolved["address"] = address
    split_method = args.get("splitMethod")
    if split_method is not None:
        split_method = require_str_enum(args, "splitMethod", SPLIT_METHODS)
    resolved["splitMethod"] = split_method
    we_owe_enabled = args.get("weOweEnabled")
    if we_owe_enabled is not None and not isinstance(we_owe_enabled, bool):
        raise AppError(ErrorCode.INVALID_INPUT, "weOweEnabled must be a boolean")
    resolved["weOweEnabled"] = we_owe_enabled
    return resolved


def _update_show_and_sell(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    resolved = _resolve_event_update_fields(args)
    show_and_sell_id = resolved["showAndSellId"]
    expected_version = resolved["expectedVersion"]
    key = resolved["idempotencyKey"]
    location_name = resolved["locationName"]
    address = resolved["address"]
    split_method = resolved["splitMethod"]
    we_owe_enabled = resolved["weOweEnabled"]

    caller, fingerprint, replayed = _idempotency_begin(event, args, "updateShowAndSell")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if current.get("status") == STORED_CANCELLED:
        raise AppError(ErrorCode.CONFLICT, "A cancelled event cannot be updated", details={"reason": "ACTIVE_GUARD"})

    now = _utcnow()
    stamp = _iso(now)
    merged = {**current}
    if location_name is not None:
        merged["locationName"] = location_name
    if address is not None:
        merged["address"] = address
    if split_method is not None:
        merged["splitMethod"] = split_method
    if we_owe_enabled is not None:
        merged["weOweEnabled"] = we_owe_enabled
    merged["version"] = expected_version + 1
    merged["updatedAt"] = stamp
    merged["updatedByAccountId"] = caller
    update = {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": merged["unitCampaignId"], "itemKey": merged["itemKey"]},
            "UpdateExpression": (
                "SET #locationName = :ln, #address = :ad, #splitMethod = :sm, #weOweEnabled = :we, "
                "#version = :next, #updatedAt = :ua, #updatedByAccountId = :ub"
            ),
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#locationName": "locationName",
                "#address": "address",
                "#splitMethod": "splitMethod",
                "#weOweEnabled": "weOweEnabled",
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":ln": merged["locationName"],
                ":ad": merged.get("address"),
                ":sm": merged["splitMethod"],
                ":we": bool(merged.get("weOweEnabled", False)),
                ":next": expected_version + 1,
                ":expected": expected_version,
                ":ua": stamp,
                ":ub": caller,
            },
        }
    }
    result = _event_to_graphql(merged, now)
    marker = _marker_put(caller, "updateShowAndSell", key, fingerprint, result, _epoch(now))
    _execute_replayable([update, marker], marker)
    return result


def _allocation_release_entries(event_item: Dict[str, Any], stamp: str) -> List[Dict[str, Any]]:
    """Every allocation CANCELLED with releasedQty += remainingQty (so the
    section 7 formulas and the auto-reduce evaluator stop reserving stock),
    plus a release movement per non-empty remainder."""
    unit_campaign_id = event_item["unitCampaignId"]
    show_and_sell_id = event_item["showAndSellId"]
    entries: List[Dict[str, Any]] = []
    # Allocations -> CANCELLED with releasedQty += remainingQty.
    allocations = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{ALLOC_PREFIX}{show_and_sell_id}#"},
    ).get("Items", [])
    for row in allocations:
        product_id = _split_alloc_key(row["itemKey"])[1]
        remaining = int(row.get("remainingQty", 0))
        entries.append(
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": row["itemKey"]},
                    "UpdateExpression": "SET #status = :cancelled, #releasedQty = releasedQty + :rel, #remainingQty = :zero, #updatedAt = :ua",
                    "ConditionExpression": "#status = :open",
                    "ExpressionAttributeNames": {
                        "#status": "status",
                        "#releasedQty": "releasedQty",
                        "#remainingQty": "remainingQty",
                        "#updatedAt": "updatedAt",
                    },
                    "ExpressionAttributeValues": {
                        ":cancelled": "CANCELLED",
                        ":open": "OPEN",
                        ":rel": remaining,
                        ":zero": 0,
                        ":ua": stamp,
                    },
                }
            }
        )
        if remaining > 0:
            entries.append(
                {
                    "Put": {
                        "TableName": tables.inventory.table_name,
                        "Item": {
                            "unitCampaignId": unit_campaign_id,
                            "itemKey": f"{MOVEMENT_PREFIX}{stamp}#{uuid.uuid4()}",
                            "productId": product_id,
                            "movementType": "RELEASE",
                            "assignedDelta": -remaining,
                            "showAndSellId": show_and_sell_id,
                            "occurredAt": stamp,
                        },
                        "ConditionExpression": "attribute_not_exists(itemKey)",
                    }
                }
            )

    return entries


def _slot_zero_entries(slots: List[Dict[str, Any]], unit_campaign_id: str, stamp: str) -> List[Dict[str, Any]]:
    return [
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": slot["itemKey"]},
                "UpdateExpression": "SET activeSignupCount = :zero, updatedAt = :ua",
                "ConditionExpression": "attribute_exists(itemKey)",
                "ExpressionAttributeValues": {":zero": 0, ":ua": stamp},
            }
        }
        for slot in slots
        if int(slot.get("activeSignupCount", 0)) != 0
    ]


def _window_release_buckets(signup: Dict[str, Any], slot: Dict[str, Any]) -> List[str]:
    """The signup's window buckets MINUS any bucket another ACTIVE signup of
    the same profile still claims (those stay)."""
    buckets = _window_buckets(slot["startAt"], slot["endAt"])
    other_buckets: set[str] = set()
    for interval in _profile_active_intervals(signup["profileId"], exclude_signup_key=signup["itemKey"]):
        other_buckets.update(_window_buckets(interval["startAt"], interval["endAt"]))
    return [b for b in buckets if b not in other_buckets]


def _signup_cancellation_entries(
    event_item: Dict[str, Any], slots: List[Dict[str, Any]], stamp: str
) -> List[Dict[str, Any]]:
    """Signups cancelled, slot counters zeroed, window buckets released
    (buckets still claimed by another ACTIVE signup of the same profile are
    retained)."""
    from boto3.dynamodb.conditions import Key

    unit_campaign_id = event_item["unitCampaignId"]
    show_and_sell_id = event_item["showAndSellId"]
    entries = _slot_zero_entries(slots, unit_campaign_id, stamp)
    signups = tables.show_and_sells.query(
        KeyConditionExpression=Key("unitCampaignId").eq(unit_campaign_id) & Key("itemKey").begins_with(SIGNUP_PREFIX),
    ).get("Items", [])
    for signup in signups:
        if signup.get("showAndSellId") != show_and_sell_id or signup.get("status") != SIGNUP_ACTIVE:
            continue
        profile_id = signup["profileId"]
        entries.append(
            {
                "Update": {
                    "TableName": tables.show_and_sells.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": signup["itemKey"]},
                    "UpdateExpression": "SET #status = :cancelled, #updatedAt = :ua",
                    "ConditionExpression": "#status = :active",
                    "ExpressionAttributeNames": {"#status": "status", "#updatedAt": "updatedAt"},
                    "ExpressionAttributeValues": {
                        ":cancelled": SIGNUP_CANCELLED,
                        ":active": SIGNUP_ACTIVE,
                        ":ua": stamp,
                    },
                }
            }
        )
        slot = next((sl for sl in slots if sl["slotId"] == signup["slotId"]), None)
        if slot is None:
            continue
        entries.extend(_window_delete_entries(profile_id, _window_release_buckets(signup, slot)))
    return entries


def _cancel_show_and_sell(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    expected_version = require_version(args)
    reason = require_bounded_str(args, "reason", 200)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "cancelShowAndSell")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})

    now = _utcnow()
    stamp = _iso(now)
    merged = {
        **current,
        "status": STORED_CANCELLED,
        "cancelledByAccountId": caller,
        "cancelledAt": stamp,
        "cancellationReason": reason,
        "version": expected_version + 1,
        "updatedAt": stamp,
        "updatedByAccountId": caller,
    }
    update = {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": current["itemKey"]},
            "UpdateExpression": (
                "SET #status = :cancelled, #cancelledByAccountId = :cb, #cancelledAt = :ca, "
                "#cancellationReason = :cr, #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub"
            ),
            "ConditionExpression": "#status <> :cancelled AND #version = :expected",
            "ExpressionAttributeNames": {
                "#status": "status",
                "#cancelledByAccountId": "cancelledByAccountId",
                "#cancelledAt": "cancelledAt",
                "#cancellationReason": "cancellationReason",
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":cancelled": STORED_CANCELLED,
                ":cb": caller,
                ":ca": stamp,
                ":cr": reason,
                ":next": expected_version + 1,
                ":expected": expected_version,
                ":ua": stamp,
                ":ub": caller,
            },
        }
    }
    result = _event_to_graphql(merged, now)
    marker = _marker_put(caller, "cancelShowAndSell", key, fingerprint, result, _epoch(now))
    from boto3.dynamodb.conditions import Key

    cascade_slots = tables.show_and_sells.query(
        KeyConditionExpression=Key("unitCampaignId").eq(current["unitCampaignId"])
        & Key("itemKey").begins_with(f"{SLOT_PREFIX}{show_and_sell_id}#"),
    ).get("Items", [])
    plan = (
        [update]
        + _allocation_release_entries(current, stamp)
        + _signup_cancellation_entries(current, cascade_slots, stamp)
        + [marker]
    )
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT,
            "The event was already cancelled or changed concurrently",
            details={"reason": "ALREADY_CANCELLED"},
        ) from None
    return result


# ---------------------------------------------------------------------------
# Mutations: allocation planner
# ---------------------------------------------------------------------------


def _product_from_balance_key(item_key: str) -> str:
    return item_key[len("BALANCE#") :]


def _split_alloc_key(item_key: str) -> tuple[str, str]:
    """ALLOC#<showAndSellId>#<productId> — ids may contain '#', so only the
    FIRST separator after the prefix splits event from product."""
    body = item_key[len(ALLOC_PREFIX) :]
    event_id, _, product_id = body.partition("#")
    return event_id, product_id


def _open_views_by_product(unit_campaign_id: str) -> Dict[str, List[OpenAllocationView]]:
    """OPEN allocation rows across the Unit Campaign grouped by product, with
    each view carrying its event's interval (cancelled events excluded)."""
    rows = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": ALLOC_PREFIX},
    ).get("Items", [])
    grouped: Dict[str, List[OpenAllocationView]] = {}
    for row in rows:
        if not row.get("itemKey", "").startswith(ALLOC_PREFIX) or row.get("status") != "OPEN":
            continue
        event_id, product_id = _split_alloc_key(row["itemKey"])
        ev = _find_event(event_id)
        if ev is None or ev.get("status") == STORED_CANCELLED:
            continue
        grouped.setdefault(product_id, []).append(
            OpenAllocationView(
                show_and_sell_id=event_id,
                event_start_at=_parse_ts(ev["startAt"]),
                event_end_at=_parse_ts(ev["endAt"]),
                allocated_qty=int(row.get("allocatedQty", 0)),
            )
        )
    return grouped


def _current_targets(existing: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    current_by_product: Dict[str, Dict[str, int]] = {}
    for row in existing:
        product_id = _split_alloc_key(row["itemKey"])[1]
        current_by_product[product_id] = {
            "allocated": int(row.get("allocatedQty", 0)),
            "sold": int(row.get("soldQty", 0)),
            "released": int(row.get("releasedQty", 0)),
        }
    return current_by_product


def _sellable_by_product(lines: List[Any], balance_by_product: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    sellable: Dict[str, int] = {}
    for line in lines:
        balance = balance_by_product.get(line.product_id, {})
        sellable[line.product_id] = int(balance.get("kernelPhysicalQty", 0)) - int(
            balance.get("soldInPossessionQty", 0)
        )
    return sellable


def _allocation_entries(
    lines: List[Any],
    existing: List[Dict[str, Any]],
    unit_campaign_id: str,
    show_and_sell_id: str,
    current: Dict[str, Any],
    stamp: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """TARGET allocation upserts (one per product) plus their wire shapes."""
    plan: List[Dict[str, Any]] = []
    allocations_out = []
    for line in lines:
        remaining = line.target - line.sold
        status = "OPEN" if line.target > 0 else "CLOSED"
        existing_row = next((r for r in existing if _split_alloc_key(r["itemKey"])[1] == line.product_id), None)
        plan.append(
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {
                        "unitCampaignId": unit_campaign_id,
                        "itemKey": f"{ALLOC_PREFIX}{show_and_sell_id}#{line.product_id}",
                    },
                    "UpdateExpression": (
                        "SET #productId = :pid, #showAndSellId = :sid, #eventStartAt = :esa, #eventEndAt = :eea, "
                        "#status = :st, #allocatedQty = :aq, #soldQty = :sq, #releasedQty = :rq, #remainingQty = :rm, "
                        "#version = if_not_exists(#version, :zero) + :one, "
                        "#createdAt = if_not_exists(#createdAt, :ua), #updatedAt = :ua"
                    ),
                    "ConditionExpression": "attribute_not_exists(itemKey) OR #version = :expected_v",
                    "ExpressionAttributeNames": {
                        "#productId": "productId",
                        "#showAndSellId": "showAndSellId",
                        "#eventStartAt": "eventStartAt",
                        "#eventEndAt": "eventEndAt",
                        "#status": "status",
                        "#allocatedQty": "allocatedQty",
                        "#soldQty": "soldQty",
                        "#releasedQty": "releasedQty",
                        "#remainingQty": "remainingQty",
                        "#version": "version",
                        "#createdAt": "createdAt",
                        "#updatedAt": "updatedAt",
                    },
                    "ExpressionAttributeValues": {
                        ":pid": line.product_id,
                        ":sid": show_and_sell_id,
                        ":esa": current["startAt"],
                        ":eea": current["endAt"],
                        ":st": status,
                        ":aq": line.target,
                        ":sq": line.sold,
                        ":rq": line.released,
                        ":rm": remaining,
                        ":zero": 0,
                        ":one": 1,
                        ":ua": stamp,
                        ":expected_v": int(existing_row.get("version", 0)) if existing_row else -1,
                    },
                }
            }
        )
        allocations_out.append(
            {
                "unitCampaignId": unit_campaign_id,
                "productId": line.product_id,
                "showAndSellId": show_and_sell_id,
                "eventStartAt": current["startAt"],
                "eventEndAt": current["endAt"],
                "status": status,
                "allocatedQty": line.target,
                "soldQty": line.sold,
                "releasedQty": line.released,
                "remainingQty": remaining,
                "version": (int(existing_row.get("version", 0)) if existing_row else 0) + 1,
                "createdAt": (existing_row or {}).get("createdAt", stamp),
                "updatedAt": stamp,
            }
        )
    return plan, allocations_out


def _resolve_assign_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the assign input: dedup, non-negative targets, versions."""
    resolved: Dict[str, Any] = {}
    resolved["showAndSellId"] = require_bounded_str(args, "showAndSellId", 100)
    raw_items = args.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AppError(ErrorCode.INVALID_INPUT, "items must be a non-empty list")
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "items entries must be objects")
        product_id = require_bounded_str(entry, "productId", 100)
        target = require_strict_int(entry, "quantity")
        if target < 0:
            raise AppError(ErrorCode.INVALID_INPUT, "quantity must not be negative")
        if product_id in seen:
            raise AppError(ErrorCode.INVALID_INPUT, "items must not repeat a productId")
        seen.add(product_id)
        items.append({"productId": product_id, "quantity": target})
    resolved["items"] = items
    resolved["expectedVersion"] = require_version(args)
    resolved["idempotencyKey"] = require_idempotency_key(args)
    return resolved


def _assign_show_and_sell_inventory(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    resolved = _resolve_assign_input(args)
    show_and_sell_id = resolved["showAndSellId"]
    items = resolved["items"]
    expected_version = resolved["expectedVersion"]
    key = resolved["idempotencyKey"]

    caller, fingerprint, replayed = _idempotency_begin(event, args, "assignShowAndSellInventory")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if current.get("status") == STORED_CANCELLED:
        raise AppError(
            ErrorCode.CONFLICT, "A cancelled event cannot be assigned inventory", details={"reason": "ACTIVE_GUARD"}
        )

    unit_campaign_id = current["unitCampaignId"]
    # Current allocations on the TARGET event + sold/released per product.
    existing = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{ALLOC_PREFIX}{show_and_sell_id}#"},
    ).get("Items", [])
    lines = plan_targets(items, _current_targets(existing))
    for line in lines:
        violation = validate_plan_line(line)
        if violation:
            raise AppError(
                ErrorCode.CONFLICT,
                f"Target for {line.product_id} is below its sold quantity ({violation})",
                details={"reason": "SOLD_STOCK_PROTECTION", "productId": line.product_id},
            )

    # Sellable per product + open allocations across the Unit Campaign.
    balances = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": "BALANCE#"},
    ).get("Items", [])
    balance_by_product = {_product_from_balance_key(b["itemKey"]): b for b in balances}
    sellable_by_product = _sellable_by_product(lines, balance_by_product)
    open_by_product = _open_views_by_product(unit_campaign_id)

    warnings, hard_blocks = evaluate_assignment(
        lines,
        sellable_by_product=sellable_by_product,
        open_by_product=open_by_product,
        target_start=_parse_ts(current["startAt"]),
        target_end=_parse_ts(current["endAt"]),
        target_show_and_sell_id=show_and_sell_id,
        event_location_name=current["locationName"],
    )
    if hard_blocks:
        raise AppError(
            ErrorCode.CONFLICT,
            "Concurrent over-assignment would exceed sellable stock",
            details={"reason": "CONCURRENT_OVER_ASSIGNMENT", "blocks": hard_blocks},
        )

    now = _utcnow()
    stamp = _iso(now)
    plan, allocations_out = _allocation_entries(lines, existing, unit_campaign_id, show_and_sell_id, current, stamp)
    event_update = _event_bump_entry(current, expected_version, caller, stamp)
    plan.append(event_update)

    def project_positions() -> List[Dict[str, Any]]:
        from src.utils.inventory_derived import derive_position

        positions = []
        for line in lines:
            balance = balance_by_product.get(line.product_id, {})
            positions.append(
                derive_position(
                    unit_campaign_id=unit_campaign_id,
                    product_id=line.product_id,
                    kernel_physical_qty=int(balance.get("kernelPhysicalQty", 0)),
                    sold_in_possession_qty=int(balance.get("soldInPossessionQty", 0)),
                    council_on_order_qty=int(balance.get("councilOnOrderQty", 0)),
                    balance_version=int(balance.get("version", 0)),
                    allocations=[],
                    custody_rows=[],
                )
            )
        return positions

    result = {"allocations": allocations_out, "inventoryPositions": project_positions(), "warnings": warnings}
    marker = _marker_put(caller, "assignShowAndSellInventory", key, fingerprint, result, _epoch(now))
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
            "Allocation raced a concurrent change; re-read and retry",
            details={"reason": "VERSION_MISMATCH"},
        ) from None
    return result


# ---------------------------------------------------------------------------
# Mutations: slots, signups, work confirmation
# ---------------------------------------------------------------------------


def _resolve_slot_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the upsertShowAndSellSlot input (deterministic, pre-marker)."""
    resolved: Dict[str, Any] = {}
    resolved["showAndSellId"] = require_bounded_str(args, "showAndSellId", 100)
    slot_id = args.get("slotId")
    if slot_id is not None:
        slot_id = require_bounded_str(args, "slotId", 100)
    resolved["slotId"] = slot_id
    label = args.get("label")
    if label is not None:
        label = require_bounded_str(args, "label", 100)
    resolved["label"] = label
    start_at = require_timestamp(args, "startAt")
    end_at = require_timestamp(args, "endAt")
    if _parse_ts(end_at) <= _parse_ts(start_at):
        raise AppError(ErrorCode.INVALID_INPUT, "endAt must be after startAt")
    resolved["startAt"] = start_at
    resolved["endAt"] = end_at
    capacity = require_strict_int(args, "capacity")
    if capacity < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "capacity must not be negative")
    resolved["capacity"] = capacity
    resolved["expectedEventVersion"] = require_version(args, "expectedEventVersion")
    slot_version = args.get("expectedSlotVersion")
    if slot_version is not None:
        slot_version = require_strict_int(args, "expectedSlotVersion")
        if slot_version < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "expectedSlotVersion must be a positive integer")
    if slot_id is not None and slot_version is None:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedSlotVersion is required when updating an existing slot")
    resolved["expectedSlotVersion"] = slot_version
    resolved["idempotencyKey"] = require_idempotency_key(args)
    return resolved


def _slot_write_entry(
    *,
    is_create: bool,
    unit_campaign_id: str,
    show_and_sell_id: str,
    slot_id: str,
    start_at: str,
    end_at: str,
    capacity: int,
    label: Optional[str],
    existing_slot: Optional[Dict[str, Any]],
    expected_slot_version: Optional[int],
    stamp: str,
) -> tuple[Dict[str, Any], Dict[str, Any], int]:
    """Build the create-Put or conditional update for one slot; returns
    (entry, slot_item, new_slot_version)."""
    if is_create:
        slot_item = {
            "unitCampaignId": unit_campaign_id,
            "itemKey": f"{SLOT_PREFIX}{show_and_sell_id}#{slot_id}",
            "showAndSellId": show_and_sell_id,
            "slotId": slot_id,
            "startAt": start_at,
            "endAt": end_at,
            "capacity": capacity,
            "activeSignupCount": 0,
            "version": 1,
            "createdAt": stamp,
            "updatedAt": stamp,
        }
        if label is not None:
            slot_item["label"] = label
        return (
            {
                "Put": {
                    "TableName": tables.show_and_sells.table_name,
                    "Item": slot_item,
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            },
            slot_item,
            1,
        )
    assert existing_slot is not None and expected_slot_version is not None
    if int(existing_slot.get("version", 0)) != expected_slot_version:
        raise AppError(ErrorCode.CONFLICT, "Slot was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    slot_item = {
        **existing_slot,
        "startAt": start_at,
        "endAt": end_at,
        "capacity": capacity,
        "version": expected_slot_version + 1,
        "updatedAt": stamp,
    }
    if label is not None:
        slot_item["label"] = label
    entry = {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": slot_item["itemKey"]},
            "UpdateExpression": (
                "SET #startAt = :sa, #endAt = :ea, #capacity = :cap, #version = :next, #updatedAt = :ua"
                + (", #label = :label" if label is not None else "")
            ),
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#startAt": "startAt",
                "#endAt": "endAt",
                "#capacity": "capacity",
                "#version": "version",
                "#updatedAt": "updatedAt",
                **({"#label": "label"} if label is not None else {}),
            },
            "ExpressionAttributeValues": {
                ":sa": start_at,
                ":ea": end_at,
                ":cap": capacity,
                ":next": expected_slot_version + 1,
                ":expected": expected_slot_version,
                ":ua": stamp,
                **({":label": label} if label is not None else {}),
            },
        }
    }
    return entry, slot_item, expected_slot_version + 1


def _guard_slot_capacity(is_create: bool, existing_slots: List[Dict[str, Any]]) -> None:
    """The 20-active-slot cap applies only when a NEW slot would exceed it."""
    if is_create and len(existing_slots) >= MAX_ACTIVE_SLOTS:
        raise AppError(
            ErrorCode.CONFLICT,
            f"An event can have at most {MAX_ACTIVE_SLOTS} active slots",
            details={"reason": "SLOT_LIMIT"},
        )


def _load_slot_for_write(
    unit_campaign_id: str, show_and_sell_id: str, slot_id: str, is_create: bool
) -> Optional[Dict[str, Any]]:
    existing_slot = tables.show_and_sells.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{SLOT_PREFIX}{show_and_sell_id}#{slot_id}"},
        ConsistentRead=True,
    ).get("Item")
    if is_create and isinstance(existing_slot, dict):
        raise AppError(ErrorCode.CONFLICT, "slotId already exists", details={"reason": "ALREADY_EXISTS"})
    if not is_create and not isinstance(existing_slot, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found")
    return existing_slot if isinstance(existing_slot, dict) else None


def _upsert_show_and_sell_slot(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    resolved = _resolve_slot_input(event.get("arguments", {}).get("input") or {})
    args = event.get("arguments", {}).get("input") or {}
    show_and_sell_id = resolved["showAndSellId"]
    slot_id = resolved["slotId"]
    label = resolved["label"]
    start_at = resolved["startAt"]
    end_at = resolved["endAt"]
    capacity = resolved["capacity"]
    expected_event_version = resolved["expectedEventVersion"]
    expected_slot_version = resolved["expectedSlotVersion"]
    key = resolved["idempotencyKey"]

    caller, fingerprint, replayed = _idempotency_begin(event, args, "upsertShowAndSellSlot")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_event_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if current.get("status") == STORED_CANCELLED:
        raise AppError(ErrorCode.CONFLICT, "A cancelled event cannot change slots", details={"reason": "ACTIVE_GUARD"})

    unit_campaign_id = current["unitCampaignId"]
    is_create = slot_id is None
    slot_id = slot_id or str(uuid.uuid4())
    existing_slot = _load_slot_for_write(unit_campaign_id, show_and_sell_id, slot_id, is_create)

    existing_slots = _slots_for(show_and_sell_id, unit_campaign_id)
    _guard_slot_capacity(is_create, existing_slots)

    now = _utcnow()
    stamp = _iso(now)
    slot_entry, slot_item, slot_version = _slot_write_entry(
        is_create=is_create,
        unit_campaign_id=unit_campaign_id,
        show_and_sell_id=show_and_sell_id,
        slot_id=slot_id,
        start_at=start_at,
        end_at=end_at,
        capacity=capacity,
        label=label,
        existing_slot=existing_slot if isinstance(existing_slot, dict) else None,
        expected_slot_version=expected_slot_version,
        stamp=stamp,
    )
    event_update = _event_bump_entry(current, expected_event_version, caller, stamp)
    result = _slot_to_graphql(slot_item)
    result["version"] = slot_version
    marker = _marker_put(caller, "upsertShowAndSellSlot", key, fingerprint, result, _epoch(now))
    _execute_replayable([slot_entry, event_update, marker], marker)
    return result


def _delete_show_and_sell_slot(event: Dict[str, Any], context: Any) -> bool:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    slot_id = require_bounded_str(args, "slotId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "deleteShowAndSellSlot")
    if replayed is not None:
        return bool(replayed["deleted"])
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})

    unit_campaign_id = current["unitCampaignId"]
    slot_item = tables.show_and_sells.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{SLOT_PREFIX}{show_and_sell_id}#{slot_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(slot_item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found")

    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = [
        {
            "Delete": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": slot_item["itemKey"]},
                "ConditionExpression": "attribute_exists(itemKey)",
            }
        },
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": current["itemKey"]},
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
        },
    ]
    # Remove the slot's signup rows in the same transaction.
    from boto3.dynamodb.conditions import Key

    signups = tables.show_and_sells.query(
        KeyConditionExpression=Key("unitCampaignId").eq(unit_campaign_id)
        & Key("itemKey").begins_with(f"{SIGNUP_PREFIX}{slot_id}#"),
    ).get("Items", [])
    for signup in signups:
        plan.append(
            {
                "Delete": {
                    "TableName": tables.show_and_sells.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": signup["itemKey"]},
                    "ConditionExpression": "attribute_exists(itemKey)",
                }
            }
        )
    marker = _marker_put(caller, "deleteShowAndSellSlot", key, fingerprint, {"deleted": True}, _epoch(now))
    plan.append(marker)
    _execute_replayable(plan, marker)
    return True


def _signup_to_graphql(item: Dict[str, Any], admin_view: bool = False) -> Dict[str, Any]:
    result = {
        "showAndSellId": item["showAndSellId"],
        "slotId": item["slotId"],
        "profileId": item["profileId"],
        "unitCampaignId": item["unitCampaignId"],
        "campaignId": item["campaignId"],
        "status": item["status"],
        "actualMinutes": int(item.get("actualMinutes", 0)),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
        "version": int(item.get("version", 0)),
    }
    if admin_view:
        result["signedUpByAccountId"] = item.get("signedUpByAccountId", "")
        result["confirmedByAccountId"] = item.get("confirmedByAccountId")
        result["confirmedAt"] = item.get("confirmedAt")
    return result


WINDOW_PREFIX = "PROFILEWINDOW#"
WINDOW_BUCKET_SECONDS = 30 * 60  # 30-minute fixed grid; overlapping slots always share a bucket


def _window_buckets(start_at: str, end_at: str) -> List[str]:
    """The fixed-grid bucket starts an interval touches. Two overlapping
    intervals always share at least one bucket, so one attribute_not_exists
    Put per bucket is EXACT atomic overlap prevention (SIGN-M-01 / DM-AC-14);
    the friendly pre-read only improves the error message."""
    start = _parse_ts(start_at)
    end = _parse_ts(end_at)
    buckets = []
    current = int(start.timestamp() // WINDOW_BUCKET_SECONDS) * WINDOW_BUCKET_SECONDS
    last = int((end.timestamp() - 1) // WINDOW_BUCKET_SECONDS) * WINDOW_BUCKET_SECONDS
    while current <= last:
        buckets.append(str(current))
        current += WINDOW_BUCKET_SECONDS
    return buckets


def _window_put_entries(profile_id: str, buckets: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": {
                    "unitCampaignId": f"{WINDOW_PREFIX}{profile_id}",
                    "itemKey": bucket,
                    "profileId": profile_id,
                    "bucketStartEpoch": int(bucket),
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        }
        for bucket in buckets
    ]


def _window_delete_entries(profile_id: str, buckets: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "Delete": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": f"{WINDOW_PREFIX}{profile_id}", "itemKey": bucket},
                "ConditionExpression": "attribute_exists(itemKey)",
            }
        }
        for bucket in buckets
    ]


def _profile_active_intervals(profile_id: str, exclude_signup_key: Optional[str] = None) -> List[Dict[str, str]]:
    """The profile's ACTIVE signup intervals across Unit Campaigns (the
    friendly overlap pre-read; the atomic guard is the window buckets)."""
    intervals = []
    memberships = tables.unit_campaigns.query(
        IndexName="profileId-unitCampaignId-index",
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
    ).get("Items", [])
    for membership in memberships:
        unit_campaign_id = membership["unitCampaignId"]
        signups = tables.show_and_sells.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": SIGNUP_PREFIX},
        ).get("Items", [])
        for signup in signups:
            if signup.get("profileId") != profile_id or signup.get("status") != SIGNUP_ACTIVE:
                continue
            if exclude_signup_key is not None and signup["itemKey"] == exclude_signup_key:
                continue
            slot = tables.show_and_sells.get_item(
                Key={
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"{SLOT_PREFIX}{signup['showAndSellId']}#{signup['slotId']}",
                },
                ConsistentRead=True,
            ).get("Item")
            if isinstance(slot, dict):
                intervals.append({"startAt": slot["startAt"], "endAt": slot["endAt"], "itemKey": signup["itemKey"]})
    return intervals


def _check_overlap(profile_id: str, slot: Dict[str, Any], exclude_signup_key: Optional[str] = None) -> None:
    start = _parse_ts(slot["startAt"])
    end = _parse_ts(slot["endAt"])
    for interval in _profile_active_intervals(profile_id, exclude_signup_key):
        other_start = _parse_ts(interval["startAt"])
        other_end = _parse_ts(interval["endAt"])
        if other_start < end and other_end > start:
            raise AppError(
                ErrorCode.CONFLICT,
                "The Scout has a conflicting commitment in another campaign or slot",
                details={"reason": "OVERLAPPING_COMMITMENT"},
            )


def _signup_write_plan(
    *,
    signup_item: Dict[str, Any],
    slot: Dict[str, Any],
    unit_campaign_id: str,
    membership: Dict[str, Any],
    event_item: Dict[str, Any],
    caller: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """The six-write signup contract (r1 CHANGES-2 + r2 W4-1, ported from the
    clean room's SIGN-M-01): signup row, conditioned slot counter, CONDITIONED
    MEMBERSHIP update (version + ACTIVE — a removal racing the signup cancels
    the transaction, DM-AC-19), event version bump, and the SIGNUPWINDOW
    bucket proofs (attribute_not_exists — exact atomic overlap prevention,
    DM-AC-14). The marker rides last."""
    capacity = int(slot.get("capacity", 0))
    plan = [
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": signup_item,
                "ConditionExpression": "attribute_not_exists(itemKey) OR #status = :cancelled",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {":cancelled": SIGNUP_CANCELLED},
            }
        },
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": slot["itemKey"]},
                "UpdateExpression": "ADD activeSignupCount :one SET updatedAt = :ua",
                "ConditionExpression": "activeSignupCount < :capacity AND version = :sv",
                "ExpressionAttributeValues": {
                    ":one": 1,
                    ":ua": stamp,
                    ":capacity": capacity,
                    ":sv": int(slot.get("version", 0)),
                },
            }
        },
        {
            "Update": {
                "TableName": tables.unit_campaigns.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"MEMBER#{signup_item['profileId']}"},
                "UpdateExpression": "ADD version :one SET updatedAt = :ua",
                "ConditionExpression": "#status = :active AND version = :mv",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":one": 1,
                    ":ua": stamp,
                    ":active": "ACTIVE",
                    ":mv": int(membership.get("version", 0)),
                },
            }
        },
        _event_bump_entry(event_item, int(event_item.get("version", 0)), caller, stamp),
    ]
    plan.extend(_window_put_entries(str(signup_item["profileId"]), _window_buckets(slot["startAt"], slot["endAt"])))
    return plan


def _authorize_signup_campaign(campaign_id: str, profile_id: str, caller: str) -> None:
    """The caller must control the Scout Campaign, which must belong to the
    named profile, and the campaign must exist (authoritative base read)."""
    pointer = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": campaign_id},
        Limit=1,
    ).get("Items", [])
    if not pointer:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    campaign = tables.campaigns.get_item(
        Key={"profileId": pointer[0]["profileId"], "campaignId": campaign_id}, ConsistentRead=True
    ).get("Item")
    if not isinstance(campaign, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    if campaign["profileId"] != profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign does not belong to the specified profile")
    if not check_profile_access(caller, profile_id, "WRITE"):
        raise AppError(ErrorCode.FORBIDDEN, "You do not have access to this Campaign")


def _require_active_membership(unit_campaign_id: str, profile_id: str) -> None:
    """Sequence contract: the Scout Campaign must be an ACTIVE roster member
    of the event's Unit Campaign (finalization feasibility)."""
    membership = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"MEMBER#{profile_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(membership, dict) or membership.get("status") != "ACTIVE":
        raise AppError(
            ErrorCode.CONFLICT,
            "The Scout Campaign must join the Unit Campaign before signing up",
            details={"reason": "NOT_ROSTERED"},
        )


def _signup_scout_for_slot(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    slot_id = require_bounded_str(args, "slotId", 100)
    campaign_id = require_bounded_str(args, "campaignId", 100)
    profile_id = require_bounded_str(args, "profileId", 100)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "signupScoutForShowAndSellSlot")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    slot = tables.show_and_sells.get_item(
        Key={"unitCampaignId": current["unitCampaignId"], "itemKey": f"{SLOT_PREFIX}{show_and_sell_id}#{slot_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(slot, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found")
    if current.get("status") == STORED_CANCELLED:
        raise AppError(ErrorCode.CONFLICT, "A cancelled event cannot take signups", details={"reason": "ACTIVE_GUARD"})

    _authorize_signup_campaign(campaign_id, profile_id, caller)
    _require_active_membership(current["unitCampaignId"], profile_id)
    membership = (
        tables.unit_campaigns.get_item(
            Key={"unitCampaignId": current["unitCampaignId"], "itemKey": f"MEMBER#{profile_id}"},
            ConsistentRead=True,
        ).get("Item")
        or {}
    )
    # Friendly overlap pre-read (the message); the atomic guard is the
    # SIGNUPWINDOW bucket proofs in the transaction (DM-AC-14).
    _check_overlap(profile_id, slot)

    now = _utcnow()
    stamp = _iso(now)
    signup_item = {
        "unitCampaignId": current["unitCampaignId"],
        "itemKey": f"{SIGNUP_PREFIX}{slot_id}#{profile_id}",
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "profileId": profile_id,
        "campaignId": campaign_id,
        "status": SIGNUP_ACTIVE,
        "actualMinutes": 0,
        "signedUpByAccountId": caller,
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    plan = _signup_write_plan(
        signup_item=signup_item,
        slot=slot,
        unit_campaign_id=current["unitCampaignId"],
        membership=membership,
        event_item=current,
        caller=caller,
        stamp=stamp,
    )
    result = _signup_to_graphql(signup_item)
    marker = _marker_put(caller, "signupScoutForShowAndSellSlot", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    window_start = 4  # after signup, slot, membership, event bump
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        marker_index = plan.index(marker)
        if marker_index in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        if 2 in exc.failed_indexes:
            # The membership version+ACTIVE condition fired: a removal raced
            # the signup (DM-AC-19) or the roster changed under it.
            raise AppError(
                ErrorCode.CONFLICT,
                "The Scout's membership changed concurrently; re-check the roster",
                details={"reason": "NOT_ROSTERED"},
            ) from None
        if any(window_start <= idx < marker_index for idx in exc.failed_indexes):
            raise AppError(
                ErrorCode.CONFLICT,
                "The Scout has a conflicting commitment in another campaign or slot",
                details={"reason": "OVERLAPPING_COMMITMENT"},
            ) from None
        raise AppError(
            ErrorCode.CONFLICT,
            "The slot is full or the event changed; retry the signup",
            details={"reason": "SLOT_FULL"},
        ) from None
    return result


def _cancel_show_and_sell_signup(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    slot_id = require_bounded_str(args, "slotId", 100)
    profile_id = require_bounded_str(args, "profileId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "cancelShowAndSellSignup")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    signup = tables.show_and_sells.get_item(
        Key={"unitCampaignId": current["unitCampaignId"], "itemKey": f"{SIGNUP_PREFIX}{slot_id}#{profile_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(signup, dict) or signup.get("status") != SIGNUP_ACTIVE:
        raise AppError(ErrorCode.NOT_FOUND, "Signup not found")
    if int(signup.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Signup was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    slot = tables.show_and_sells.get_item(
        Key={"unitCampaignId": current["unitCampaignId"], "itemKey": f"{SLOT_PREFIX}{show_and_sell_id}#{slot_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(slot, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found")

    now = _utcnow()
    stamp = _iso(now)
    merged = {**signup, "status": SIGNUP_CANCELLED, "version": expected_version + 1, "updatedAt": stamp}
    # Release the signup's window buckets (retaining buckets another ACTIVE
    # signup of the same profile still claims), then the slot decrement.
    buckets = _window_buckets(slot["startAt"], slot["endAt"])
    other_buckets: set[str] = set()
    for interval in _profile_active_intervals(profile_id, exclude_signup_key=signup["itemKey"]):
        other_buckets.update(_window_buckets(interval["startAt"], interval["endAt"]))
    plan = _window_delete_entries(profile_id, [b for b in buckets if b not in other_buckets]) + [
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": signup["itemKey"]},
                "UpdateExpression": "SET #status = :cancelled, #version = :next, #updatedAt = :ua",
                "ConditionExpression": "#status = :active AND #version = :expected",
                "ExpressionAttributeNames": {"#status": "status", "#version": "version", "#updatedAt": "updatedAt"},
                "ExpressionAttributeValues": {
                    ":cancelled": SIGNUP_CANCELLED,
                    ":active": SIGNUP_ACTIVE,
                    ":next": expected_version + 1,
                    ":expected": expected_version,
                    ":ua": stamp,
                },
            }
        },
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": slot["itemKey"]},
                "UpdateExpression": "ADD activeSignupCount :neg SET updatedAt = :ua",
                "ConditionExpression": "activeSignupCount > :zero",
                "ExpressionAttributeValues": {":neg": -1, ":ua": stamp, ":zero": 0},
            }
        },
    ]
    result = _signup_to_graphql(merged)
    marker = _marker_put(caller, "cancelShowAndSellSignup", key, fingerprint, result, _epoch(now))
    plan.append(marker)
    _execute_replayable(plan, marker)
    return result


def _resolve_work_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the work-confirmation input: dedup slot/profile pairs,
    non-negative minutes."""
    resolved: Dict[str, Any] = {}
    resolved["showAndSellId"] = require_bounded_str(args, "showAndSellId", 100)
    raw_work = args.get("work")
    if not isinstance(raw_work, list) or not raw_work:
        raise AppError(ErrorCode.INVALID_INPUT, "work must be a non-empty list")
    work: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_work:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "work entries must be objects")
        slot_id = require_bounded_str(entry, "slotId", 100)
        profile_id = require_bounded_str(entry, "profileId", 100)
        minutes = require_strict_int(entry, "actualMinutes")
        if minutes < 0:
            raise AppError(ErrorCode.INVALID_INPUT, "actualMinutes must not be negative")
        pair = f"{slot_id}#{profile_id}"
        if pair in seen:
            raise AppError(ErrorCode.INVALID_INPUT, "work must not repeat a slot/profile pair")
        seen.add(pair)
        work.append({"slotId": slot_id, "profileId": profile_id, "actualMinutes": minutes})
    resolved["work"] = work
    resolved["expectedVersion"] = require_version(args)
    resolved["idempotencyKey"] = require_idempotency_key(args)
    return resolved


def _confirm_show_and_sell_work(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    resolved = _resolve_work_input(args)
    show_and_sell_id = resolved["showAndSellId"]
    work = resolved["work"]
    expected_version = resolved["expectedVersion"]
    key = resolved["idempotencyKey"]

    caller, fingerprint, replayed = _idempotency_begin(event, args, "confirmShowAndSellWork")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})

    unit_campaign_id = current["unitCampaignId"]
    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = []
    signups_out = []
    totals: Dict[str, int] = {}
    for entry in work:
        signup = tables.show_and_sells.get_item(
            Key={
                "unitCampaignId": unit_campaign_id,
                "itemKey": f"{SIGNUP_PREFIX}{entry['slotId']}#{entry['profileId']}",
            },
            ConsistentRead=True,
        ).get("Item")
        if not isinstance(signup, dict) or signup.get("status") != SIGNUP_ACTIVE:
            raise AppError(
                ErrorCode.NOT_FOUND,
                f"No active signup for slot {entry['slotId']} profile {entry['profileId']}",
            )
        merged = {
            **signup,
            "actualMinutes": entry["actualMinutes"],
            "version": int(signup.get("version", 0)) + 1,
            "updatedAt": stamp,
            "confirmedByAccountId": caller,
            "confirmedAt": stamp,
        }
        plan.append(
            {
                "Update": {
                    "TableName": tables.show_and_sells.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": signup["itemKey"]},
                    "UpdateExpression": (
                        "SET #actualMinutes = :am, #confirmedByAccountId = :cb, #confirmedAt = :ca, "
                        "#version = :next, #updatedAt = :ua"
                    ),
                    "ConditionExpression": "#status = :active AND #version = :expected",
                    "ExpressionAttributeNames": {
                        "#actualMinutes": "actualMinutes",
                        "#confirmedByAccountId": "confirmedByAccountId",
                        "#confirmedAt": "confirmedAt",
                        "#status": "status",
                        "#version": "version",
                        "#updatedAt": "updatedAt",
                    },
                    "ExpressionAttributeValues": {
                        ":am": entry["actualMinutes"],
                        ":cb": caller,
                        ":ca": stamp,
                        ":active": SIGNUP_ACTIVE,
                        ":next": int(signup.get("version", 0)) + 1,
                        ":expected": int(signup.get("version", 0)),
                        ":ua": stamp,
                    },
                }
            }
        )
        signups_out.append(_signup_to_graphql(merged, admin_view=True))
        totals[entry["profileId"]] = totals.get(entry["profileId"], 0) + entry["actualMinutes"]
    event_update = _event_bump_entry(current, expected_version, caller, stamp)
    plan.append(event_update)
    total_minutes = sum(totals.values())
    split_note = (
        "Split will be computed per confirmed time worked."
        if current.get("splitMethod") == "TIME_WORKED"
        else "Split will be computed equally across participating Scouts."
    )
    result = {
        "signups": signups_out,
        "pendingPreview": {
            "totalConfirmedMinutes": total_minutes,
            "confirmedMinutesByProfileId": [
                {"profileId": pid, "confirmedMinutes": mins} for pid, mins in sorted(totals.items())
            ],
            "note": split_note,
        },
    }
    marker = _marker_put(caller, "confirmShowAndSellWork", key, fingerprint, result, _epoch(now))
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
            "Work confirmation raced a concurrent change; re-read and retry",
            details={"reason": "VERSION_MISMATCH"},
        ) from None
    return result


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _get_show_and_sell(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    try:
        _require_event_admin(current, caller)
    except AppError:
        # Roster participants may read the event: any ACTIVE membership in
        # the Unit Campaign grants the participant view.
        memberships = tables.unit_campaigns.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": current["unitCampaignId"], ":prefix": "MEMBER#"},
        ).get("Items", [])
        profile_ids = {m["profileId"] for m in memberships if m.get("status") == "ACTIVE"}
        if not any(check_profile_access(caller, pid, "READ") for pid in profile_ids):
            raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    return _event_to_graphql(current, _utcnow())


def _event_page_items(
    kwargs: Dict[str, Any], status: Optional[str], now: datetime, limit: int
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fetch EVENT rows through the startAt index, deriving status and
    filtering, until the page fills or the index exhausts."""
    items: List[Dict[str, Any]] = []
    response = tables.show_and_sells.query(**kwargs)
    last_key = response.get("LastEvaluatedKey")

    def _collect(rows: List[Dict[str, Any]]) -> None:
        for item in rows:
            if not item.get("itemKey", "").startswith(EVENT_PREFIX):
                continue
            derived = _derive_status(item, now)
            if status is None or derived == status:
                items.append(_event_to_graphql(item, now, include_slots=False))

    _collect(response.get("Items", []))
    while last_key is not None and len(items) < limit:
        kwargs["ExclusiveStartKey"] = last_key
        response = tables.show_and_sells.query(**kwargs)
        _collect(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
    return items[:limit], last_key


def _list_show_and_sells(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    status = args.get("status")
    if status is not None:
        status = require_str_enum(
            args, "status", ("SCHEDULED", "ACTIVE", "ENDED", "FINALIZED", "REOPENED", "CANCELLED")
        )
    caller = _require_caller(event)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    page = args.get("page") or {}
    limit = validate_page_limit(page.get("limit"))
    kwargs: Dict[str, Any] = {
        "IndexName": "unitCampaignId-startAt-index",
        "KeyConditionExpression": Key("unitCampaignId").eq(unit_campaign_id),
        "Limit": limit,
    }
    if page.get("cursor"):
        kwargs["ExclusiveStartKey"] = decode_cursor(page["cursor"], f"showAndSells:{unit_campaign_id}:{status}")
    now = _utcnow()
    items, last_key = _event_page_items(kwargs, status, now, limit)
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"showAndSells:{unit_campaign_id}:{status}", last_key) if last_key else None,
            "hasNextPage": last_key is not None,
        },
    }


def _allocation_view(
    row: Dict[str, Any],
    unit_campaign_id: str,
    show_and_sell_id: Optional[str],
    product_id: Optional[str],
    status: Optional[str],
) -> Optional[Dict[str, Any]]:
    row_event_id, row_product = _split_alloc_key(row["itemKey"])
    if not row_event_id or not row_product:
        return None
    if show_and_sell_id is not None and row_event_id != show_and_sell_id:
        return None
    if product_id is not None and row_product != product_id:
        return None
    if status is not None and row.get("status") != status:
        return None
    ev = _find_event(row_event_id) or {}
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": row_product,
        "showAndSellId": row_event_id,
        "eventStartAt": row.get("eventStartAt", ev.get("startAt", "")),
        "eventEndAt": row.get("eventEndAt", ev.get("endAt", "")),
        "status": row.get("status", ""),
        "allocatedQty": int(row.get("allocatedQty", 0)),
        "soldQty": int(row.get("soldQty", 0)),
        "releasedQty": int(row.get("releasedQty", 0)),
        "remainingQty": int(row.get("remainingQty", 0)),
        "version": int(row.get("version", 0)),
        "createdAt": row.get("createdAt", ""),
        "updatedAt": row.get("updatedAt", ""),
    }


def _event_inventory_allocations(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    show_and_sell_id = args.get("showAndSellId")
    product_id = args.get("productId")
    status = args.get("status")
    caller = _require_caller(event)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    response = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": ALLOC_PREFIX},
    )
    items = [
        view
        for row in response.get("Items", [])
        if (view := _allocation_view(row, unit_campaign_id, show_and_sell_id, product_id, status)) is not None
    ]
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _show_and_sell_signups(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    show_and_sell_id = require_bounded_str(args, "showAndSellId", 100)
    status = args.get("status")
    if status is not None:
        status = require_str_enum(args, "status", (SIGNUP_ACTIVE, SIGNUP_CANCELLED))
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    response = tables.show_and_sells.query(
        KeyConditionExpression=Key("unitCampaignId").eq(current["unitCampaignId"])
        & Key("itemKey").begins_with(SIGNUP_PREFIX),
    )
    items = [
        _signup_to_graphql(item, admin_view=True)
        for item in response.get("Items", [])
        if item.get("showAndSellId") == show_and_sell_id and (status is None or item.get("status") == status)
    ]
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "createShowAndSell": _create_show_and_sell,
    "updateShowAndSell": _update_show_and_sell,
    "cancelShowAndSell": _cancel_show_and_sell,
    "assignShowAndSellInventory": _assign_show_and_sell_inventory,
    "upsertShowAndSellSlot": _upsert_show_and_sell_slot,
    "deleteShowAndSellSlot": _delete_show_and_sell_slot,
    "signupScoutForShowAndSellSlot": _signup_scout_for_slot,
    "cancelShowAndSellSignup": _cancel_show_and_sell_signup,
    "confirmShowAndSellWork": _confirm_show_and_sell_work,
    "showAndSell": _get_show_and_sell,
    "showAndSells": _list_show_and_sells,
    "eventInventoryAllocations": _event_inventory_allocations,
    "showAndSellSignups": _show_and_sell_signups,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch an event operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported event operation: {field_name}")
    return operation(event, context)
