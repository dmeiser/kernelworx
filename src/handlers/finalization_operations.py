"""Show & Sell finalization, reopening, and credit projections.

Spec: SHOW_SELL_DATA_MODEL §5.16-5.18, §8.7 (finalization/reopening) and
§8.10 (sizing); API §8. Normative semantics are the wave-10 review-hardened
doctrine (clean-room review docs wave-10-stage-5-backend), including:

- Union-key return baseline: the stock delta applied at every version is
  computed over the UNION of current and previous return-adjustment keys —
  `net = current.get(pid, 0) - previous.get(pid, 0)`. An omitted return
  line is a DECLARED ZERO: the transition to the zero baseline is applied
  (an omitted product releases the prior version's adjustment). The
  baseline is the newest APPROVED/SUSPENDED version regardless of
  emptiness (`{}` is a real baseline).
- Auto-reduction (ADR 0003): later-STARTING OPEN allocations reduce in
  start-time order under per-campaign cumulative-peak accounting, floored
  at soldQty + releasedQty (never negative remaining), one
  EVENT_AUTO_REDUCE movement per reduced allocation, run after the
  finalization commits (retry-convergent).
- Corrected We Owe at publication: existing obligations retarget with the
  §8.6.1 clamp (corrected = min(line weOwe, original)); the excess
  materializes as supplemental obligations.
- Reopen: SUSPENDED exact-subtraction — credits/finalization SUSPENDED,
  Scout totals subtracted exactly, approvedFinalizationId cleared,
  REOPENED; NO stock or allocation movement.
- Rounding: base shares floor to whole cents; Kernel-assigned cents must
  total the unassigned remainder exactly (the app never chooses); the
  draft persists on the event and merges when re-finalization omits it.
"""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import TransactionCancelledError, execute_transaction, tables
    from utils.errors import AppError, ErrorCode
    from utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin
except ImportError:  # pragma: no cover
    from ..utils.dynamodb import TransactionCancelledError, execute_transaction, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.unit_auth import METADATA_ITEM_KEY, require_unit_admin

from src.handlers.event_operations import _derive_status, _event_to_graphql
from src.handlers.sale_operations import (
    ALLOC_PREFIX,
    BALANCE_PREFIX,
    EVENT_PREFIX,
    MOVEMENT_PREFIX,
    SALE_PREFIX,
    WEOWE_PREFIX,
    _idempotency_begin,
    _iso,
    _load_event,
    _marker_put,
    _parse_ts,
    _require_caller,
    _require_event_admin,
    _utcnow,
)

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = None  # placeholder replaced below to keep complexity low

FINAL_PREFIX = "FINAL#"
CREDIT_PREFIX = "CREDIT#"
SIGNUP_PREFIX = "SIGNUP#"
SLOT_PREFIX = "SLOT#"
TOTAL_PREFIX = "SSTOTAL#"

FINAL_APPROVED = "APPROVED"
FINAL_SUSPENDED = "SUSPENDED"
FINAL_SUPERSEDED = "SUPERSEDED"

TRANSACTION_ACTION_LIMIT = 90

FINALIZEABLE_STATUSES = ("ENDED", "REOPENED")


def _preflight_named(action_count: int, source: str) -> None:
    """Spec 8.10 finalize-time backstop: a named CONFLICT whose message
    names the remediation — never a bare transaction-limit error. The wire
    error shape (#329) carries code + message only, so the naming lives in
    the message."""
    if action_count <= TRANSACTION_ACTION_LIMIT:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        f"OPERATION_TOO_LARGE: {source} computed a {action_count}-action finalization plan "
        f"(limit {TRANSACTION_ACTION_LIMIT}). Remediation: remove signups, zero-unconfirm work "
        "(set actualMinutes = 0), correct or void sales, reduce allocations, or split the "
        "event into smaller events, then finalize again.",
    )


def _list_event_items(unit_campaign_id: str, prefix: str) -> List[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": prefix},
    )
    items = response.get("Items", [])
    return [dict(item) for item in items]


def _active_sales(unit_campaign_id: str, show_and_sell_id: str) -> List[Dict[str, Any]]:
    return [
        item
        for item in _list_event_items(unit_campaign_id, SALE_PREFIX)
        if item.get("showAndSellId") == show_and_sell_id and item.get("status") == "ACTIVE"
    ]


def _list_inventory_items(unit_campaign_id: str, prefix: str) -> List[Dict[str, Any]]:
    response = tables.inventory.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": prefix},
    )
    return [dict(item) for item in response.get("Items", [])]


def _event_allocations(unit_campaign_id: str, show_and_sell_id: str) -> List[Dict[str, Any]]:
    # Allocations live in the INVENTORY table (ALLOC#<event>#<product>).
    return [
        item
        for item in tables.inventory.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{ALLOC_PREFIX}{show_and_sell_id}#"},
        ).get("Items", [])
        if item.get("status") != "CANCELLED"
    ]


def _event_obligations(unit_campaign_id: str, show_and_sell_id: str) -> List[Dict[str, Any]]:
    return [
        item
        for item in _list_event_items(unit_campaign_id, WEOWE_PREFIX)
        if item.get("showAndSellId") == show_and_sell_id and item.get("status") not in (FINAL_SUPERSEDED,)
    ]


def _confirmed_work(unit_campaign_id: str, show_and_sell_id: str) -> Dict[str, Dict[str, Any]]:
    """Per-profile confirmed work: {profileId: {campaignId, minutes}} from
    signups with actualMinutes > 0 on this event (a profile joins with one
    campaign; later rows extend minutes)."""
    work: Dict[str, Dict[str, Any]] = {}
    for signup in _list_event_items(unit_campaign_id, SIGNUP_PREFIX):
        if signup.get("showAndSellId") != show_and_sell_id:
            continue
        minutes = int(signup.get("actualMinutes", 0))
        if minutes <= 0:
            continue
        profile_id = signup["profileId"]
        bucket = work.setdefault(profile_id, {"campaignId": signup["campaignId"], "minutes": 0})
        bucket["minutes"] += minutes
    return work


def _cash_cents_of(sale: Dict[str, Any]) -> int:
    snapshot = sale.get("paymentMethodSnapshot") or {}
    return int(sale.get("totalCents", 0)) if snapshot.get("methodCode") == "CASH" else 0


