"""
Unit Campaign operations handlers: Unit Campaigns, join lifecycle, roster
(Show & Sell, spec API §5).

Lands impact map §3.5's ``src/handlers/unit_campaign_operations.py`` in the
application's handler conventions (dispatcher Lambda, ``@lambda_handler``,
``utils.unit_auth`` authorization, ``utils.dynamodb.execute_transaction``
plans, committed-replay idempotency).

Item layout:
- unit_campaigns METADATA row: the Unit Campaign (itemKey "METADATA"),
  carrying unitId/createdAt for the unitId-createdAt-index and catalogId
  for the soft-delete usage guard.
- unit_campaigns MEMBER#<profileId>: one roster row per Scout Campaign
  (status ACTIVE/REMOVED, membership version).
- unit_campaigns GUARD#ROSTER: the roster guard version; bumped on
  join/removal only, read into every membership projection (the SDL's
  guardVersion field exists because participation bumps the membership row
  while the guard must move independently).
- units JOIN#<joinCode> pointer row: join codes are looked up through the
  units table's metadataKey-createdAt-index (wave-1 design decision), so no
  new GSI is needed; codes are generated from the unambiguous alphabet and
  checked globally before creation.

Join-time catalog identity (impact map 3.3) is enforced HERE: a Scout
Campaign can only join a Unit Campaign when their catalogIds match, so
product/price identity can never drift between origin and Unit records.
"""

import secrets
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
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_strict_int,
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

UNIT_CREATED_INDEX = "unitId-createdAt-index"
PROFILES_PROFILE_ID_INDEX = "profileId-index"

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # unambiguous (decision recorded)
JOIN_CODE_LENGTH = 16

MEMBER_ACTIVE = "ACTIVE"
MEMBER_REMOVED = "REMOVED"
GUARD_ITEM_KEY = "GUARD#ROSTER"

IDEM_HASH = "__IDEM__"


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


def _idempotency_begin(
    event: Dict[str, Any], args: Dict[str, Any], scope: str
) -> tuple[str, str, Optional[Dict[str, Any]]]:
    """Resolve the caller, compute the request fingerprint, and read the
    committed marker (replay result or None)."""
    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, scope, str(args.get("idempotencyKey", ""))), fingerprint)
    return caller, fingerprint, replayed


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


def _execute_or_replay(plan: List[Dict[str, Any]], marker_entry: Dict[str, Any]) -> None:
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        if plan.index(marker_entry) in exc.failed_indexes:
            raise AppError(
                ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
            ) from None
        raise


def _filtered_pages(
    query: Any, kwargs: Dict[str, Any], limit: int, keep: Any
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Run a paginated query, dropping non-matching rows and fetching more
    pages while the caller's page is unfilled and the index has more."""
    response = query(**kwargs)
    items = [item for item in response.get("Items", []) if keep(item)]
    last_key = response.get("LastEvaluatedKey")
    while last_key is not None and len(items) < limit:
        kwargs["ExclusiveStartKey"] = last_key
        response = query(**kwargs)
        items.extend(item for item in response.get("Items", []) if keep(item))
        last_key = response.get("LastEvaluatedKey")
    return items[:limit], last_key


def _new_join_code() -> str:
    rng = secrets.SystemRandom()
    return "".join(rng.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


def _join_code_taken(code: str) -> bool:
    response = tables.units.query(
        IndexName="metadataKey-createdAt-index",
        KeyConditionExpression="metadataKey = :code",
        ExpressionAttributeValues={":code": code},
        Limit=1,
    )
    return bool(response.get("Items"))


def _require_uc_admin(unit_campaign_id: str, caller: str) -> Dict[str, Any]:
    """Fetch the Unit Campaign METADATA row and authorize the caller as a
    Unit Admin of its Unit. NOT_FOUND for a missing Unit Campaign (no oracle)."""
    response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, item["unitId"], caller)
    return item


def _campaign_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unitCampaignId": item["unitCampaignId"],
        "unitId": item["unitId"],
        "campaignName": item["campaignName"],
        "campaignYear": int(item["campaignYear"]),
        "catalogId": item["catalogId"],
        "joinCode": item["joinCode"],
        "isActive": bool(item.get("isActive", True)),
        "version": int(item.get("version", 0)),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
        "createdByAccountId": item["createdByAccountId"],
        "updatedByAccountId": item.get("updatedByAccountId"),
    }


