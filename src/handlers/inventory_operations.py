"""
Inventory operations handlers: balances, movements, custody issue/return
(Show & Sell, spec API §6 / DATA_MODEL §7).

Impact map §3.5 `src/handlers/inventory_operations.py` in the application's
handler conventions. Custody moves (issue/return) are single-transaction
balance + custody + movement writes — the same atomicity class the custody
createOrder Lambda upholds (r2 C-1): a stock move either fully lands or
leaves no trace.

Read-then-plan discipline: every mutation reads the balance/custody rows it
will touch (consistent reads), computes the post-write projection
deterministically, and commits the projection INSIDE the idempotency marker
in the same transaction, with the write entries conditioned on the versions
read (optimistic concurrency — a lost update cancels the transaction rather
than silently overwriting). A concurrent same-key commit is replayed from
the marker; a condition failure surfaces as the domain error.

Item layout (inventory table, wave-1 design):
- BALANCE#<productId>: {kernelPhysicalQty, soldInPossessionQty,
  councilOnOrderQty, version}
- CUSTODY#<profileId>#<productId>: {withScoutQty, version, campaignId}
- MOVEMENT#<occurredAt>#<movementId>: append-style audit with per-bucket
  deltas (kernelPhysical / soldPossession / withScout / assigned /
  councilOnOrder) plus actor, reason, and the inventory version it wrote.
- ALLOC#<showAndSellId>#<productId>: wave-4 event allocations (already read
  by the position projection; nothing here writes them yet).
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_strict_int,
        require_timestamp,
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
    from utils.inventory_derived import derive_position
    from utils.logging import get_logger
    from utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_strict_int,
        require_timestamp,
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
    from ..utils.inventory_derived import derive_position
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
BALANCE_PREFIX = "BALANCE#"
CUSTODY_PREFIX = "CUSTODY#"
MOVEMENT_PREFIX = "MOVEMENT#"
ALLOC_PREFIX = "ALLOC#"

ZERO_BALANCE = {"kernelPhysicalQty": 0, "soldInPossessionQty": 0, "councilOnOrderQty": 0, "version": 0}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return str(moment.isoformat()).replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _fingerprint(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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
    replayed = _check_marker(_get_marker(caller, scope, str(args.get("idempotencyKey", ""))), fingerprint)
    return caller, fingerprint, replayed


def _require_caller(event: Dict[str, Any]) -> str:
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller)


def _require_uc_admin(unit_campaign_id: str, caller: str) -> Dict[str, Any]:
    response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, item["unitId"], caller)
    return item


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


def _read_balance(unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    item = tables.inventory.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"}, ConsistentRead=True
    ).get("Item")
    if not isinstance(item, dict):
        return dict(ZERO_BALANCE)
    return {
        "kernelPhysicalQty": int(item.get("kernelPhysicalQty", 0)),
        "soldInPossessionQty": int(item.get("soldInPossessionQty", 0)),
        "councilOnOrderQty": int(item.get("councilOnOrderQty", 0)),
        "version": int(item.get("version", 0)),
    }


def _read_custody(unit_campaign_id: str, profile_id: str, product_id: str) -> Dict[str, Any]:
    item = tables.inventory.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{CUSTODY_PREFIX}{profile_id}#{product_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(item, dict):
        return {"withScoutQty": 0, "version": 0, "campaignId": ""}
    return {
        "withScoutQty": int(item.get("withScoutQty", 0)),
        "version": int(item.get("version", 0)),
        "campaignId": str(item.get("campaignId", "")),
    }


def _related_rows(unit_campaign_id: str, product_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Custody and OPEN allocation rows for a product (one base-table scan-class
    query; wave 4 adds ALLOC writers)."""
    response = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc",
        ExpressionAttributeValues={":uc": unit_campaign_id},
    )
    custody_rows: List[Dict[str, Any]] = []
    allocations: List[Dict[str, Any]] = []
    for item in response.get("Items", []):
        item_key = item.get("itemKey", "")
        if item.get("productId") != product_id:
            continue
        if item_key.startswith(CUSTODY_PREFIX):
            # CUSTODY#<profileId>#<productId>: the profile segment keeps the
            # planned projection able to substitute one row's post-write value.
            custody_rows.append(
                {
                    "withScoutQty": int(item.get("withScoutQty", 0)),
                    "profileId": item_key[len(CUSTODY_PREFIX) :].rsplit("#", 1)[0],
                }
            )
        elif item_key.startswith(ALLOC_PREFIX):
            allocations.append({"remainingQty": int(item.get("remainingQty", 0)), "status": item.get("status", "")})
    return {"custody_rows": custody_rows, "allocations": allocations}