def _compute_split(
    pool_cents: int, split_method: str, work: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    """Base shares round DOWN to whole cents (SPLIT-10); returns
    (base allocations sorted by profileId, unassigned cents)."""
    profiles = sorted(work.keys())
    if not profiles:
        return [], pool_cents
    if split_method == "TIME_WORKED":
        total_minutes = sum(entry["minutes"] for entry in work.values())
        if total_minutes <= 0:
            raise AppError(ErrorCode.CONFLICT, "Time-worked split requires confirmed minutes")
        base = [
            {
                "profileId": pid,
                "campaignId": work[pid]["campaignId"],
                "minutes": work[pid]["minutes"],
                "baseAmountCents": (pool_cents * work[pid]["minutes"]) // total_minutes,
            }
            for pid in profiles
        ]
    else:
        share = pool_cents // len(profiles)
        base = [
            {
                "profileId": pid,
                "campaignId": work[pid]["campaignId"],
                "minutes": work[pid]["minutes"],
                "baseAmountCents": share,
            }
            for pid in profiles
        ]
    assigned = sum(entry["baseAmountCents"] for entry in base)
    return base, pool_cents - assigned


def _newest_finalization(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [row for row in rows if row.get("status") in (FINAL_APPROVED, FINAL_SUSPENDED)]
    if not candidates:
        return None
    return max(candidates, key=lambda row: int(row.get("versionNumber", 0)))


def _finalizations_for(unit_campaign_id: str, show_and_sell_id: str) -> List[Dict[str, Any]]:
    return [
        item
        for item in _list_event_items(unit_campaign_id, FINAL_PREFIX)
        if item.get("showAndSellId") == show_and_sell_id
    ]


def _finalization_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "finalizationId": item["finalizationId"],
        "showAndSellId": item["showAndSellId"],
        "versionNumber": int(item.get("versionNumber", 1)),
        "status": item.get("status", FINAL_APPROVED),
        "wholePoolCents": int(item.get("wholePoolCents", 0)),
        "expectedCashCents": int(item.get("expectedCashCents", 0)),
        "actualCashCents": int(item["actualCashCents"]) if item.get("actualCashCents") is not None else None,
        "cashAdjustmentCents": int(item.get("cashAdjustmentCents", 0)),
        "cashDiscrepancyCents": int(item["cashDiscrepancyCents"])
        if item.get("cashDiscrepancyCents") is not None
        else None,
        "discrepancyExplanation": item.get("discrepancyExplanation"),
        "previousFinalizationId": item.get("previousFinalizationId"),
        "actorAccountId": item.get("actorAccountId", ""),
        "createdAt": item.get("createdAt", ""),
    }


def _credit_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "allocationId": item["allocationId"],
        "finalizationId": item["finalizationId"],
        "showAndSellId": item["showAndSellId"],
        "unitCampaignId": item["unitCampaignId"],
        "campaignId": item["campaignId"],
        "profileId": item["profileId"],
        "amountCents": int(item.get("amountCents", 0)),
        "status": item.get("status", FINAL_APPROVED),
        "createdAt": item.get("createdAt", ""),
        "suspendedAt": item.get("suspendedAt"),
    }


def _movement_entry(
    unit_campaign_id: str, product_id: str, movement_type: str, quantity: int, actor: str, stamp: str
) -> Dict[str, Any]:
    movement_id = str(uuid.uuid4())
    return {
        "Put": {
            "TableName": tables.inventory.table_name,
            "Item": {
                "unitCampaignId": unit_campaign_id,
                "itemKey": f"{MOVEMENT_PREFIX}{movement_id}",
                "movementId": movement_id,
                "productId": product_id,
                "movementType": movement_type,
                "quantity": quantity,
                "actorAccountId": actor,
                "showAndSellId": None,
                "createdAt": stamp,
            },
        }
    }


def _balance_update(unit_campaign_id: str, balance: Dict[str, Any], delta: int, stamp: str) -> Dict[str, Any]:
    new_qty = int(balance.get("kernelPhysicalQty", 0)) + delta
    if new_qty < 0:
        raise AppError(
            ErrorCode.CONFLICT,
            "Re-finalization would drive kernel stock negative; reconcile the return "
            "quantities against current stock before finalizing.",
            details={"reason": "INSUFFICIENT_STOCK", "productId": balance.get("productId", "")},
        )
    return {
        "Update": {
            "TableName": tables.inventory.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": balance["itemKey"]},
            "UpdateExpression": "SET #qty = :qty, #version = :next, #updatedAt = :ua",
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#qty": "kernelPhysicalQty",
                "#version": "version",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":qty": new_qty,
                ":next": int(balance.get("version", 0)) + 1,
                ":ua": stamp,
                ":expected": int(balance.get("version", 0)),
            },
        }
    }


def _total_item_key(campaign_id: str) -> str:
    return f"{TOTAL_PREFIX}{campaign_id}"


def _totals_for(unit_campaign_id: str, campaign_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    totals: Dict[str, Dict[str, Any]] = {}
    for campaign_id in campaign_ids:
        item = tables.unit_campaigns.get_item(
            Key={"unitCampaignId": unit_campaign_id, "itemKey": _total_item_key(campaign_id)},
            ConsistentRead=True,
        ).get("Item")
        totals[campaign_id] = dict(item) if isinstance(item, dict) else {"version": 0, "approvedAmountCents": 0}
    return totals


def _total_apply_entry(
    unit_campaign_id: str, campaign_id: str, profile_id: str, signed_delta_cents: int, stamp: str
) -> Dict[str, Any]:
    current = _totals_for(unit_campaign_id, [campaign_id])[campaign_id]
    new_total = int(current.get("approvedAmountCents", 0)) + signed_delta_cents
    if new_total < 0:  # exact-subtraction doctrine: never below zero
        raise AppError(
            ErrorCode.CONFLICT, "Scout total projection would go negative", details={"reason": "TOTAL_UNDERFLOW"}
        )
    return {
        "Update": {
            "TableName": tables.unit_campaigns.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": _total_item_key(campaign_id)},
            "UpdateExpression": "SET #amount = :amount, #version = :next, #profileId = :pid, #updatedAt = :ua",
            # Creation-tolerant: the first credit for a Campaign has no
            # row yet (version 0 expected on a missing attribute).
            "ConditionExpression": "attribute_not_exists(#version) OR #version = :expected",
            "ExpressionAttributeNames": {
                "#amount": "approvedAmountCents",
                "#version": "version",
                "#profileId": "profileId",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":amount": new_total,
                ":next": int(current.get("version", 0)) + 1,
                ":pid": profile_id,
                ":ua": stamp,
                ":expected": int(current.get("version", 0)),
            },
        }
    }


# ---------------------------------------------------------------------------
# Preview + rounding draft
# ---------------------------------------------------------------------------


def _preview_payload(current: Dict[str, Any]) -> Dict[str, Any]:
    unit_campaign_id = current["unitCampaignId"]
    show_and_sell_id = current["showAndSellId"]
    sales = _active_sales(unit_campaign_id, show_and_sell_id)
    pool = sum(int(sale.get("totalCents", 0)) for sale in sales)
    work = _confirmed_work(unit_campaign_id, show_and_sell_id)
    rich_base, unassigned = _compute_split(pool, current.get("splitMethod", "EQUAL"), work)
    base = [{"profileId": entry["profileId"], "baseAmountCents": entry["baseAmountCents"]} for entry in rich_base]
    expected_cash = sum(_cash_cents_of(sale) for sale in sales)
    issues: List[Dict[str, Any]] = []
    if unassigned > 0:
        issues.append(
            {
                "code": "UNASSIGNED_CENTS",
                "message": f"{unassigned} cent(s) unassigned: assign every cent to a confirmed Scout before approval.",
                "unassignedCents": unassigned,
            }
        )
    return {
        "wholePoolCents": pool,
        "baseAllocations": base,
        "unassignedCents": unassigned,
        "expectedCashCents": expected_cash,
        "cashDiscrepancyCents": None,
        "issues": issues,
        "eventVersion": int(current.get("version", 0)),
    }


def _preview(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    payload = _preview_payload(current)
    adjustment = args.get("cashAdjustmentCents")
    actual = args.get("actualCashCents")
    if isinstance(adjustment, int) and not isinstance(adjustment, bool):
        payload["expectedCashCents"] = payload["expectedCashCents"] + adjustment
    if isinstance(actual, int) and not isinstance(actual, bool):
        payload["cashDiscrepancyCents"] = actual - payload["expectedCashCents"]
    return payload


def _validate_draft_entry(entry: Any, eligible: set[str], seen: set[str]) -> Tuple[str, int]:
    if not isinstance(entry, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "each draft entry must be an object")
    profile_id = entry.get("profileId")
    cents = entry.get("cents")
    if not isinstance(profile_id, str) or profile_id not in eligible:
        raise AppError(ErrorCode.INVALID_INPUT, "Rounding draft entries must name confirmed participants")
    if profile_id in seen:
        raise AppError(ErrorCode.INVALID_INPUT, "Rounding draft entries must be unique per Scout")
    cents_int = _integral_cents(cents)
    seen.add(profile_id)
    return profile_id, cents_int


def _normalize_draft(raw_draft: Any, preview: Dict[str, Any]) -> List[Dict[str, Any]]:
    eligible = {entry["profileId"] for entry in preview["baseAllocations"]}
    seen: set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for entry in raw_draft:
        profile_id, cents = _validate_draft_entry(entry, eligible, seen)
        normalized.append({"profileId": profile_id, "cents": cents})
    if sum(entry["cents"] for entry in normalized) > preview["unassignedCents"]:
        raise AppError(ErrorCode.INVALID_INPUT, "Rounding draft cannot exceed the unassigned cents")
    return normalized


def _draft_commit(
    current: Dict[str, Any],
    normalized: List[Dict[str, Any]],
    expected_version: int,
    caller: str,
    key: str,
    fingerprint: str,
) -> Dict[str, Any]:
    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = [
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": current["itemKey"]},
                "UpdateExpression": "SET #draft = :draft, #version = :next, #updatedAt = :ua",
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": {
                    "#draft": "roundingDraft",
                    "#version": "version",
                    "#updatedAt": "updatedAt",
                },
                "ExpressionAttributeValues": {
                    ":draft": normalized,
                    ":next": expected_version + 1,
                    ":ua": stamp,
                    ":expected": expected_version,
                },
            }
        }
    ]
    updated = dict(current)
    updated["roundingDraft"] = normalized
    updated["version"] = expected_version + 1
    updated["updatedAt"] = stamp
    result = _event_to_graphql(updated, now, include_slots=False)
    marker = _marker_put(caller, "updateShowAndSellRoundingDraft", key, fingerprint, result, int(now.timestamp()))
    plan.append(marker)
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        ) from None
    return result


