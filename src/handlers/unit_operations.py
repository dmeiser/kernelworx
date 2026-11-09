"""
Unit operations handlers: Units, grants, invites (Show & Sell, spec API §4.1-4.2).

Lands impact map §3.5's ``src/handlers/unit_operations.py`` in the
application's handler conventions: one dispatcher Lambda keyed on
``info.fieldName``, ``@lambda_handler`` structured errors, base-table
strongly-consistent authorization through ``utils.unit_auth``, and
transaction plans executed through ``utils.dynamodb.execute_transaction``.

Item layout (units table, wave-1 design):
- METADATA row: itemKey "METADATA" — the Unit, its counts, and version.
- GRANT#<accountId>: an active Unit Admin grant.
- GRANT_TOMBSTONE#<accountId>: proof access was removed (SEC-02/03).
- INVITE#<inviteCode>: an invite; metadataKey = inviteCode so redemption
  lookups ride the metadataKey-createdAt-index.
- IDEM markers: unitId __IDEM__, itemKey "<actor>#<scope>#<key>".

Domain rulings carried from the gate-proven build (docs/investigations/
show-sell-idempotency-convention.md and show-sell-error-vocabulary.md):
deterministic validation before the marker, marker+effect in ONE
transaction, committed-replay equality, invite redemption answers
NOT_FOUND for every non-success outcome (no existence oracle, spec 5.3),
and only FAILED redemptions increment the hourly throttle (attempt 11 is
RATE_LIMIT_EXCEEDED).
"""

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_timezone,
        require_version,
    )
    from utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        idem_expiry_epoch,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
    from utils.pagination import decode_cursor, encode_cursor, validate_page_limit
    from utils.unit_auth import (
        METADATA_ITEM_KEY,
        get_grant,
        grant_item_key,
        grant_tombstone_item_key,
        require_unit_admin,
    )
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_str_enum,
        require_timezone,
        require_version,
    )
    from ..utils.dynamodb import (
        TransactionCancelledError,
        execute_transaction,
        idem_expiry_epoch,
        tables,
    )
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger
    from ..utils.pagination import decode_cursor, encode_cursor, validate_page_limit
    from ..utils.unit_auth import (
        METADATA_ITEM_KEY,
        get_grant,
        grant_item_key,
        grant_tombstone_item_key,
        require_unit_admin,
    )

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)

ACCOUNT_UNIT_INDEX = "accountId-unitId-index"
METADATA_KEY_INDEX = "metadataKey-createdAt-index"

MAX_ACTIVE_INVITES = 20  # spec API §3.4
INVITE_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"  # decision recorded: A-Z0-9
INVITE_CODE_LENGTH = 16
INVITE_TTL = timedelta(days=14)  # spec cap; build_invite validates <= 14 days

THROTTLE_FAILED_ATTEMPT_LIMIT = 10  # attempt 11 in one UTC hour is rejected
THROTTLE_TTL = timedelta(hours=2)  # map 4.4: at least a one-hour TTL

IDEM_HASH = "__IDEM__"
INVITE_ACTIVE = "ACTIVE"
INVITE_REVOKED = "REVOKED"
INVITE_CONSUMED = "CONSUMED"

SPLIT_METHODS = ("EQUAL", "RATIO")
COUNCIL_NEED_BASES = ("PHYSICAL_STOCK", "KERNEL_STOCK")
DEFAULT_TIMEZONE = "America/Denver"
DEFAULT_SPLIT = "EQUAL"
DEFAULT_NEED_BASIS = "PHYSICAL_STOCK"

IdFactory = Callable[[], str]
Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return str(moment.isoformat()).replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _metadata_key(unit_type: str, unit_number: str, city: str, state: str) -> str:
    """Normalized exact-geography duplicate key (case-insensitive, API §4.2).

    Every component is case-folded: "Pack"/"pack" and "Denver"/"denver"
    must collide, or the duplicate guard is a case-sensitivity oracle.
    """
    return f"{unit_type.strip().casefold()}|{unit_number.strip().casefold()}|{city.strip().casefold()}|{state.strip().casefold()}"