def _position(unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    balance = _read_balance(unit_campaign_id, product_id)
    related = _related_rows(unit_campaign_id, product_id)
    return cast(
        Dict[str, Any],
        derive_position(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            kernel_physical_qty=balance["kernelPhysicalQty"],
            sold_in_possession_qty=balance["soldInPossessionQty"],
            council_on_order_qty=balance["councilOnOrderQty"],
            balance_version=balance["version"],
            allocations=related["allocations"],
            custody_rows=related["custody_rows"],
        ),
    )


def _custody_projection(
    unit_campaign_id: str, profile_id: str, product_id: str, custody: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "profileId": profile_id,
        "campaignId": custody["campaignId"],
        "withScoutQty": custody["withScoutQty"],
        "version": custody["version"],
    }


# ---------------------------------------------------------------------------
# Plan builders (transaction entries)
# ---------------------------------------------------------------------------


def _balance_entry(
    unit_campaign_id: str,
    product_id: str,
    read_version: int,
    *,
    kernel_delta: int = 0,
    sold_delta: int = 0,
    council_delta: int = 0,
    stamp: str,
) -> Dict[str, Any]:
    """Conditional balance update on the version read at plan time. Callers
    validate the stock sufficiency themselves so the domain error names the
    real cause instead of a bare condition failure."""
    update_expression = "SET #productId = :pid, version = version + :one, updatedAt = :ua"
    values: Dict[str, Any] = {":pid": product_id, ":one": 1, ":ua": stamp}
    if kernel_delta:
        update_expression = "ADD kernelPhysicalQty :kd " + update_expression
        values[":kd"] = kernel_delta
    if sold_delta:
        update_expression = "ADD soldInPossessionQty :sd " + update_expression
        values[":sd"] = sold_delta
    if council_delta:
        update_expression = "ADD councilOnOrderQty :cd " + update_expression
        values[":cd"] = council_delta
    if read_version == 0:
        # Row may not exist yet: the ADD attributes self-create, and version
        # starts at 1 via if_not_exists under a not-exists condition.
        return {
            "Update": {
                "TableName": tables.inventory.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"},
                "UpdateExpression": update_expression.replace(
                    "version = version + :one", "version = if_not_exists(#version, :zero) + :one"
                ),
                "ConditionExpression": "attribute_not_exists(itemKey)",
                "ExpressionAttributeNames": {"#version": "version", "#productId": "productId"},
                "ExpressionAttributeValues": {**values, ":zero": 0},
            }
        }
    return {
        "Update": {
            "TableName": tables.inventory.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{BALANCE_PREFIX}{product_id}"},
            "UpdateExpression": update_expression,
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {"#version": "version", "#productId": "productId"},
            "ExpressionAttributeValues": {**values, ":expected": read_version},
        }
    }


def _custody_entry(
    unit_campaign_id: str,
    profile_id: str,
    product_id: str,
    custody: Dict[str, Any],
    delta: int,
    campaign_id: str,
    stamp: str,
) -> Dict[str, Any]:
    values: Dict[str, Any] = {":q": delta, ":one": 1, ":zero": 0, ":cid": campaign_id, ":ua": stamp}
    if custody["version"] == 0:
        return {
            "Update": {
                "TableName": tables.inventory.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{CUSTODY_PREFIX}{profile_id}#{product_id}"},
                "UpdateExpression": "ADD withScoutQty :q SET #productId = :pid, version = if_not_exists(#version, :zero) + :one, campaignId = :cid, updatedAt = :ua",
                "ConditionExpression": "attribute_not_exists(itemKey)",
                "ExpressionAttributeNames": {"#version": "version", "#productId": "productId"},
                "ExpressionAttributeValues": {**values, ":pid": product_id},
            }
        }
    return {
        "Update": {
            "TableName": tables.inventory.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"{CUSTODY_PREFIX}{profile_id}#{product_id}"},
            "UpdateExpression": "ADD withScoutQty :q SET #productId = :pid, version = version + :one, campaignId = :cid, updatedAt = :ua",
            "ConditionExpression": "#version = :expected AND withScoutQty >= :min",
            "ExpressionAttributeNames": {"#version": "version", "#productId": "productId"},
            "ExpressionAttributeValues": {
                **values,
                ":pid": product_id,
                ":expected": custody["version"],
                ":min": -delta if delta < 0 else 0,
            },
        }
    }