def _draft_args(args: Dict[str, Any]) -> Tuple[str, int, Any, str]:
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    expected_version = args.get("expectedVersion")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedVersion must be a positive integer")
    raw_draft = args.get("draft")
    if not isinstance(raw_draft, list):
        raise AppError(ErrorCode.INVALID_INPUT, "draft must be a list of rounding assignments")
    key = args.get("idempotencyKey")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'idempotencyKey' must be between 8 and 128 characters")
    return show_and_sell_id, expected_version, raw_draft, key


def _update_rounding_draft(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id, expected_version, raw_draft, key = _draft_args(args)

    caller, _fingerprint_value, replayed = _idempotency_begin(event, args, "updateShowAndSellRoundingDraft")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if current.get("status") == "CANCELLED":
        raise AppError(
            ErrorCode.CONFLICT, "A cancelled event cannot hold a rounding draft", details={"reason": "ACTIVE_GUARD"}
        )

    # Validation against the CURRENT preview (unique eligible confirmed
    # participants, integer cents >= 0, sum <= unassigned cents).
    preview = _preview_payload(current)
    normalized = _normalize_draft(raw_draft, preview)

    return _draft_commit(current, normalized, expected_version, caller, key, _fingerprint_value)


# ---------------------------------------------------------------------------
# finalizeShowAndSell (spec 8.7 versioned publication)
# ---------------------------------------------------------------------------


def _require_int(value: Any, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must be an integer")


def _validate_cash_inputs(args: Dict[str, Any], calculated_expected: int) -> Dict[str, Any]:
    adjustment = args.get("cashAdjustmentCents")
    adjustment_reason = args.get("cashAdjustmentReason")
    actual = args.get("actualCashCents")
    explanation = args.get("discrepancyExplanation")
    if adjustment is None:
        adjustment = 0
    _require_int(adjustment, "cashAdjustmentCents")
    if adjustment != 0 and not isinstance(adjustment_reason, str):
        raise AppError(ErrorCode.INVALID_INPUT, "cashAdjustmentReason is required for a nonzero adjustment")
    if actual is not None:
        _require_int(actual, "actualCashCents")
    adjusted = calculated_expected + adjustment
    discrepancy = None
    if actual is not None:
        discrepancy = actual - adjusted
        if discrepancy != 0 and not isinstance(explanation, str):
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "discrepancyExplanation is required when actual cash differs from the adjusted expectation",
            )
    return {
        "adjustment": adjustment,
        "adjustmentReason": adjustment_reason if adjustment != 0 else None,
        "actual": actual,
        "adjustedExpected": adjusted,
        "discrepancy": discrepancy,
        "explanation": explanation if discrepancy else None,
    }


def _non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must be a non-negative integer")
    return value


def _validate_return_line(line: Any) -> Tuple[str, Dict[str, Any]]:
    if not isinstance(line, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "each return line must be an object")
    product_id = line.get("productId")
    if not isinstance(product_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "each return line needs a productId")
    expected = _non_negative_int(line.get("expectedQty"), f"expectedQty for {product_id}")
    actual = _non_negative_int(line.get("actualQty"), f"actualQty for {product_id}")
    reason = line.get("reason")
    if actual != expected and not isinstance(reason, str):
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"A return variance for {product_id} needs a reason (stock-only adjustment)",
        )
    return product_id, {"expectedQty": expected, "actualQty": actual, "reason": reason}


def _normalize_return_lines(raw_lines: Any, allocations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return lines keyed by product. Omission is a DECLARED ZERO (the
    union-key doctrine): every omitted allocated product participates in
    the union with an adjustment of zero."""
    by_product = {_split_alloc_product(alloc): alloc for alloc in allocations}
    normalized: Dict[str, Dict[str, Any]] = {}
    if raw_lines is None:
        raw_lines = []
    if not isinstance(raw_lines, list):
        raise AppError(ErrorCode.INVALID_INPUT, "returnLines must be a list")
    for line in raw_lines:
        product_id, parsed = _validate_return_line(line)
        if product_id in normalized:
            raise AppError(ErrorCode.INVALID_INPUT, f"Duplicate return line for {product_id}")
        normalized[product_id] = parsed
    for product_id in by_product:
        normalized.setdefault(product_id, {"expectedQty": 0, "actualQty": 0, "reason": None})
    return normalized


def _split_alloc_product(alloc: Dict[str, Any]) -> str:
    return str(alloc.get("productId") or alloc["itemKey"].rsplit("#", 1)[-1])


def _integral_cents(value: Any) -> int:
    """Integer cents on the wire OR reloaded from DynamoDB (Decimal)."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise AppError(ErrorCode.INVALID_INPUT, "Rounding cents must be a non-negative integer")
    cents = int(value)
    if cents != value or cents < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "Rounding cents must be a non-negative integer")
    return cents


def _normalize_rounding_entries(source: Any, base_by_profile: Dict[str, int]) -> List[Dict[str, Any]]:
    if not isinstance(source, list):
        raise AppError(ErrorCode.INVALID_INPUT, "roundingAssignments must be a list")
    eligible = set(base_by_profile.keys())
    seen: set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for entry in source:
        if not isinstance(entry, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "each rounding assignment must be an object")
        profile_id = entry.get("profileId")
        cents = entry.get("cents")
        if not isinstance(profile_id, str) or profile_id not in eligible:
            raise AppError(ErrorCode.INVALID_INPUT, "Rounding assignments must name confirmed participants")
        if profile_id in seen:
            raise AppError(ErrorCode.INVALID_INPUT, "Rounding assignments must be unique per Scout")
        cents_int = _integral_cents(cents)
        seen.add(profile_id)
        normalized.append({"profileId": profile_id, "cents": cents_int})
    return normalized