def _fingerprint(payload: Dict[str, Any]) -> str:
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
    """Committed-replay equality: same fingerprint replays; different is a CONFLICT."""
    if marker is None:
        return None
    if marker.get("idemFingerprint") != fingerprint:
        raise AppError(ErrorCode.CONFLICT, "Idempotency key was already used with a different request")
    result = marker.get("idemResult")
    if not isinstance(result, dict):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Idempotency marker is missing its committed result")
    return result


def _cancelled_index_is(plan: List[Dict[str, Any]], entry: Dict[str, Any]) -> int:
    return plan.index(entry)


def _execute_or_replay(plan: List[Dict[str, Any]], replay_entry: Dict[str, Any]) -> None:
    """Execute the plan; on a marker-key race, re-read the marker (the winner's
    commit is replayable) instead of surfacing a bare conflict."""
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if _cancelled_index_is(plan, replay_entry) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise


def _unit_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unitId": item["unitId"],
        "unitType": item["unitType"],
        "unitNumber": item["unitNumber"],
        "city": item["city"],
        "state": item["state"],
        "displayName": item["displayName"],
        "timezone": item["timezone"],
        "splitDefault": item["splitDefault"],
        "councilNeedBasis": item["councilNeedBasis"],
        "adminCount": int(item.get("adminCount", 0)),
        "version": int(item.get("version", 0)),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
        "createdByAccountId": item["createdByAccountId"],
    }


def _grant_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unitId": item["unitId"],
        "accountId": item["accountId"],
        "role": item.get("role", "UNIT_ADMIN"),
        "createdByAccountId": item["createdByAccountId"],
        "createdAt": item["createdAt"],
    }


def _invite_to_listing(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "inviteCode": item["inviteCode"],
        "unitId": item["unitId"],
        "createdByAccountId": item["createdByAccountId"],
        "createdAt": item["createdAt"],
        "expiresAt": item["expiresAt"],
    }


def _require_caller(event: Dict[str, Any]) -> str:
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller)