def _movement_entry(movement: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Put": {
            "TableName": tables.inventory.table_name,
            "Item": movement,
            "ConditionExpression": "attribute_not_exists(itemKey)",
        }
    }


def _movement(
    *,
    unit_campaign_id: str,
    product_id: str,
    occurred_at: str,
    movement_type: str,
    actor: str,
    inventory_version: int,
    kernel_delta: int = 0,
    sold_possession_delta: int = 0,
    with_scout_delta: int = 0,
    assigned_delta: int = 0,
    council_delta: int = 0,
    profile_id: Optional[str] = None,
    order_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    movement_id = str(uuid.uuid4())
    item: Dict[str, Any] = {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{MOVEMENT_PREFIX}{occurred_at}#{movement_id}",
        "movementId": movement_id,
        "productId": product_id,
        "movementType": movement_type,
        "kernelPhysicalDelta": kernel_delta,
        "soldPossessionDelta": sold_possession_delta,
        "withScoutDelta": with_scout_delta,
        "assignedDelta": assigned_delta,
        "councilOnOrderDelta": council_delta,
        "actorAccountId": actor,
        "occurredAt": occurred_at,
        "inventoryVersion": inventory_version,
    }
    if profile_id is not None:
        item["profileId"] = profile_id
    if order_id is not None:
        item["orderId"] = order_id
    if reason is not None:
        item["reason"] = reason
    return item


def _planned_position(
    unit_campaign_id: str,
    product_id: str,
    balance: Dict[str, Any],
    *,
    planned_profile_id: Optional[str] = None,
    planned_with_scout: Optional[int] = None,
) -> Callable[[], Dict[str, Any]]:
    """Project the position from a PLANNED balance (post-write values).

    When a custody move plans a with-Scout change, the caller passes the
    affected profile and its post-write quantity: the projection substitutes
    that row instead of reading the pre-write table state (reading here would
    pin stale custody into the committed-replay result).
    """
    related = _related_rows(unit_campaign_id, product_id)
    custody_rows = list(related["custody_rows"])
    if planned_profile_id is not None and planned_with_scout is not None:
        custody_rows = [r for r in custody_rows if r.get("profileId") != planned_profile_id]
        custody_rows.append({"withScoutQty": planned_with_scout})

    def project() -> Dict[str, Any]:
        return cast(
            Dict[str, Any],
            derive_position(
                unit_campaign_id=unit_campaign_id,
                product_id=product_id,
                kernel_physical_qty=balance["kernelPhysicalQty"],
                sold_in_possession_qty=balance["soldInPossessionQty"],
                council_on_order_qty=balance["councilOnOrderQty"],
                balance_version=balance["version"] + 1,
                allocations=related["allocations"],
                custody_rows=custody_rows,
            ),
        )

    return project


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _validate_uc_product_qty(args: Dict[str, Any]) -> tuple[str, str, int, str]:
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    product_id = require_bounded_str(args, "productId", 100)
    quantity = require_strict_int(args, "quantity")
    key = require_idempotency_key(args)
    if quantity < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")
    return unit_campaign_id, product_id, quantity, key


def _record_inventory_receipt(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id, product_id, quantity, key = _validate_uc_product_qty(args)
    occurred_at = args.get("occurredAt")
    if occurred_at is not None:
        occurred_at = require_timestamp(args, "occurredAt")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "recordInventoryReceipt")
    if replayed is not None:
        return replayed
    _require_uc_admin(unit_campaign_id, caller)

    balance = _read_balance(unit_campaign_id, product_id)
    planned = {**balance, "kernelPhysicalQty": balance["kernelPhysicalQty"] + quantity}
    project = _planned_position(unit_campaign_id, product_id, planned)

    now = _utcnow()
    stamp = occurred_at or _iso(now)
    write_stamp = _iso(now)
    update = _balance_entry(unit_campaign_id, product_id, balance["version"], kernel_delta=quantity, stamp=write_stamp)
    movement = _movement(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        occurred_at=stamp,
        movement_type="RECEIPT",
        actor=caller,
        inventory_version=balance["version"],
        kernel_delta=quantity,
    )
    marker = _marker_put(caller, "recordInventoryReceipt", key, fingerprint, project(), _epoch(now))
    plan = [update, _movement_entry(movement), marker]
    _execute_replayable(plan, marker)
    return project()


def _adjust_inventory(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    product_id = require_bounded_str(args, "productId", 100)
    delta = require_strict_int(args, "quantityDelta")
    reason = require_bounded_str(args, "reason", 200)
    key = require_idempotency_key(args)
    if delta == 0:
        raise AppError(ErrorCode.INVALID_INPUT, "quantityDelta must not be zero")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "adjustInventory")
    if replayed is not None:
        return replayed
    _require_uc_admin(unit_campaign_id, caller)

    balance = _read_balance(unit_campaign_id, product_id)
    planned_qty = balance["kernelPhysicalQty"] + delta
    if planned_qty < 0:
        raise AppError(
            ErrorCode.CONFLICT,
            "Adjustment would drive kernel physical stock negative",
            details={"reason": "INSUFFICIENT_STOCK"},
        )
    planned = {**balance, "kernelPhysicalQty": planned_qty}
    project = _planned_position(unit_campaign_id, product_id, planned)

    now = _utcnow()
    stamp = _iso(now)
    update = _balance_entry(unit_campaign_id, product_id, balance["version"], kernel_delta=delta, stamp=stamp)
    movement = _movement(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        occurred_at=stamp,
        movement_type="ADJUST",
        actor=caller,
        inventory_version=balance["version"],
        kernel_delta=delta,
        reason=reason,
    )
    marker = _marker_put(caller, "adjustInventory", key, fingerprint, project(), _epoch(now))
    plan = [update, _movement_entry(movement), marker]
    _execute_replayable(plan, marker)
    return project()


def _adjust_council_on_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    product_id = require_bounded_str(args, "productId", 100)
    delta = require_strict_int(args, "quantityDelta")
    reason = args.get("reason")
    if reason is not None:
        reason = require_bounded_str(args, "reason", 200)
    key = require_idempotency_key(args)
    if delta == 0:
        raise AppError(ErrorCode.INVALID_INPUT, "quantityDelta must not be zero")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "adjustCouncilOnOrder")
    if replayed is not None:
        return replayed
    _require_uc_admin(unit_campaign_id, caller)

    balance = _read_balance(unit_campaign_id, product_id)
    planned_qty = balance["councilOnOrderQty"] + delta
    if planned_qty < 0:
        raise AppError(
            ErrorCode.CONFLICT,
            "Adjustment would drive council-on-order negative",
            details={"reason": "INSUFFICIENT_STOCK"},
        )
    planned = {**balance, "councilOnOrderQty": planned_qty}
    project = _planned_position(unit_campaign_id, product_id, planned)

    now = _utcnow()
    stamp = _iso(now)
    update = _balance_entry(unit_campaign_id, product_id, balance["version"], council_delta=delta, stamp=stamp)
    movement = _movement(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        occurred_at=stamp,
        movement_type="COUNCIL_ADJUST",
        actor=caller,
        inventory_version=balance["version"],
        council_delta=delta,
        reason=reason,
    )
    marker = _marker_put(caller, "adjustCouncilOnOrder", key, fingerprint, project(), _epoch(now))
    plan = [update, _movement_entry(movement), marker]
    _execute_replayable(plan, marker)
    return project()