def _get_guard_row(unit_campaign_id: str) -> Dict[str, Any]:
    response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": GUARD_ITEM_KEY}, ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Roster guard row is missing")
    return item


def _profile_display_name(profile_id: str) -> Optional[str]:
    """Resolve a profile's current display name through its GSI (read-only)."""
    response = tables.profiles.query(
        IndexName=PROFILES_PROFILE_ID_INDEX,
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        name = item.get("displayName")
        return str(name) if name else None
    return None


def _membership_to_graphql(item: Dict[str, Any], guard_version: int) -> Dict[str, Any]:
    return {
        "unitCampaignId": item["unitCampaignId"],
        "unitId": item["unitId"],
        "campaignId": item["campaignId"],
        "profileId": item["profileId"],
        "status": item["status"],
        "joinedByAccountId": item["joinedByAccountId"],
        "joinedAt": item["joinedAt"],
        "removedByAccountId": item.get("removedByAccountId"),
        "removedAt": item.get("removedAt"),
        "version": int(item.get("version", 0)),
        "profileDisplayName": _profile_display_name(item["profileId"]),
        "campaignName": item.get("campaignNameSnapshot"),
        "guardVersion": guard_version,
    }


def _require_caller(event: Dict[str, Any]) -> str:
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller)


def _find_campaign_owner(campaign_id: str) -> Optional[Dict[str, Any]]:
    """Locate a legacy Scout Campaign row (GSI first, caller re-checks)."""
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": campaign_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        return dict(item)
    return None