def _resolve_unit_fields(args: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    """Validate and resolve Unit input fields for create and update.

    Create requires the four geography fields (absent ones raise through the
    strict validators); update treats every field as optional and omits
    absent ones from the result so the caller never re-derives them.
    """
    resolved: Dict[str, Any] = {}
    if not partial:
        resolved["unitType"] = require_bounded_str(args, "unitType", 50)
        resolved["unitNumber"] = require_bounded_str(args, "unitNumber", 20)
        resolved["city"] = require_bounded_str(args, "city", 100)
        resolved["state"] = require_bounded_str(args, "state", 2)
    else:
        for field, bound in (("unitType", 50), ("unitNumber", 20), ("city", 100), ("state", 2)):
            if args.get(field) is not None:
                resolved[field] = require_bounded_str(args, field, bound)
    if args.get("displayName") is not None:
        resolved["displayName"] = require_bounded_str(args, "displayName", 100)
    if args.get("timezone") is not None:
        resolved["timezone"] = require_timezone(args, "timezone")
    if args.get("splitDefault") is not None:
        resolved["splitDefault"] = require_str_enum(args, "splitDefault", SPLIT_METHODS)
    if args.get("councilNeedBasis") is not None:
        resolved["councilNeedBasis"] = require_str_enum(args, "councilNeedBasis", COUNCIL_NEED_BASES)
    return resolved


def _new_invite_code() -> str:
    rng = secrets.SystemRandom()
    return "".join(rng.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def _find_duplicate_geography(metadata_key: str, exclude_unit_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Exact-geography duplicate via the metadataKey index (warning-free unless hit)."""
    response = tables.units.query(
        IndexName=METADATA_KEY_INDEX,
        KeyConditionExpression="metadataKey = :mk",
        ExpressionAttributeValues={":mk": metadata_key},
    )
    for item in response.get("Items", []):
        if item.get("itemKey") == METADATA_ITEM_KEY and item.get("unitId") != exclude_unit_id:
            return dict(item)
    return None


def _active_invite_count(item: Dict[str, Any]) -> int:
    return int(item.get("activeInviteCount", 0))


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _create_unit(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    # Deterministic input validation BEFORE the marker (convention rule 1).
    resolved = _resolve_unit_fields(args, partial=False)
    duplicate_confirmed = bool(args.get("duplicateConfirmed", False))
    key = require_idempotency_key(args)

    caller = _require_caller(event)
    now = _utcnow()
    stamp = _iso(now)
    fingerprint = _fingerprint({**args, "actor": caller})

    replayed = _check_marker(_get_marker(caller, "createUnit", key), fingerprint)
    if replayed is not None:
        return replayed

    metadata_key = _metadata_key(resolved["unitType"], resolved["unitNumber"], resolved["city"], resolved["state"])
    duplicate = _find_duplicate_geography(metadata_key, exclude_unit_id=None)
    if duplicate is not None and not duplicate_confirmed:
        raise AppError(
            ErrorCode.CONFLICT,
            "A Unit with this exact geography already exists; confirm to create anyway",
            details={"reason": "DUPLICATE_GEOGRAPHY"},
        )

    unit_id = str(uuid.uuid4())
    unit_item = {
        "unitId": unit_id,
        "itemKey": METADATA_ITEM_KEY,
        "accountId": caller,
        "unitType": resolved["unitType"],
        "unitNumber": resolved["unitNumber"],
        "city": resolved["city"],
        "state": resolved["state"],
        "displayName": resolved.get("displayName")
        or f"{resolved['unitType']} {resolved['unitNumber']} ({resolved['city']})",
        "timezone": resolved.get("timezone") or DEFAULT_TIMEZONE,
        "splitDefault": resolved.get("splitDefault") or DEFAULT_SPLIT,
        "councilNeedBasis": resolved.get("councilNeedBasis") or DEFAULT_NEED_BASIS,
        "metadataKey": metadata_key,
        "adminCount": 1,
        "activeInviteCount": 0,
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
        "createdByAccountId": caller,
    }
    grant_item = {
        "unitId": unit_id,
        "itemKey": grant_item_key(caller),
        "accountId": caller,
        "role": "UNIT_ADMIN",
        "createdByAccountId": caller,
        "createdAt": stamp,
    }
    result = {"unit": _unit_to_graphql(unit_item), "grant": _grant_to_graphql(grant_item)}
    marker = _marker_put(caller, "createUnit", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Put": {
                "TableName": tables.units.table_name,
                "Item": unit_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Put": {
                "TableName": tables.units.table_name,
                "Item": grant_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return result


def _update_unit(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    unit_id = require_bounded_str(args, "unitId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)
    resolved = _resolve_unit_fields(args, partial=True)

    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "updateUnit", key), fingerprint)
    if replayed is not None:
        return replayed

    units_table = tables.units
    current = require_unit_admin(units_table, unit_id, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Unit was modified concurrently", details={"reason": "VERSION_MISMATCH"})

    merged = {**current, **resolved}
    # Omitted displayName is never re-derived (clean-room ruling).
    new_metadata_key = _metadata_key(merged["unitType"], merged["unitNumber"], merged["city"], merged["state"])
    if new_metadata_key != current.get("metadataKey"):
        # Update has no confirmation flag: a colliding change is invalid input.
        if _find_duplicate_geography(new_metadata_key, exclude_unit_id=unit_id) is not None:
            raise AppError(ErrorCode.INVALID_INPUT, "These changes collide with an existing Unit's geography")
        merged["metadataKey"] = new_metadata_key

    now = _utcnow()
    stamp = _iso(now)
    # Every attribute is expression-name-tokenized: several natural names
    # (state, timezone) are DynamoDB reserved keywords.
    expression = (
        "SET #unitType = :ut, #unitNumber = :un, #city = :ci, #state = :st, #displayName = :dn, "
        "#timezone = :tz, #splitDefault = :sd, #councilNeedBasis = :cb, #metadataKey = :mk, "
        "#version = #version + :one, #updatedAt = :ua"
    )
    values = {
        ":ut": merged["unitType"],
        ":un": merged["unitNumber"],
        ":ci": merged["city"],
        ":st": merged["state"],
        ":dn": merged["displayName"],
        ":tz": merged["timezone"],
        ":sd": merged["splitDefault"],
        ":cb": merged["councilNeedBasis"],
        ":mk": merged["metadataKey"],
        ":one": 1,
        ":ua": stamp,
    }
    update = {
        "Update": {
            "TableName": units_table.table_name,
            "Key": {"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
            "UpdateExpression": expression,
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#unitType": "unitType",
                "#unitNumber": "unitNumber",
                "#city": "city",
                "#state": "state",
                "#displayName": "displayName",
                "#timezone": "timezone",
                "#splitDefault": "splitDefault",
                "#councilNeedBasis": "councilNeedBasis",
                "#metadataKey": "metadataKey",
                "#version": "version",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {":expected": expected_version, **values},
        }
    }
    merged["version"] = int(current.get("version", 0)) + 1
    merged["updatedAt"] = stamp
    result = _unit_to_graphql(merged)
    marker = _marker_put(caller, "updateUnit", key, fingerprint, result, _epoch(now))
    plan = [update, marker]
    _execute_or_replay(plan, marker)
    return result


def _create_unit_invite(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    key = require_idempotency_key(args)
    caller = _require_caller(event)
    fingerprint = _fingerprint({"unitId": unit_id, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "createUnitInvite", key), fingerprint)
    if replayed is not None:
        return replayed

    units_table = tables.units
    current = require_unit_admin(units_table, unit_id, caller)
    if _active_invite_count(current) >= MAX_ACTIVE_INVITES:
        raise AppError(ErrorCode.CONFLICT, "This Unit already has the maximum number of active invites")

    now = _utcnow()
    stamp = _iso(now)
    expires_at = now + INVITE_TTL
    for _attempt in range(5):
        code = _new_invite_code()
        existing = units_table.get_item(Key={"unitId": unit_id, "itemKey": f"INVITE#{code}"})
        if not existing.get("Item"):
            break
    else:  # pragma: no cover - 2**80 code space makes this unreachable
        raise AppError(ErrorCode.INTERNAL_ERROR, "Could not allocate an invite code")

    invite_item = {
        "unitId": unit_id,
        "itemKey": f"INVITE#{code}",
        "metadataKey": code,
        "inviteCode": code,
        "createdByAccountId": caller,
        "createdAt": stamp,
        "expiresAt": _iso(expires_at),
        "expiresAtEpoch": _epoch(expires_at),
        "status": INVITE_ACTIVE,
    }
    result = _invite_to_listing(invite_item)
    marker = _marker_put(caller, "createUnitInvite", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Put": {
                "TableName": units_table.table_name,
                "Item": invite_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Update": {
                "TableName": units_table.table_name,
                "Key": {"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
                "UpdateExpression": "ADD activeInviteCount :one SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "activeInviteCount < :cap AND version = :v",
                "ExpressionAttributeValues": {
                    ":one": 1,
                    ":ua": stamp,
                    ":cap": MAX_ACTIVE_INVITES,
                    ":v": int(current["version"]),
                },
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return result


def _revoke_unit_invite(event: Dict[str, Any], context: Any) -> bool:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    invite_code = require_bounded_str(args, "inviteCode", INVITE_CODE_LENGTH)
    key = require_idempotency_key(args)
    caller = _require_caller(event)
    fingerprint = _fingerprint({"unitId": unit_id, "inviteCode": invite_code, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "revokeUnitInvite", key), fingerprint)
    if replayed is not None:
        return bool(replayed["revoked"])

    units_table = tables.units
    current = require_unit_admin(units_table, unit_id, caller)
    invite = units_table.get_item(Key={"unitId": unit_id, "itemKey": f"INVITE#{invite_code}"}).get("Item")
    if not invite or invite.get("status") != INVITE_ACTIVE:
        # Invisible to admins once consumed/revoked: NOT_FOUND, no oracle.
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")

    now = _utcnow()
    stamp = _iso(now)
    result = {"revoked": True}
    marker = _marker_put(caller, "revokeUnitInvite", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Update": {
                "TableName": units_table.table_name,
                "Key": {"unitId": unit_id, "itemKey": f"INVITE#{invite_code}"},
                "UpdateExpression": "SET #status = :revoked, updatedAt = :ua",
                "ConditionExpression": "#status = :active",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {":revoked": INVITE_REVOKED, ":ua": stamp, ":active": INVITE_ACTIVE},
            }
        },
        {
            "Update": {
                "TableName": units_table.table_name,
                "Key": {"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
                "UpdateExpression": "ADD activeInviteCount :neg SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "activeInviteCount > :zero AND version = :v",
                "ExpressionAttributeValues": {
                    ":neg": -1,
                    ":one": 1,
                    ":ua": stamp,
                    ":zero": 0,
                    ":v": int(current["version"]),
                },
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return True


def _throttle_key(account_id: str, now: datetime) -> str:
    return f"UNIT_INVITE_REDEMPTION#{account_id}#WINDOW#{now:%Y-%m-%dT%H}"


def _record_failed_redemption(account_id: str, now: datetime) -> None:
    """Increment the hourly failure counter; raise RATE_LIMIT_EXCEEDED past the limit."""
    key = _throttle_key(account_id, now)
    response = tables.public_order_throttles.update_item(
        Key={"key": key},
        UpdateExpression="ADD attempts :one SET expiresAt = :exp",
        ExpressionAttributeValues={":one": 1, ":exp": _epoch(now + THROTTLE_TTL)},
        ReturnValues="UPDATED_NEW",
    )
    attempts = int(response.get("Attributes", {}).get("attempts", 1))
    if attempts > THROTTLE_FAILED_ATTEMPT_LIMIT:
        window_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        raise AppError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            "Too many failed redemption attempts; try again later",
            details={"retryAfterHint": _iso(window_end)},
        )


def _redeem_unit_invite(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    invite_code = require_bounded_str(args, "inviteCode", INVITE_CODE_LENGTH)
    key = require_idempotency_key(args)
    caller = _require_caller(event)
    fingerprint = _fingerprint({"inviteCode": invite_code, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "redeemUnitInvite", key), fingerprint)
    if replayed is not None:
        return replayed

    now = _utcnow()
    throttle_row = tables.public_order_throttles.get_item(Key={"key": _throttle_key(caller, now)})
    existing_attempts = int(throttle_row.get("Item", {}).get("attempts", 0))
    if existing_attempts >= THROTTLE_FAILED_ATTEMPT_LIMIT:
        window_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        raise AppError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            "Too many failed redemption attempts; try again later",
            details={"retryAfterHint": _iso(window_end)},
        )

    # Invite lookup by code through the metadataKey index (global uniqueness).
    response = tables.units.query(
        IndexName=METADATA_KEY_INDEX,
        KeyConditionExpression="metadataKey = :code",
        ExpressionAttributeValues={":code": invite_code},
    )
    invite = next(
        (item for item in response.get("Items", []) if item.get("itemKey", "").startswith("INVITE#")),
        None,
    )
    if invite is None or invite.get("status") != INVITE_ACTIVE or int(invite.get("expiresAtEpoch", 0)) <= _epoch(now):
        # Expired / consumed / revoked / unknown are indistinguishable (spec 5.3).
        _record_failed_redemption(caller, now)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")

    unit_id = invite["unitId"]
    existing_grant = get_grant(tables.units, unit_id, caller)
    if existing_grant is not None:
        # Re-joining admin: the effect already holds; do not consume an invite
        # and do not count a failure.
        result = _grant_to_graphql(existing_grant)
        marker = _marker_put(caller, "redeemUnitInvite", key, fingerprint, result, _epoch(now))
        execute_transaction([marker])
        return result

    stamp = _iso(now)
    grant_item = {
        "unitId": unit_id,
        "itemKey": grant_item_key(caller),
        "accountId": caller,
        "role": "UNIT_ADMIN",
        "createdByAccountId": caller,
        "createdAt": stamp,
    }
    result = _grant_to_graphql(grant_item)
    marker = _marker_put(caller, "redeemUnitInvite", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Update": {
                "TableName": tables.units.table_name,
                "Key": {"unitId": unit_id, "itemKey": invite["itemKey"]},
                "UpdateExpression": "SET #status = :consumed, consumedByAccountId = :acct, updatedAt = :ua",
                "ConditionExpression": "#status = :active AND expiresAtEpoch > :now",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":consumed": INVITE_CONSUMED,
                    ":acct": caller,
                    ":ua": stamp,
                    ":active": INVITE_ACTIVE,
                    ":now": _epoch(now),
                },
            }
        },
        {
            "Put": {
                "TableName": tables.units.table_name,
                "Item": grant_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Update": {
                "TableName": tables.units.table_name,
                "Key": {"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
                "UpdateExpression": "ADD activeInviteCount :neg, adminCount :one SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "attribute_exists(itemKey)",
                "ExpressionAttributeValues": {":neg": -1, ":one": 1, ":ua": stamp},
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return result


def _revoke_unit_access_grant(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    target_account = require_bounded_str(args, "accountId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)
    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "revokeUnitAccessGrant", key), fingerprint)
    if replayed is not None:
        return replayed

    units_table = tables.units
    current = require_unit_admin(units_table, unit_id, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(ErrorCode.CONFLICT, "Unit was modified concurrently", details={"reason": "VERSION_MISMATCH"})
    if get_grant(units_table, unit_id, target_account) is None:
        # No grant (or already tombstoned) is invisible: NOT_FOUND.
        raise AppError(ErrorCode.NOT_FOUND, "Grant not found")
    if int(current.get("adminCount", 0)) <= 1:
        raise AppError(
            ErrorCode.CONFLICT,
            "A Unit must keep at least one admin",
            details={"reason": "LAST_UNIT_ADMIN"},
        )

    now = _utcnow()
    stamp = _iso(now)
    plan = [
        {
            "Delete": {
                "TableName": units_table.table_name,
                "Key": {"unitId": unit_id, "itemKey": grant_item_key(target_account)},
                "ConditionExpression": "attribute_exists(itemKey)",
            }
        },
        {
            "Put": {
                "TableName": units_table.table_name,
                "Item": {
                    "unitId": unit_id,
                    "itemKey": grant_tombstone_item_key(target_account),
                    "accountId": target_account,
                    "removedAt": stamp,
                    "removedByAccountId": caller,
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Update": {
                "TableName": units_table.table_name,
                "Key": {"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
                "UpdateExpression": "ADD adminCount :neg SET version = version + :one, updatedAt = :ua",
                "ConditionExpression": "adminCount > :min AND version = :v",
                "ExpressionAttributeValues": {
                    ":neg": -1,
                    ":one": 1,
                    ":ua": stamp,
                    ":min": 1,
                    ":v": expected_version,
                },
            }
        },
        _marker_put(
            caller,
            "revokeUnitAccessGrant",
            key,
            fingerprint,
            None,
            _epoch(now),
        ),
    ]
    merged = {
        **current,
        "adminCount": int(current.get("adminCount", 1)) - 1,
        "version": expected_version + 1,
        "updatedAt": stamp,
    }
    result = _unit_to_graphql(merged)
    plan[-1]["Put"]["Item"]["idemResult"] = result
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if _cancelled_index_is(plan, plan[-1]) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        if 2 in exc.failed_indexes:  # METADATA update: count/version guard lost the race
            raise AppError(
                ErrorCode.CONFLICT, "Unit was modified concurrently", details={"reason": "VERSION_MISMATCH"}
            ) from None
        raise
    return result


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _page_args(event: Dict[str, Any]) -> tuple[int, Optional[str]]:
    page = event.get("arguments", {}).get("page") or {}
    limit = validate_page_limit(page.get("limit"))
    return limit, page.get("cursor")


def _my_units(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    caller = _require_caller(event)
    limit, cursor = _page_args(event)
    kwargs: Dict[str, Any] = {
        "IndexName": ACCOUNT_UNIT_INDEX,
        "KeyConditionExpression": "accountId = :acct",
        "ExpressionAttributeValues": {":acct": caller},
        "Limit": limit,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor, f"myUnits:{caller}")
    response = tables.units.query(**kwargs)
    items = [_unit_to_graphql(item) for item in response.get("Items", []) if item.get("itemKey") == METADATA_ITEM_KEY]
    last_key = response.get("LastEvaluatedKey")
    has_next = last_key is not None
    while has_next and len(items) < limit:
        # GSI pages can be grant-row-heavy; keep fetching until the page is
        # full of METADATA rows or the index is exhausted.
        kwargs["ExclusiveStartKey"] = last_key
        response = tables.units.query(**kwargs)
        batch = [
            _unit_to_graphql(item) for item in response.get("Items", []) if item.get("itemKey") == METADATA_ITEM_KEY
        ]
        items.extend(batch[: limit - len(items)])
        last_key = response.get("LastEvaluatedKey")
        has_next = last_key is not None
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"myUnits:{caller}", last_key) if has_next and last_key else None,
            "hasNextPage": has_next,
        },
    }


def _get_unit(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    caller = _require_caller(event)
    return _unit_to_graphql(require_unit_admin(tables.units, unit_id, caller))


def _unit_admins(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    caller = _require_caller(event)
    require_unit_admin(tables.units, unit_id, caller)
    limit, cursor = _page_args(event)
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": Key("unitId").eq(unit_id) & Key("itemKey").begins_with("GRANT#"),
        "Limit": limit,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor, f"unitAdmins:{unit_id}")
    response = tables.units.query(**kwargs)
    items = [_grant_to_graphql(item) for item in response.get("Items", [])]
    last_key = response.get("LastEvaluatedKey")
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"unitAdmins:{unit_id}", last_key) if last_key else None,
            "hasNextPage": last_key is not None,
        },
    }


def _unit_invites(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    caller = _require_caller(event)
    require_unit_admin(tables.units, unit_id, caller)
    limit, cursor = _page_args(event)
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": Key("unitId").eq(unit_id) & Key("itemKey").begins_with("INVITE#"),
        "Limit": limit,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor, f"unitInvites:{unit_id}")
    response = tables.units.query(**kwargs)
    items = [_invite_to_listing(item) for item in response.get("Items", []) if item.get("status") == INVITE_ACTIVE]
    last_key = response.get("LastEvaluatedKey")
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"unitInvites:{unit_id}", last_key) if last_key else None,
            "hasNextPage": last_key is not None,
        },
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "createUnit": _create_unit,
    "updateUnit": _update_unit,
    "createUnitInvite": _create_unit_invite,
    "revokeUnitInvite": _revoke_unit_invite,
    "redeemUnitInvite": _redeem_unit_invite,
    "revokeUnitAccessGrant": _revoke_unit_access_grant,
    "myUnits": _my_units,
    "unit": _get_unit,
    "unitAdmins": _unit_admins,
    "unitInvites": _unit_invites,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch a Unit operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported Unit operation: {field_name}")
    return operation(event, context)