def _issue_stock_to_scout(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    campaign_id = require_bounded_str(args, "campaignId", 100)
    profile_id = require_bounded_str(args, "profileId", 100)
    product_id = require_bounded_str(args, "productId", 100)
    quantity = require_strict_int(args, "quantity")
    key = require_idempotency_key(args)
    if quantity < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "issueStockToScout")
    if replayed is not None:
        return replayed
    _require_uc_admin(unit_campaign_id, caller)

    balance = _read_balance(unit_campaign_id, product_id)
    if balance["kernelPhysicalQty"] - quantity < 0:
        raise AppError(ErrorCode.CONFLICT, "Not enough kernel stock to issue", details={"reason": "INSUFFICIENT_STOCK"})
    custody = _read_custody(unit_campaign_id, profile_id, product_id)
    planned_balance = {**balance, "kernelPhysicalQty": balance["kernelPhysicalQty"] - quantity}
    planned_custody = {
        "withScoutQty": custody["withScoutQty"] + quantity,
        "version": custody["version"] + 1,
        "campaignId": campaign_id,
    }
    project = _planned_position(
        unit_campaign_id,
        product_id,
        planned_balance,
        planned_profile_id=profile_id,
        planned_with_scout=planned_custody["withScoutQty"],
    )

    now = _utcnow()
    stamp = _iso(now)
    balance_update = _balance_entry(
        unit_campaign_id, product_id, balance["version"], kernel_delta=-quantity, stamp=stamp
    )
    custody_update = _custody_entry(unit_campaign_id, profile_id, product_id, custody, quantity, campaign_id, stamp)
    movement = _movement(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        occurred_at=stamp,
        movement_type="ISSUE",
        actor=caller,
        inventory_version=balance["version"],
        kernel_delta=-quantity,
        with_scout_delta=quantity,
        profile_id=profile_id,
    )

    def project_result() -> Dict[str, Any]:
        return {
            "inventoryPosition": project(),
            "custodyBalance": _custody_projection(unit_campaign_id, profile_id, product_id, planned_custody),
        }

    marker = _marker_put(caller, "issueStockToScout", key, fingerprint, project_result(), _epoch(now))
    plan = [balance_update, custody_update, _movement_entry(movement), marker]
    _execute_replayable(plan, marker)
    return project_result()