def _validate_rounding(
    raw_assignments: Any,
    stored_draft: Any,
    preview: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """The app never chooses: caller assignments (or the persisted draft
    when omitted) must name unique confirmed participants, use integer
    cents >= 0, and total the unassigned cents EXACTLY."""
    source = raw_assignments if raw_assignments is not None else stored_draft
    if source is None:
        source = []
    base_by_profile = {entry["profileId"]: entry["baseAmountCents"] for entry in preview["baseAllocations"]}
    campaign_by_profile = {entry["profileId"]: entry["campaignId"] for entry in preview["baseAllocations"]}
    minutes_by_profile = {entry["profileId"]: entry.get("minutes", 0) for entry in preview["baseAllocations"]}
    normalized = _normalize_rounding_entries(source, base_by_profile)
    total_rounding = sum(entry["cents"] for entry in normalized)
    if total_rounding != preview["unassignedCents"]:
        raise AppError(
            ErrorCode.CONFLICT,
            f"Rounding assignments total {total_rounding} cents but {preview['unassignedCents']} "
            "cent(s) remain unassigned; assign every cent before approval.",
            details={"reason": "UNASSIGNED_CENTS", "unassignedCents": preview["unassignedCents"]},
        )
    rounding_by_profile = {entry["profileId"]: entry["cents"] for entry in normalized}
    # Every confirmed participant receives a credit (rounding 0 when the
    # Kernel assigned none); base + rounding == pool exactly.
    return [
        {
            "profileId": profile_id,
            "campaignId": campaign_by_profile[profile_id],
            "minutes": minutes_by_profile[profile_id],
            "baseAmountCents": base_by_profile[profile_id],
            "roundingCents": rounding_by_profile.get(profile_id, 0),
            "amountCents": base_by_profile[profile_id] + rounding_by_profile.get(profile_id, 0),
        }
        for profile_id in sorted(base_by_profile.keys())
    ]


def _release_entries(
    allocations: List[Dict[str, Any]],
    unit_campaign_id: str,
    actor: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """First-finalization release: OPEN allocations become RELEASED with
    remaining moved into releasedQty. Re-finalization skips rows already
    released (prior releases are never replayed)."""
    entries: List[Dict[str, Any]] = []
    for alloc in allocations:
        if alloc.get("status") == "RELEASED":
            continue
        remaining = int(alloc.get("remainingQty", 0))
        product_id = _split_alloc_product(alloc)
        new_released = int(alloc.get("releasedQty", 0)) + remaining
        entries.append(
            {
                "Update": {
                    "TableName": tables.inventory.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": alloc["itemKey"]},
                    "UpdateExpression": "SET #status = :status, #released = :released, #remaining = :zero, #version = :next, #updatedAt = :ua",
                    "ConditionExpression": "#version = :expected",
                    "ExpressionAttributeNames": {
                        "#status": "status",
                        "#released": "releasedQty",
                        "#remaining": "remainingQty",
                        "#version": "version",
                        "#updatedAt": "updatedAt",
                    },
                    "ExpressionAttributeValues": {
                        ":status": "RELEASED",
                        ":released": new_released,
                        ":zero": 0,
                        ":next": int(alloc.get("version", 0)) + 1,
                        ":ua": stamp,
                        ":expected": int(alloc.get("version", 0)),
                    },
                }
            }
        )
        if remaining:
            entries.append(_movement_entry(unit_campaign_id, product_id, "EVENT_RELEASE", remaining, actor, stamp))
    return entries


def _stock_delta_entries(
    current_adjustments: Dict[str, int],
    previous_adjustments: Dict[str, int],
    balances: Dict[str, Dict[str, Any]],
    unit_campaign_id: str,
    actor: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """The union-key return baseline (W10 review doctrine): the delta
    applied now is `current - previous` over the UNION of keys. An omitted
    line is a declared zero — the transition to (or from) zero is applied,
    and an unchanged line nets exactly zero. A negative delta the current
    stock cannot satisfy fails for Kernel reconciliation."""
    entries: List[Dict[str, Any]] = []
    for product_id in sorted(set(current_adjustments) | set(previous_adjustments)):
        delta = current_adjustments.get(product_id, 0) - previous_adjustments.get(product_id, 0)
        if delta == 0:
            continue
        balance = balances.get(product_id)
        if not isinstance(balance, dict):
            raise AppError(
                ErrorCode.CONFLICT,
                f"Return reconciliation names {product_id} but the Unit Campaign has no balance row",
                details={"reason": "UNKNOWN_PRODUCT", "productId": product_id},
            )
        entries.append(_balance_update(unit_campaign_id, balance, delta, stamp))
        entries.append(_movement_entry(unit_campaign_id, product_id, "EVENT_RETURN_RECONCILE", delta, actor, stamp))
    return entries


def _supplemental_obligation(
    sale: Dict[str, Any], line: Dict[str, Any], quantity: int, unit_campaign_id: str, stamp: str
) -> Dict[str, Any]:
    we_owe_id = str(uuid.uuid4())
    return {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{WEOWE_PREFIX}{we_owe_id}",
        "weOweId": we_owe_id,
        "saleId": sale["saleId"],
        "showAndSellId": sale["showAndSellId"],
        "lineItemId": line.get("lineItemId"),
        "buyerName": sale.get("buyerName", ""),
        "productId": line.get("productId"),
        "productNameSnapshot": line.get("productNameSnapshot", ""),
        "originalQty": quantity,
        "fulfilledQty": 0,
        "cancelledQty": 0,
        "reservedQty": 0,
        "remainingQty": quantity,
        "uncoveredQty": quantity,
        "status": "OPEN",
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
    }


def _obligation_retarget_entry(
    row: Dict[str, Any], take: int, unit_campaign_id: str, stamp: str
) -> Optional[Dict[str, Any]]:
    original = int(row.get("originalQty", 0))
    fulfilled = int(row.get("fulfilledQty", 0))
    target = max(take, fulfilled)  # never below the fulfilled floor
    outstanding = max(target - fulfilled, 0)
    current_outstanding = original - fulfilled - int(row.get("cancelledQty", 0))
    if outstanding == current_outstanding:
        return None
    cancelled = original - fulfilled - outstanding
    remaining = max(original - fulfilled - cancelled, 0)
    status = "OPEN" if remaining > 0 else ("FULFILLED" if fulfilled > 0 else "CLOSED")
    return {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": row["itemKey"]},
            "UpdateExpression": (
                "SET #cancelled = :cancelled, #remaining = :remaining, #status = :status, "
                "#version = :next, #updatedAt = :ua"
            ),
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#cancelled": "cancelledQty",
                "#remaining": "remainingQty",
                "#status": "status",
                "#version": "version",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":cancelled": cancelled,
                ":remaining": remaining,
                ":status": status,
                ":next": int(row.get("version", 0)) + 1,
                ":ua": stamp,
                ":expected": int(row.get("version", 0)),
            },
        }
    }


def _publish_one_line(
    sale: Dict[str, Any],
    line: Dict[str, Any],
    rows: List[Dict[str, Any]],
    unit_campaign_id: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    corrected = int(line.get("weOweQty", 0))
    ordered = sorted(rows, key=lambda row: row.get("createdAt", ""))
    if not ordered:
        if corrected <= 0:
            return []
        return [
            {
                "Put": {
                    "TableName": tables.show_and_sells.table_name,
                    "Item": _supplemental_obligation(sale, line, corrected, unit_campaign_id, stamp),
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            }
        ]
    entries: List[Dict[str, Any]] = []
    excess = max(0, corrected - sum(int(row.get("originalQty", 0)) for row in ordered))
    running_target = corrected - excess
    for row in ordered:
        take = min(int(row.get("originalQty", 0)), max(running_target, 0))
        running_target -= take
        entry = _obligation_retarget_entry(row, take, unit_campaign_id, stamp)
        if entry is not None:
            entries.append(entry)
    if excess > 0:
        entries.append(
            {
                "Put": {
                    "TableName": tables.show_and_sells.table_name,
                    "Item": _supplemental_obligation(sale, line, excess, unit_campaign_id, stamp),
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            }
        )
    return entries


def _obligation_publish_entries(
    obligations: List[Dict[str, Any]],
    sales: List[Dict[str, Any]],
    unit_campaign_id: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """Re-finalization obligation publication (W10-H3 doctrine): retarget
    each obligation to its sale line's current We Owe quantity with the
    §8.6.1 clamp (existing rows never exceed their original), and
    materialize the excess as supplemental obligation rows. Idempotent: a
    consistent set produces no writes."""
    entries: List[Dict[str, Any]] = []
    lines_by_id: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    for sale in sales:
        for line in sale.get("lineItems", []):
            lines_by_id[str(line.get("lineItemId"))] = (sale, line)
    by_line: Dict[str, List[Dict[str, Any]]] = {}
    for obligation in obligations:
        by_line.setdefault(str(obligation.get("lineItemId")), []).append(obligation)
    for line_item_id, (sale, line) in lines_by_id.items():
        entries.extend(_publish_one_line(sale, line, by_line.get(line_item_id, []), unit_campaign_id, stamp))
    return entries


def _credit_plan_entries(
    assignments: List[Dict[str, Any]],
    finalization_id: str,
    show_and_sell_id: str,
    unit_campaign_id: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    """Credit records + totals projections (exact addition)."""
    plan: List[Dict[str, Any]] = []
    for assignment in assignments:
        credit_item = {
            "unitCampaignId": unit_campaign_id,
            "itemKey": f"{CREDIT_PREFIX}{finalization_id}#{assignment['profileId']}",
            "allocationId": str(uuid.uuid4()),
            "finalizationId": finalization_id,
            "showAndSellId": show_and_sell_id,
            "campaignId": assignment["campaignId"],
            "profileId": assignment["profileId"],
            "baseAmountCents": assignment["baseAmountCents"],
            "roundingCents": assignment["roundingCents"],
            "amountCents": assignment["amountCents"],
            "minutesConfirmed": assignment.get("minutes", 0),
            "status": FINAL_APPROVED,
            "version": 1,
            "createdAt": stamp,
        }
        plan.append(
            {
                "Put": {
                    "TableName": tables.show_and_sells.table_name,
                    "Item": credit_item,
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            }
        )
        plan.append(
            _total_apply_entry(
                unit_campaign_id, assignment["campaignId"], assignment["profileId"], assignment["amountCents"], stamp
            )
        )
    return plan


def _supersede_entries(previous: Dict[str, Any], unit_campaign_id: str, stamp: str) -> List[Dict[str, Any]]:
    """The re-finalization chain: the SUSPENDED prior version and its
    credits become SUPERSEDED in the same publication transaction."""
    entries: List[Dict[str, Any]] = [
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": previous["itemKey"]},
                "UpdateExpression": "SET #status = :status, #updatedAt = :ua",
                "ConditionExpression": "#status = :suspended",
                "ExpressionAttributeNames": {"#status": "status", "#updatedAt": "updatedAt"},
                "ExpressionAttributeValues": {
                    ":status": FINAL_SUPERSEDED,
                    ":suspended": FINAL_SUSPENDED,
                    ":ua": stamp,
                },
            }
        }
    ]
    for credit in _list_event_items(unit_campaign_id, f"{CREDIT_PREFIX}{previous['finalizationId']}#"):
        entries.append(
            {
                "Update": {
                    "TableName": tables.show_and_sells.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": credit["itemKey"]},
                    "UpdateExpression": "SET #status = :status, #updatedAt = :ua",
                    "ConditionExpression": "#status = :suspended",
                    "ExpressionAttributeNames": {"#status": "status", "#updatedAt": "updatedAt"},
                    "ExpressionAttributeValues": {
                        ":status": FINAL_SUPERSEDED,
                        ":suspended": FINAL_SUSPENDED,
                        ":ua": stamp,
                    },
                },
            }
        )
    return entries


def _require_finalizeable(current: Dict[str, Any], expected_version: int) -> None:
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    # ACTIVE/ENDED are time-derived (never stored); FINALIZED/REOPENED/
    # CANCELLED are stored. Finalization is allowed once the event has
    # ended (or was reopened after a prior finalization).
    derived = _derive_status(current, _utcnow())
    if derived not in FINALIZEABLE_STATUSES:
        raise AppError(
            ErrorCode.CONFLICT,
            f"Only ENDED or REOPENED events can be finalized (current status: {derived})",
            details={"reason": "ACTIVE_GUARD"},
        )


def _finalize_args(args: Dict[str, Any]) -> Tuple[str, int, str]:
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    expected_version = args.get("expectedVersion")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedVersion must be a positive integer")
    key = args.get("idempotencyKey")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'idempotencyKey' must be between 8 and 128 characters")
    return show_and_sell_id, expected_version, key


def _finalization_version_item(
    current: Dict[str, Any],
    sales: List[Dict[str, Any]],
    work: Dict[str, Dict[str, Any]],
    assignments: List[Dict[str, Any]],
    cash: Dict[str, Any],
    current_adjustments: Dict[str, int],
    finalization_id: str,
    show_and_sell_id: str,
    version_number: int,
    previous: Optional[Dict[str, Any]],
    caller: str,
    expected_version: int,
    stamp: str,
    unit_campaign_id: str,
) -> Dict[str, Any]:
    """The immutable version row — snapshots included; adjustments stored
    even when {} so the next baseline is well-defined."""
    return {
        "unitCampaignId": unit_campaign_id,
        "itemKey": f"{FINAL_PREFIX}{finalization_id}",
        "finalizationId": finalization_id,
        "showAndSellId": show_and_sell_id,
        "versionNumber": version_number,
        "status": FINAL_APPROVED,
        "wholePoolCents": sum(int(sale.get("totalCents", 0)) for sale in sales),
        "splitMethod": current.get("splitMethod", "EQUAL"),
        "expectedCashCents": cash["adjustedExpected"],
        "actualCashCents": cash["actual"],
        "cashAdjustmentCents": cash["adjustment"],
        "cashDiscrepancyCents": cash["discrepancy"],
        "discrepancyExplanation": cash["explanation"],
        "returnAdjustmentsByProduct": current_adjustments,
        "saleSnapshots": [
            {
                "saleId": sale["saleId"],
                "revision": int(sale.get("revision", 1)),
                "totalCents": int(sale.get("totalCents", 0)),
            }
            for sale in sales
        ],
        "workSnapshots": [
            {"profileId": pid, "campaignId": entry["campaignId"], "actualMinutes": entry["minutes"]}
            for pid, entry in sorted(work.items())
        ],
        "roundingDraft": [{"profileId": entry["profileId"], "cents": entry["roundingCents"]} for entry in assignments],
        "previousFinalizationId": previous["finalizationId"] if previous else None,
        "actorAccountId": caller,
        "sourceEventVersion": expected_version,
        "createdAt": stamp,
    }


def _finalize_transition_entry(
    current: Dict[str, Any],
    assignments: List[Dict[str, Any]],
    finalization_id: str,
    expected_version: int,
    caller: str,
    stamp: str,
) -> Dict[str, Any]:
    return {
        "Update": {
            "TableName": tables.show_and_sells.table_name,
            "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": current["itemKey"]},
            "UpdateExpression": (
                "SET #status = :status, #approved = :fid, #draft = :draft, "
                "#version = :next, #updatedAt = :ua, #updatedByAccountId = :ub"
            ),
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#status": "status",
                "#approved": "approvedFinalizationId",
                "#draft": "roundingDraft",
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":status": "FINALIZED",
                ":fid": finalization_id,
                ":draft": [{"profileId": entry["profileId"], "cents": entry["roundingCents"]} for entry in assignments],
                ":next": expected_version + 1,
                ":ua": stamp,
                ":ub": caller,
                ":expected": expected_version,
            },
        }
    }


def _finalize_result(
    finalization_item: Dict[str, Any],
    assignments: List[Dict[str, Any]],
    finalization_id: str,
    show_and_sell_id: str,
    unit_campaign_id: str,
    stamp: str,
) -> Dict[str, Any]:
    return {
        "finalization": _finalization_to_graphql(finalization_item),
        "scoutAllocations": [
            {
                "allocationId": str(uuid.uuid4()),
                "finalizationId": finalization_id,
                "showAndSellId": show_and_sell_id,
                "unitCampaignId": unit_campaign_id,
                "campaignId": entry["campaignId"],
                "profileId": entry["profileId"],
                "amountCents": entry["amountCents"],
                "status": FINAL_APPROVED,
                "createdAt": stamp,
                "suspendedAt": None,
            }
            for entry in assignments
        ],
        "laterAllocationWarnings": [],
    }


def _finalize_sources(
    unit_campaign_id: str, show_and_sell_id: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    sales = _active_sales(unit_campaign_id, show_and_sell_id)
    allocations = _event_allocations(unit_campaign_id, show_and_sell_id)
    obligations = _event_obligations(unit_campaign_id, show_and_sell_id)
    previous = _newest_finalization(_finalizations_for(unit_campaign_id, show_and_sell_id))
    return sales, allocations, obligations, previous


def _balance_map(unit_campaign_id: str) -> Dict[str, Dict[str, Any]]:
    return {
        row["productId"]: row
        for row in tables.inventory.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{BALANCE_PREFIX}"},
        ).get("Items", [])
    }


def _previous_adjustments(previous: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if previous is None:
        return {}
    return {str(pid): int(delta) for pid, delta in (previous.get("returnAdjustmentsByProduct") or {}).items()}


def _finalize_event(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id, expected_version, key = _finalize_args(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "finalizeShowAndSell")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    _require_finalizeable(current, expected_version)

    unit_campaign_id = current["unitCampaignId"]
    sales, allocations, obligations, previous = _finalize_sources(unit_campaign_id, show_and_sell_id)

    # Pool / split / rounding (the app never chooses: unassigned cents
    # block approval, named in the error).
    work = _confirmed_work(unit_campaign_id, show_and_sell_id)
    pool = sum(int(sale.get("totalCents", 0)) for sale in sales)
    rich_base, unassigned = _compute_split(pool, current.get("splitMethod", "EQUAL"), work)
    preview = {
        "baseAllocations": rich_base,
        "unassignedCents": unassigned,
    }
    assignments = _validate_rounding(args.get("roundingAssignments"), current.get("roundingDraft"), preview)

    # Cash.
    calculated_cash = sum(_cash_cents_of(sale) for sale in sales)
    cash = _validate_cash_inputs(args, calculated_cash)

    now = _utcnow()
    stamp = _iso(now)
    finalization_id = str(uuid.uuid4())
    version_number = (int(previous["versionNumber"]) if previous else 0) + 1
    plan: List[Dict[str, Any]] = _credit_plan_entries(
        assignments, finalization_id, show_and_sell_id, unit_campaign_id, stamp
    )

    # Returns: omission is a declared zero; the version's own adjustment
    # map is stored even when empty ({} is a real baseline).
    return_lines = _normalize_return_lines(args.get("returnLines"), allocations)
    current_adjustments = {pid: line["actualQty"] - line["expectedQty"] for pid, line in return_lines.items()}

    balances = _balance_map(unit_campaign_id)
    previous_adjustments = _previous_adjustments(previous)

    if previous is not None:
        plan.extend(_supersede_entries(previous, unit_campaign_id, stamp))
    # Allocation releases (first finalization only; never replayed).
    plan.extend(_release_entries(allocations, unit_campaign_id, caller, stamp))
    # Union-key stock deltas.
    plan.extend(
        _stock_delta_entries(current_adjustments, previous_adjustments, balances, unit_campaign_id, caller, stamp)
    )
    # Obligation publication (clamp + supplemental; idempotent).
    plan.extend(_obligation_publish_entries(obligations, sales, unit_campaign_id, stamp))
    # The immutable version row — snapshots included; adjustments stored
    # even when {} so the next baseline is well-defined.
    finalization_item = _finalization_version_item(
        current,
        sales,
        work,
        assignments,
        cash,
        current_adjustments,
        finalization_id,
        show_and_sell_id,
        version_number,
        previous,
        caller,
        expected_version,
        stamp,
        unit_campaign_id,
    )
    plan.append(
        {
            "Put": {
                "TableName": tables.show_and_sells.table_name,
                "Item": finalization_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        }
    )
    # Event transition: FINALIZED + persisted rounding draft + version bump.
    plan.append(_finalize_transition_entry(current, assignments, finalization_id, expected_version, caller, stamp))

    result = _finalize_result(
        finalization_item, assignments, finalization_id, show_and_sell_id, unit_campaign_id, stamp
    )
    marker = _marker_put(caller, "finalizeShowAndSell", key, fingerprint, result, int(now.timestamp()))
    plan.append(marker)

    _preflight_named(len(plan), "finalizeShowAndSell")
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT,
            "A source record changed during finalization; re-read the event and finalize again",
            details={"reason": "VERSION_MISMATCH"},
        ) from None

    warnings = _auto_reduce_later_events(current, caller, stamp)
    result["laterAllocationWarnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# reopenShowAndSell (spec 8.7: suspension; no stock movement)
# ---------------------------------------------------------------------------


def _suspension_entries(credits: List[Dict[str, Any]], unit_campaign_id: str, stamp: str) -> List[Dict[str, Any]]:
    """SUSPENDED exact-subtraction: totals subtract each credit exactly
    (never below zero); credits and the version row suspend together."""
    plan: List[Dict[str, Any]] = []
    for credit in credits:
        plan.append(
            _total_apply_entry(
                unit_campaign_id, credit["campaignId"], credit["profileId"], -int(credit["amountCents"]), stamp
            )
        )
        plan.append(
            {
                "Update": {
                    "TableName": tables.show_and_sells.table_name,
                    "Key": {"unitCampaignId": unit_campaign_id, "itemKey": credit["itemKey"]},
                    "UpdateExpression": "SET #status = :status, #suspendedAt = :sa, #updatedAt = :ua",
                    "ConditionExpression": "#status = :approved",
                    "ExpressionAttributeNames": {
                        "#status": "status",
                        "#suspendedAt": "suspendedAt",
                        "#updatedAt": "updatedAt",
                    },
                    "ExpressionAttributeValues": {
                        ":status": FINAL_SUSPENDED,
                        ":approved": FINAL_APPROVED,
                        ":sa": stamp,
                        ":ua": stamp,
                    },
                },
            }
        )
    return plan


def _reopen_targets(
    current: Dict[str, Any], show_and_sell_id: str, unit_campaign_id: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if current.get("status") != "FINALIZED":
        raise AppError(
            ErrorCode.CONFLICT,
            f"Only FINALIZED events can be reopened (current status: {current.get('status')})",
            details={"reason": "ACTIVE_GUARD"},
        )
    finalization_id = current.get("approvedFinalizationId")
    if not isinstance(finalization_id, str) or not finalization_id:
        raise AppError(ErrorCode.CONFLICT, "The event has no approved finalization to suspend")
    rows = _finalizations_for(unit_campaign_id, show_and_sell_id)
    approved = next(
        (row for row in rows if row.get("finalizationId") == finalization_id and row.get("status") == FINAL_APPROVED),
        None,
    )
    if approved is None:
        raise AppError(ErrorCode.CONFLICT, "The approved finalization is already suspended or superseded")
    credits = [
        credit
        for credit in _list_event_items(unit_campaign_id, f"{CREDIT_PREFIX}{finalization_id}#")
        if credit.get("status") == FINAL_APPROVED
    ]
    return approved, credits


def _reopen_commit(
    current: Dict[str, Any],
    approved: Dict[str, Any],
    expected_version: int,
    reason: str,
    caller: str,
    key: str,
    fingerprint: str,
    stamp: str,
    plan: List[Dict[str, Any]],
) -> Dict[str, Any]:
    # The suspended version row keeps the reason (history stays readable).
    plan.append(
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": approved["itemKey"]},
                "UpdateExpression": (
                    "SET #status = :status, #suspendedBy = :sb, #suspendedAt = :sa, #reason = :reason, #updatedAt = :ua"
                ),
                "ConditionExpression": "#status = :approved",
                "ExpressionAttributeNames": {
                    "#status": "status",
                    "#suspendedBy": "suspendedByAccountId",
                    "#suspendedAt": "suspendedAt",
                    "#reason": "suspensionReason",
                    "#updatedAt": "updatedAt",
                },
                "ExpressionAttributeValues": {
                    ":status": FINAL_SUSPENDED,
                    ":approved": FINAL_APPROVED,
                    ":sb": caller,
                    ":sa": stamp,
                    ":reason": reason,
                    ":ua": stamp,
                },
            }
        }
    )
    # Reopening moves NO stock and NO allocations — status only.
    updated = dict(current)
    updated["status"] = "REOPENED"
    updated["approvedFinalizationId"] = None
    updated["version"] = expected_version + 1
    updated["updatedAt"] = stamp
    updated["updatedByAccountId"] = caller
    result = _event_to_graphql(updated, _utcnow(), include_slots=False)
    marker = _marker_put(caller, "reopenShowAndSell", key, fingerprint, result, int(_utcnow().timestamp()))
    plan.append(
        {
            "Update": {
                "TableName": tables.show_and_sells.table_name,
                "Key": {"unitCampaignId": current["unitCampaignId"], "itemKey": current["itemKey"]},
                "UpdateExpression": (
                    "SET #status = :status, #approved = :null, #version = :next, "
                    "#updatedAt = :ua, #updatedByAccountId = :ub"
                ),
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": {
                    "#status": "status",
                    "#approved": "approvedFinalizationId",
                    "#version": "version",
                    "#updatedAt": "updatedAt",
                    "#updatedByAccountId": "updatedByAccountId",
                },
                "ExpressionAttributeValues": {
                    ":status": "REOPENED",
                    ":null": None,
                    ":next": expected_version + 1,
                    ":ua": stamp,
                    ":ub": caller,
                    ":expected": expected_version,
                },
            }
        }
    )
    plan.append(marker)
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise AppError(
            ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        ) from None
    return result


def _reopen_args(args: Dict[str, Any]) -> Tuple[str, int, str, str]:
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    expected_version = args.get("expectedVersion")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "expectedVersion must be a positive integer")
    reason = args.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 500:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'reason' is required (1-500 characters)")
    key = args.get("idempotencyKey")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'idempotencyKey' must be between 8 and 128 characters")
    return show_and_sell_id, expected_version, reason, key


def _reopen_event(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id, expected_version, reason, key = _reopen_args(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "reopenShowAndSell")
    if replayed is not None:
        return replayed
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Event was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    unit_campaign_id = current["unitCampaignId"]
    approved, credits = _reopen_targets(current, show_and_sell_id, unit_campaign_id)

    now = _utcnow()
    stamp = _iso(now)
    plan: List[Dict[str, Any]] = _suspension_entries(credits, unit_campaign_id, stamp)
    result = _reopen_commit(current, approved, expected_version, reason, caller, key, fingerprint, stamp, plan)
    return result


# ---------------------------------------------------------------------------
# ADR 0003 per-campaign auto-reduce (after commit; retry-convergent)
# ---------------------------------------------------------------------------


def _earlier_open_totals(
    finalized_event: Dict[str, Any],
    later: Dict[str, Any],
    events: List[Dict[str, Any]],
    balances: Dict[str, Dict[str, Any]],
    unit_campaign_id: str,
) -> Dict[str, int]:
    running: Dict[str, int] = {product_id: 0 for product_id in balances}
    earlier_events = [finalized_event] + [e for e in events if _parse_ts(e["startAt"]) <= _parse_ts(later["startAt"])]
    for earlier in earlier_events:
        for alloc in _list_inventory_items(unit_campaign_id, f"{ALLOC_PREFIX}{earlier['showAndSellId']}#"):
            if alloc.get("status") != "OPEN":
                continue
            if earlier["showAndSellId"] == later["showAndSellId"]:
                continue  # candidate rows are added as they are processed
            pid = _split_alloc_product(alloc)
            running[pid] = running.get(pid, 0) + int(alloc.get("allocatedQty", 0))
    return running


def _reduce_one_later_event(
    later: Dict[str, Any],
    finalized_event: Dict[str, Any],
    balances: Dict[str, Dict[str, Any]],
    events: List[Dict[str, Any]],
    actor: str,
    stamp: str,
) -> List[Dict[str, Any]]:
    unit_campaign_id = finalized_event["unitCampaignId"]
    allocs = [
        item
        for item in _list_inventory_items(unit_campaign_id, f"{ALLOC_PREFIX}{later['showAndSellId']}#")
        if item.get("status") == "OPEN"
    ]
    if not allocs:
        return []
    # Cumulative-peak accounting: OPEN allocations of events starting no
    # later than this one (finalized + earlier + itself), per product.
    running = _earlier_open_totals(finalized_event, later, events, balances, unit_campaign_id)
    warnings: List[Dict[str, Any]] = []
    for alloc in allocs:
        warning = _reduce_one_allocation(alloc, later, running, balances, unit_campaign_id, actor, stamp)
        if warning is not None:
            warnings.append(warning)
    return warnings


def _reduce_one_allocation(
    alloc: Dict[str, Any],
    later: Dict[str, Any],
    running: Dict[str, int],
    balances: Dict[str, Dict[str, Any]],
    unit_campaign_id: str,
    actor: str,
    stamp: str,
) -> Optional[Dict[str, Any]]:
    pid = _split_alloc_product(alloc)
    balance = balances.get(pid)
    if not isinstance(balance, dict):
        return None
    sellable = int(balance.get("kernelPhysicalQty", 0))
    floor = int(alloc.get("soldQty", 0)) + int(alloc.get("releasedQty", 0))
    unconverged_target = max(0, sellable - running.get(pid, 0))
    target = max(unconverged_target, floor)  # W10-H1 sold-stock floor
    current_allocated = int(alloc.get("allocatedQty", 0))
    if target >= current_allocated:
        running[pid] = running.get(pid, 0) + current_allocated
        return None
    plan = [
        {
            "Update": {
                "TableName": tables.inventory.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": alloc["itemKey"]},
                "UpdateExpression": (
                    "SET #allocated = :allocated, #remaining = :remaining, #version = :next, #updatedAt = :ua"
                ),
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": {
                    "#allocated": "allocatedQty",
                    "#remaining": "remainingQty",
                    "#version": "version",
                    "#updatedAt": "updatedAt",
                },
                "ExpressionAttributeValues": {
                    ":allocated": target,
                    ":remaining": target - floor,
                    ":next": int(alloc.get("version", 0)) + 1,
                    ":ua": stamp,
                    ":expected": int(alloc.get("version", 0)),
                },
            }
        },
        _movement_entry(unit_campaign_id, pid, "EVENT_AUTO_REDUCE", current_allocated - target, actor, stamp),
    ]
    execute_transaction(plan)
    running[pid] = running.get(pid, 0) + target
    warning: Dict[str, Any] = {
        "showAndSellId": later["showAndSellId"],
        "productId": pid,
        "previousAllocatedQty": current_allocated,
        "allocatedQty": target,
    }
    if target == floor and floor > unconverged_target:
        warning["warning"] = "Sold-stock floor prevented full convergence"
    return warning


def _auto_reduce_later_events(finalized_event: Dict[str, Any], actor: str, stamp: str) -> List[Dict[str, Any]]:
    """Earlier-event priority: when this event finalizes, later-STARTING
    OPEN allocations on the same Unit Campaign re-check against the
    per-campaign sellable pool in start-time order (ADJACENT non-overlapping
    later events reduce too — per-campaign pool semantics, ADR 0003).
    Each reduction is floored at soldQty + releasedQty (W10-H1: remaining
    never goes negative); a floored reduction warns instead of converging.
    One EVENT_AUTO_REDUCE movement per reduced allocation; each reduction
    is its own conditioned transaction (retry re-runs converge)."""
    unit_campaign_id = finalized_event["unitCampaignId"]
    finalized_id = finalized_event["showAndSellId"]
    finalized_start = _parse_ts(finalized_event["startAt"])
    balances = {
        row["productId"]: row
        for row in tables.inventory.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"{BALANCE_PREFIX}"},
        ).get("Items", [])
    }
    events = [
        item
        for item in _list_event_items(unit_campaign_id, EVENT_PREFIX)
        if item.get("showAndSellId") != finalized_id
        and item.get("status") in ("SCHEDULED", "ACTIVE", "ENDED", "REOPENED")
    ]
    events.sort(key=lambda item: (_parse_ts(item["startAt"]), str(item.get("showAndSellId"))))
    warnings: List[Dict[str, Any]] = []
    for later in events:
        if _parse_ts(later["startAt"]) <= finalized_start:
            continue
        warnings.extend(_reduce_one_later_event(later, finalized_event, balances, events, actor, stamp))
    return warnings


def _list_finalizations(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    items = [_finalization_to_graphql(row) for row in _finalizations_for(current["unitCampaignId"], show_and_sell_id)]
    items.sort(key=lambda row: row["versionNumber"])
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _list_finalization_credits(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    show_and_sell_id = args.get("showAndSellId")
    if not isinstance(show_and_sell_id, str) or not show_and_sell_id:
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId is required")
    caller = _require_caller(event)
    current = _load_event(show_and_sell_id)
    _require_event_admin(current, caller)
    finalization_id = args.get("finalizationId")
    status = args.get("status")
    prefix = f"{CREDIT_PREFIX}{finalization_id}#" if isinstance(finalization_id, str) else CREDIT_PREFIX
    items = []
    for row in _list_event_items(current["unitCampaignId"], prefix):
        if row.get("showAndSellId") != show_and_sell_id:
            continue
        if status is not None and row.get("status") != status:
            continue
        items.append(_credit_to_graphql(row))
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _uc_credit_allocations(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = args.get("unitCampaignId")
    if not isinstance(unit_campaign_id, str) or not unit_campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    caller = _require_caller(event)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    status = args.get("status")
    items = []
    for row in _list_event_items(unit_campaign_id, CREDIT_PREFIX):
        if status is not None and row.get("status") != status:
            continue
        finalization_row = tables.show_and_sells.get_item(
            Key={"unitCampaignId": unit_campaign_id, "itemKey": f"{FINAL_PREFIX}{row['finalizationId']}"}
        ).get("Item")
        items.append(
            {
                "finalizationId": row["finalizationId"],
                "showAndSellId": row["showAndSellId"],
                "versionNumber": int(finalization_row.get("versionNumber", 1))
                if isinstance(finalization_row, dict)
                else 1,
                "profileId": row["profileId"],
                "campaignId": row["campaignId"],
                "baseAmountCents": int(row.get("baseAmountCents", 0)),
                "roundingCents": int(row.get("roundingCents", 0)),
                "totalAmountCents": int(row.get("amountCents", 0)),
                "minutesConfirmed": int(row.get("minutesConfirmed", 0)),
                "status": row.get("status", FINAL_APPROVED),
                "eventVersion": int(finalization_row.get("sourceEventVersion", 0))
                if isinstance(finalization_row, dict)
                else 0,
                "createdAt": row.get("createdAt", ""),
            }
        )
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _scout_total(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    profile_id = args.get("profileId")
    unit_campaign_id = args.get("unitCampaignId")
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or not isinstance(unit_campaign_id, str)
        or not unit_campaign_id
    ):
        raise AppError(ErrorCode.INVALID_INPUT, "profileId and unitCampaignId are required")
    caller = _require_caller(event)
    uc = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    ).get("Item")
    if not isinstance(uc, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, uc["unitId"], caller)
    total = 0
    response = tables.unit_campaigns.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": TOTAL_PREFIX},
    )
    for item in response.get("Items", []):
        if item.get("profileId") == profile_id:
            total += int(item.get("approvedAmountCents", 0))
    return {"profileId": profile_id, "unitCampaignId": unit_campaign_id, "approvedTotalCents": total}


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Any] = {
    "showAndSellFinalizationPreview": _preview,
    "updateShowAndSellRoundingDraft": _update_rounding_draft,
    "finalizeShowAndSell": _finalize_event,
    "reopenShowAndSell": _reopen_event,
    "showAndSellFinalizations": _list_finalizations,
    "showAndSellFinalizationCredits": _list_finalization_credits,
    "unitCampaignCreditAllocations": _uc_credit_allocations,
    "scoutCampaignShowAndSellTotal": _scout_total,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    info = event.get("info")
    field = info.get("fieldName") if isinstance(info, dict) else None
    operation = _DISPATCH.get(field) if isinstance(field, str) else None
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unknown operation: {field}")
    return operation(event, context)