def _authoritative_campaign(campaign_id: str) -> Dict[str, Any]:
    """Strongly consistent Campaign read via its natural key (impact map 3.2)."""
    pointer = _find_campaign_owner(campaign_id)
    if pointer is None:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    response = tables.campaigns.get_item(
        Key={"profileId": pointer["profileId"], "campaignId": campaign_id}, ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    return item


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _resolve_uc_update_fields(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the optional updateUnitCampaign fields; absent fields are omitted."""
    resolved: Dict[str, Any] = {}
    if args.get("campaignName") is not None:
        resolved["campaignName"] = require_bounded_str(args, "campaignName", 100)
    if args.get("campaignYear") is not None:
        campaign_year = require_strict_int(args, "campaignYear")
        if campaign_year < 2000 or campaign_year > 2200:
            raise AppError(ErrorCode.INVALID_INPUT, "campaignYear is out of range")
        resolved["campaignYear"] = campaign_year
    is_active = args.get("isActive")
    if is_active is not None:
        if not isinstance(is_active, bool):
            raise AppError(ErrorCode.INVALID_INPUT, "isActive must be a boolean")
        resolved["isActive"] = is_active
    return resolved


def _uc_update_entry(
    unit_campaign_id: str, merged: Dict[str, Any], expected_version: int, caller: str, stamp: str
) -> Dict[str, Any]:
    """Build the conditional METADATA update for updateUnitCampaign."""
    return {
        "Update": {
            "TableName": tables.unit_campaigns.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY},
            "UpdateExpression": "SET campaignName = :cn, campaignYear = :cy, isActive = :ia, version = version + :one, updatedAt = :ua, updatedByAccountId = :ub",
            "ConditionExpression": "version = :expected",
            "ExpressionAttributeValues": {
                ":cn": merged["campaignName"],
                ":cy": int(merged["campaignYear"]),
                ":ia": bool(merged["isActive"]),
                ":one": 1,
                ":ua": stamp,
                ":ub": caller,
                ":expected": expected_version,
            },
        }
    }


def _create_unit_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    unit_id = require_bounded_str(args, "unitId", 100)
    campaign_name = require_bounded_str(args, "campaignName", 100)
    campaign_year = require_strict_int(args, "campaignYear")
    if campaign_year < 2000 or campaign_year > 2200:
        raise AppError(ErrorCode.INVALID_INPUT, "campaignYear is out of range")
    catalog_id = require_bounded_str(args, "catalogId", 100)
    key = require_idempotency_key(args)

    caller = _require_caller(event)
    fingerprint = _fingerprint({**args, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "createUnitCampaign", key), fingerprint)
    if replayed is not None:
        return replayed

    require_unit_admin(tables.units, unit_id, caller)

    join_code = _new_join_code()
    for _attempt in range(5):
        if not _join_code_taken(join_code):
            break
        join_code = _new_join_code()
    else:  # pragma: no cover - 2**77 code space makes this unreachable
        raise AppError(ErrorCode.INTERNAL_ERROR, "Could not allocate a join code")

    now = _utcnow()
    stamp = _iso(now)
    unit_campaign_id = str(uuid.uuid4())
    campaign_item = {
        "unitCampaignId": unit_campaign_id,
        "itemKey": METADATA_ITEM_KEY,
        "unitId": unit_id,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "catalogId": catalog_id,
        "joinCode": join_code,
        "isActive": True,
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
        "createdByAccountId": caller,
        "updatedByAccountId": caller,
    }
    join_pointer = {
        "unitId": unit_id,
        "itemKey": f"JOIN#{join_code}",
        "metadataKey": join_code,
        "unitCampaignId": unit_campaign_id,
        "createdAt": stamp,
        "status": MEMBER_ACTIVE,
    }
    result = _campaign_to_graphql(campaign_item)
    marker = _marker_put(caller, "createUnitCampaign", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Put": {
                "TableName": tables.unit_campaigns.table_name,
                "Item": campaign_item,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Put": {
                "TableName": tables.unit_campaigns.table_name,
                "Item": {
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": GUARD_ITEM_KEY,
                    "guardVersion": 1,
                    "createdAt": stamp,
                },
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        {
            "Put": {
                "TableName": tables.units.table_name,
                "Item": join_pointer,
                "ConditionExpression": "attribute_not_exists(itemKey)",
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return result


def _update_unit_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)
    resolved = _resolve_uc_update_fields(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "updateUnitCampaign")
    if replayed is not None:
        return replayed

    current = _require_uc_admin(unit_campaign_id, caller)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "Unit Campaign was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        )

    merged = {**current, **resolved}
    now = _utcnow()
    stamp = _iso(now)
    merged["version"] = expected_version + 1
    merged["updatedAt"] = stamp
    merged["updatedByAccountId"] = caller
    update = _uc_update_entry(unit_campaign_id, merged, expected_version, caller, stamp)
    result = _campaign_to_graphql(merged)
    marker = _marker_put(caller, "updateUnitCampaign", key, fingerprint, result, _epoch(now))
    _execute_or_replay([update, marker], marker)
    return result


def _join_unit_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    join_code = require_bounded_str(args, "joinCode", JOIN_CODE_LENGTH)
    campaign_id = require_bounded_str(args, "campaignId", 100)
    key = require_idempotency_key(args)

    caller = _require_caller(event)
    fingerprint = _fingerprint({"joinCode": join_code, "campaignId": campaign_id, "actor": caller})
    replayed = _check_marker(_get_marker(caller, "joinUnitCampaign", key), fingerprint)
    if replayed is not None:
        return replayed

    # Resolve the Unit Campaign through the join-code pointer (units table).
    pointer_response = tables.units.query(
        IndexName="metadataKey-createdAt-index",
        KeyConditionExpression="metadataKey = :code",
        ExpressionAttributeValues={":code": join_code},
        Limit=1,
    )
    pointer = next(
        (item for item in pointer_response.get("Items", []) if item.get("itemKey", "").startswith("JOIN#")),
        None,
    )
    if pointer is None or pointer.get("status") != MEMBER_ACTIVE:
        raise AppError(ErrorCode.NOT_FOUND, "Join code not found")
    unit_campaign_id = pointer["unitCampaignId"]
    unit_id = pointer["unitId"]

    uc_response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    unit_campaign = uc_response.get("Item")
    if not isinstance(unit_campaign, dict) or not bool(unit_campaign.get("isActive", False)):
        raise AppError(ErrorCode.NOT_FOUND, "Join code not found")

    campaign = _authoritative_campaign(campaign_id)
    profile_id = campaign["profileId"]
    # The joining Campaign must belong to (or be WRITE-shared with) the caller.
    if not check_profile_access(caller, profile_id, "WRITE"):
        raise AppError(ErrorCode.FORBIDDEN, "You do not have access to this Campaign")
    # Join-time catalog identity (impact map 3.3): never let product/price
    # identity drift between the Scout Campaign and the Unit Campaign.
    if campaign.get("catalogId") != unit_campaign.get("catalogId"):
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "This Campaign uses a different catalog than the Unit Campaign",
        )

    now = _utcnow()
    stamp = _iso(now)
    guard = _get_guard_row(unit_campaign_id)
    guard_version = int(guard.get("guardVersion", 0))
    member_item = {
        "unitCampaignId": unit_campaign_id,
        "unitId": unit_id,
        "itemKey": f"MEMBER#{profile_id}",
        "profileId": profile_id,
        "campaignId": campaign_id,
        "status": MEMBER_ACTIVE,
        "joinedByAccountId": caller,
        "joinedAt": stamp,
        "version": 1,
        "campaignNameSnapshot": campaign.get("campaignName"),
    }
    result = _membership_to_graphql(member_item, guard_version + 1)
    marker = _marker_put(caller, "joinUnitCampaign", key, fingerprint, result, _epoch(now))
    plan = [
        {
            "Put": {
                "TableName": tables.unit_campaigns.table_name,
                "Item": member_item,
                "ConditionExpression": "attribute_not_exists(itemKey) OR #status = :removed",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {":removed": MEMBER_REMOVED},
            }
        },
        {
            "Update": {
                "TableName": tables.unit_campaigns.table_name,
                "Key": {"unitCampaignId": unit_campaign_id, "itemKey": GUARD_ITEM_KEY},
                "UpdateExpression": "ADD guardVersion :one SET updatedAt = :ua",
                "ConditionExpression": "guardVersion = :gv",
                "ExpressionAttributeValues": {":one": 1, ":ua": stamp, ":gv": guard_version},
            }
        },
        {
            "Update": {
                "TableName": tables.campaigns.table_name,
                "Key": {"profileId": profile_id, "campaignId": campaign_id},
                "UpdateExpression": "SET unitCampaignKey = :uck",
                "ConditionExpression": "attribute_exists(campaignId)",
                "ExpressionAttributeValues": {":uck": unit_campaign_id},
            }
        },
        marker,
    ]
    _execute_or_replay(plan, marker)
    return result


def _removal_plan(
    unit_campaign_id: str,
    profile_id: str,
    campaign_id: str,
    caller: str,
    stamp: str,
    expected_membership_version: int,
    expected_guard_version: int,
    marker: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build the four-entry removal plan: member row, roster guard, legacy
    campaign detach, idempotency marker (marker last — its index is the
    concurrency-replay signal)."""
    update_member = {
        "Update": {
            "TableName": tables.unit_campaigns.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": f"MEMBER#{profile_id}"},
            "UpdateExpression": "SET #status = :removed, removedByAccountId = :rb, removedAt = :ra, version = version + :one",
            "ConditionExpression": "#status = :active AND version = :expected",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {
                ":removed": MEMBER_REMOVED,
                ":rb": caller,
                ":ra": stamp,
                ":one": 1,
                ":active": MEMBER_ACTIVE,
                ":expected": expected_membership_version,
            },
        }
    }
    update_guard = {
        "Update": {
            "TableName": tables.unit_campaigns.table_name,
            "Key": {"unitCampaignId": unit_campaign_id, "itemKey": GUARD_ITEM_KEY},
            "UpdateExpression": "ADD guardVersion :one SET updatedAt = :ua",
            "ConditionExpression": "guardVersion = :gv",
            "ExpressionAttributeValues": {":one": 1, ":ua": stamp, ":gv": expected_guard_version},
        }
    }
    detach_campaign = {
        "Update": {
            "TableName": tables.campaigns.table_name,
            "Key": {"profileId": profile_id, "campaignId": campaign_id},
            "UpdateExpression": "REMOVE unitCampaignKey",
            "ConditionExpression": "attribute_exists(campaignId)",
        }
    }
    return [update_member, update_guard, detach_campaign, marker]


def _load_membership_for_removal(
    unit_campaign_id: str,
    campaign_id: str,
    expected_membership_version: int,
    expected_guard_version: int,
    caller: str,
) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """Authorize and load everything removeUnitCampaignMembership conditions
    on: the Unit Campaign (admin-guarded), the authoritative Campaign, the
    ACTIVE membership row at the expected version, and the roster guard."""
    _require_uc_admin(unit_campaign_id, caller)
    campaign = _authoritative_campaign(campaign_id)
    profile_id = campaign["profileId"]
    member_response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": f"MEMBER#{profile_id}"}, ConsistentRead=True
    )
    member = member_response.get("Item")
    if not isinstance(member, dict) or member.get("status") != MEMBER_ACTIVE:
        raise AppError(ErrorCode.NOT_FOUND, "Membership not found")
    if int(member.get("version", 0)) != expected_membership_version:
        raise AppError(
            ErrorCode.CONFLICT, "Membership was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        )
    guard = _get_guard_row(unit_campaign_id)
    if int(guard.get("guardVersion", 0)) != expected_guard_version:
        raise AppError(ErrorCode.CONFLICT, "Roster guard moved; re-read the roster", details={"reason": "ACTIVE_GUARD"})
    return member, campaign, profile_id


def _raise_removal_cancel(exc: TransactionCancelledError, plan: List[Dict[str, Any]], marker: Dict[str, Any]) -> None:
    """Map a removal-plan cancellation to its domain error (never returns)."""
    if plan.index(marker) in exc.failed_indexes:
        raise AppError(
            ErrorCode.CONFLICT, "Request is being processed concurrently; retry to read the result"
        ) from None
    if 0 in exc.failed_indexes:
        raise AppError(
            ErrorCode.CONFLICT, "Membership was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        ) from None
    if 1 in exc.failed_indexes:
        raise AppError(
            ErrorCode.CONFLICT, "Roster guard moved; re-read the roster", details={"reason": "ACTIVE_GUARD"}
        ) from None
    raise exc


def _remove_unit_campaign_membership(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    campaign_id = require_bounded_str(args, "campaignId", 100)
    expected_membership_version = require_version(args, "expectedMembershipVersion")
    expected_guard_version = require_version(args, "expectedGuardVersion")
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "removeUnitCampaignMembership")
    if replayed is not None:
        return replayed

    member, _campaign, profile_id = _load_membership_for_removal(
        unit_campaign_id, campaign_id, expected_membership_version, expected_guard_version, caller
    )

    now = _utcnow()
    stamp = _iso(now)
    merged = {
        **member,
        "status": MEMBER_REMOVED,
        "removedByAccountId": caller,
        "removedAt": stamp,
        "version": expected_membership_version + 1,
    }
    result = _membership_to_graphql(merged, expected_guard_version + 1)
    marker = _marker_put(caller, "removeUnitCampaignMembership", key, fingerprint, result, _epoch(now))
    plan = _removal_plan(
        unit_campaign_id,
        profile_id,
        campaign_id,
        caller,
        stamp,
        expected_membership_version,
        expected_guard_version,
        marker,
    )
    try:
        execute_transaction(plan)
    except TransactionCancelledError as exc:
        _raise_removal_cancel(exc, plan, marker)
    return result


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _page_args(event: Dict[str, Any]) -> tuple[int, Optional[str]]:
    page = event.get("arguments", {}).get("page") or {}
    limit = validate_page_limit(page.get("limit"))
    return limit, page.get("cursor")


def _get_unit_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    caller = _require_caller(event)
    response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    require_unit_admin(tables.units, item["unitId"], caller)
    return _campaign_to_graphql(item)


def _list_unit_campaigns(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    caller = _require_caller(event)
    require_unit_admin(tables.units, unit_id, caller)
    is_active = args.get("isActive")
    if is_active is not None and not isinstance(is_active, bool):
        raise AppError(ErrorCode.INVALID_INPUT, "isActive must be a boolean")
    limit, cursor = _page_args(event)
    kwargs: Dict[str, Any] = {
        "IndexName": UNIT_CREATED_INDEX,
        "KeyConditionExpression": Key("unitId").eq(unit_id),
        "Limit": limit,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor, f"unitCampaigns:{unit_id}:{is_active}")
    raw_items, last_key = _filtered_pages(
        tables.unit_campaigns.query,
        kwargs,
        limit,
        lambda item: (
            item.get("itemKey") == METADATA_ITEM_KEY
            and (is_active is None or bool(item.get("isActive", True)) == is_active)
        ),
    )
    items = [_campaign_to_graphql(item) for item in raw_items]
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"unitCampaigns:{unit_id}:{is_active}", last_key) if last_key else None,
            "hasNextPage": last_key is not None,
        },
    }


def _unit_campaign_roster(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    caller = _require_caller(event)
    _require_uc_admin(unit_campaign_id, caller)
    status = args.get("status")
    if status is not None and status not in (MEMBER_ACTIVE, MEMBER_REMOVED):
        raise AppError(ErrorCode.INVALID_INPUT, "status must be ACTIVE or REMOVED")
    limit, cursor = _page_args(event)
    guard_version = int(_get_guard_row(unit_campaign_id).get("guardVersion", 0))
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": Key("unitCampaignId").eq(unit_campaign_id) & Key("itemKey").begins_with("MEMBER#"),
        "Limit": limit,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor, f"roster:{unit_campaign_id}:{status}")
    raw_items, last_key = _filtered_pages(
        tables.unit_campaigns.query,
        kwargs,
        limit,
        lambda item: item.get("itemKey", "").startswith("MEMBER#") and (status is None or item.get("status") == status),
    )
    items = [_membership_to_graphql(item, guard_version) for item in raw_items]
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"roster:{unit_campaign_id}:{status}", last_key) if last_key else None,
            "hasNextPage": last_key is not None,
        },
    }


def _unit_campaign_catalog(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_campaign_id = require_bounded_str(args, "unitCampaignId", 100)
    caller = _require_caller(event)
    unit_campaign = _require_uc_admin(unit_campaign_id, caller)
    catalog_id = unit_campaign["catalogId"]
    catalog_response = tables.catalogs.get_item(Key={"catalogId": catalog_id}, ConsistentRead=True)
    catalog = catalog_response.get("Item")
    if not isinstance(catalog, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Catalog not found")
    return {
        "catalogId": catalog_id,
        "catalogName": catalog.get("catalogName", ""),
        "products": catalog.get("products", []),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "createUnitCampaign": _create_unit_campaign,
    "updateUnitCampaign": _update_unit_campaign,
    "joinUnitCampaign": _join_unit_campaign,
    "removeUnitCampaignMembership": _remove_unit_campaign_membership,
    "unitCampaign": _get_unit_campaign,
    "unitCampaigns": _list_unit_campaigns,
    "unitCampaignRoster": _unit_campaign_roster,
    "unitCampaignCatalog": _unit_campaign_catalog,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch a Unit Campaign operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported Unit Campaign operation: {field_name}")
    return operation(event, context)