def _return_stock_from_scout(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    campaign_id = require_bounded_str(args, "campaignId", 100)
    profile_id = require_bounded_str(args, "profileId", 100)
    raw_items = args.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AppError(ErrorCode.INVALID_INPUT, "items must be a non-empty list")
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "items entries must be objects")
        product_id = require_bounded_str(entry, "productId", 100)
        quantity = require_strict_int(entry, "quantity")
        if quantity < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "quantity must be a positive integer")
        if product_id in seen:
            raise AppError(ErrorCode.INVALID_INPUT, "items must not repeat a productId")
        seen.add(product_id)
        items.append({"productId": product_id, "quantity": quantity})
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "returnStockFromScout")
    if replayed is not None:
        return replayed
    _require_uc_admin(unit_campaign_id, caller)

    # Read everything FIRST: every entry in the plan is conditioned on the
    # versions read here, so a racing writer cancels the whole return.
    plans: List[Dict[str, Any]] = []
    planned: Dict[str, Dict[str, Any]] = {}
    now = _utcnow()
    stamp = _iso(now)
    for item in items:
        product_id = item["productId"]
        balance = _read_balance(unit_campaign_id, product_id)
        custody = _read_custody(unit_campaign_id, profile_id, product_id)
        if custody["withScoutQty"] - item["quantity"] < 0:
            raise AppError(
                ErrorCode.CONFLICT,
                "With-Scout stock is insufficient for this return",
                details={"reason": "INSUFFICIENT_CUSTODY", "productId": product_id},
            )
        planned_balance = {**balance, "kernelPhysicalQty": balance["kernelPhysicalQty"] + item["quantity"]}
        planned_custody = {
            "withScoutQty": custody["withScoutQty"] - item["quantity"],
            "version": custody["version"] + 1,
            "campaignId": campaign_id,
        }
        planned[product_id] = {
            "balance": planned_balance,
            "custody": planned_custody,
            "project": _planned_position(
                unit_campaign_id,
                product_id,
                planned_balance,
                planned_profile_id=profile_id,
                planned_with_scout=planned_custody["withScoutQty"],
            ),
        }
        plans.append(
            _balance_entry(unit_campaign_id, product_id, balance["version"], kernel_delta=item["quantity"], stamp=stamp)
        )
        plans.append(
            _custody_entry(unit_campaign_id, profile_id, product_id, custody, -item["quantity"], campaign_id, stamp)
        )
        plans.append(
            _movement_entry(
                _movement(
                    unit_campaign_id=unit_campaign_id,
                    product_id=product_id,
                    occurred_at=stamp,
                    movement_type="RETURN",
                    actor=caller,
                    inventory_version=balance["version"],
                    kernel_delta=item["quantity"],
                    with_scout_delta=-item["quantity"],
                    profile_id=profile_id,
                )
            )
        )

    def project_result() -> Dict[str, Any]:
        return {
            "inventoryPositions": [planned[item["productId"]]["project"]() for item in items],
            "custodyBalances": [
                _custody_projection(
                    unit_campaign_id, profile_id, item["productId"], planned[item["productId"]]["custody"]
                )
                for item in items
            ],
        }

    marker = _marker_put(caller, "returnStockFromScout", key, fingerprint, project_result(), _epoch(now))
    plan = plans + [marker]
    _execute_replayable(plan, marker)
    return project_result()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "recordInventoryReceipt": _record_inventory_receipt,
    "adjustInventory": _adjust_inventory,
    "adjustCouncilOnOrder": _adjust_council_on_order,
    "issueStockToScout": _issue_stock_to_scout,
    "returnStockFromScout": _return_stock_from_scout,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch an inventory operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported inventory operation: {field_name}")
    return operation(event, context)
