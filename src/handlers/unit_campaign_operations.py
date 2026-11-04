"""Show & Sell Unit Campaign operations.

Wave 2, batch B (leaves 1.4.1-1.4.3, 1.5.1-1.5.6): Unit Campaign persistence,
membership with the Scout-campaign guard, create/update mutations, the join-code
redemption flow, removal, and the admin query surface.

The join transaction is deliberately single-transaction (data model §8.2): the
membership row, the Scout-campaign guard, and the Campaign's joined-scope link
commit all-or-nothing, so a partial join cannot leave the guard pointing at a
membership that failed to commit. DynamoDB rejects the whole transaction when
any condition fails (data model §8.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

try:  # pragma: no cover
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.import_fallback import import_from_utils

get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
check_profile_access = import_from_utils("auth", "check_profile_access")
try:
    from utils.mutations import IdempotentMutationRunner, WritePlan, marker_keys, normalized_fingerprint
except ModuleNotFoundError:
    from ..utils.mutations import IdempotentMutationRunner, WritePlan, marker_keys, normalized_fingerprint

AppError, ErrorCode = import_from_utils("errors", "AppError", "ErrorCode")
get_logger = import_from_utils("logging", "get_logger")

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    with_error_handling = import_from_utils("handlers", "lambda_handler")

logger = get_logger(__name__)

MARKER_TABLE_KEY = "unit_campaigns"

# Data model §6.2 key shapes.
METADATA_SK = "METADATA"
MEMBERSHIP_GUARD_SK = "MEMBERSHIP_GUARD"
JOIN_CODE_KEY_PREFIX = "JOIN_CODE#"
UNIT_CAMPAIGN_KEY_PREFIX = "UNIT_CAMPAIGN#"
SCOUT_CAMPAIGN_KEY_PREFIX = "SCOUT_CAMPAIGN#"
MEMBERSHIP_SK_PREFIX = "MEMBERSHIP#"

# Data model §6.6: join codes are 16-character uppercase alphanumeric (same
# shape as Unit invites).
JOIN_CODE_LENGTH = 16
JOIN_CODE_MAX_ATTEMPTS = 5
JOIN_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Campaign name bound per the data model's adversarial-bound posture (the
# 100-char bound the catalog/campaign surfaces already carry).
MAX_CAMPAIGN_NAME_LENGTH = 100
# Campaign years are bounded so a malformed client cannot write nonsense rows;
# the window is deliberately generous.
MIN_CAMPAIGN_YEAR = 1900
MAX_CAMPAIGN_YEAR = 2200


def _serialize(value: Any) -> Any:
    from boto3.dynamodb.types import TypeSerializer

    return TypeSerializer().serialize(value)


def _uc() -> Any:
    return tables.unit_campaigns


def _campaigns() -> Any:
    return tables.campaigns


def _catalogs() -> Any:
    return tables.catalogs


def _units() -> Any:
    return tables.units


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _marker_keys(actor: Any, operation: str, scope: Any, key: str) -> Any:
    return marker_keys(
        actor_id=actor,
        operation=operation,
        scope=scope,
        idempotency_key=key,
        table_key=MARKER_TABLE_KEY,
        table_name=_uc().name if hasattr(_uc(), "name") else MARKER_TABLE_KEY,
    )


def _require_key(args: Dict[str, Any]) -> Any:
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    return key


def _expected_version(args: Dict[str, Any], field: str) -> int:
    """Spec-strict version validation: bools, floats, and numeric strings are
    not integers and are rejected with INVALID_INPUT (§8.10)."""
    raw = args.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must be an integer")
    return raw


def _expected_update_version(args: Dict[str, Any]) -> int:
    """updateUnitCampaign's version rides the wire shape
    ``args.version.expectedVersion`` (UpdateUnitCampaignInput.version is a
    VersionedInput, schema.graphql); a top-level ``expectedVersion`` is the
    direct-event fallback. The value the fingerprint excludes is the value
    this reads: a wire replay that carries a freshly read version under one
    key must fingerprint like the original under either shape."""
    version_input = args.get("version")
    raw = version_input.get("expectedVersion") if isinstance(version_input, dict) else None
    if raw is None:
        raw = args.get("expectedVersion")
    return _expected_version({"expectedVersion": raw}, "expectedVersion")


def _wire_put(table: Any, item: Dict[str, Any], condition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    action: Dict[str, Any] = {"TableName": table.name, "Item": {k: _serialize(v) for k, v in item.items()}}
    if condition:
        action.update(condition)
    return action


def _wire_update(
    table: Any,
    key: Dict[str, Any],
    update_expression: str,
    names: Dict[str, str],
    values: Dict[str, Any],
    condition: str,
) -> Dict[str, Any]:
    return {
        "TableName": table.name,
        "Key": {k: _serialize(v) for k, v in key.items()},
        "UpdateExpression": update_expression,
        "ConditionExpression": condition,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": {k: _serialize(v) for k, v in values.items()},
    }


def _is_unit_admin(caller: str, unit_id: str) -> bool:
    """Caller holds an active Unit Admin grant: the GRANT# row exists.

    Same contract as batch A's unit_operations: revoked grants are deleted
    rows, so row presence (batch A's try/except transport fallback included)
    is the whole check.
    """
    try:
        response = _units().get_item(Key={"pk": f"UNIT#{unit_id}", "sk": f"GRANT#{caller}"}, ConsistentRead=True)
    except Exception:
        return False
    return response.get("Item") is not None


def _require_admin(caller: str, unit_id: str) -> None:
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")


def _get_unit_campaign(unit_campaign_id: str) -> Any:
    """Strongly consistent base-table read of the Unit Campaign metadata row."""
    response = _uc().get_item(
        Key={"pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}", "sk": METADATA_SK},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, f"Unit campaign {unit_campaign_id} not found")
    return item


def _validate_campaign_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_CAMPAIGN_NAME_LENGTH:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "campaignName must be a non-empty string of at most 100 characters",
        )
    return name


def _validate_campaign_year(year: Any) -> int:
    """Integer years 1900-2200. Numeric strings coerce (spec), integral floats
    are accepted (GraphQL Int may surface as a float), but bools and
    fractional floats are NOT integers and are rejected (§8.10)."""
    if isinstance(year, bool) or (isinstance(year, float) and not year.is_integer()):
        raise AppError(ErrorCode.INVALID_INPUT, "campaignYear must be an integer")
    try:
        coerced = int(year)
    except TypeError, ValueError:
        raise AppError(ErrorCode.INVALID_INPUT, "campaignYear must be an integer") from None
    if coerced < MIN_CAMPAIGN_YEAR or coerced > MAX_CAMPAIGN_YEAR:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"campaignYear must be between {MIN_CAMPAIGN_YEAR} and {MAX_CAMPAIGN_YEAR}",
        )
    return coerced


def _validate_join_code_shape(join_code: Any) -> str:
    """Malformed codes are NOT_FOUND so code shape is not an existence oracle."""
    if not isinstance(join_code, str):
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    code = join_code.upper().strip()
    if len(code) != JOIN_CODE_LENGTH or any(ch not in JOIN_CODE_ALPHABET for ch in code):
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    return code


def _get_join_target(join_code: str) -> Any:
    """Resolve a join code to the ACTIVE Unit Campaign it points at.

    Every miss - unknown code, dangling pointer, missing or inactive campaign -
    is NOT_FOUND (UNIT-Q-06, CAMP-M-03-04), so a caller learns nothing about
    whether a different Unit exists behind a code they cannot redeem.
    """
    # The pointer's sk is UNIT_CAMPAIGN#<id> (data model §6.2), so a code-only
    # read is a base-table query by pk, not a get_item.
    pointer_items = (
        _uc()
        .query(
            KeyConditionExpression=Key("pk").eq(f"{JOIN_CODE_KEY_PREFIX}{join_code}"),
            ConsistentRead=True,
            Limit=1,
        )
        .get("Items", [])
    )
    pointer = pointer_items[0] if pointer_items else None
    unit_campaign_id = pointer.get("unitCampaignId") if pointer else None
    if not unit_campaign_id:
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    campaign = _get_unit_campaign(unit_campaign_id)
    if not campaign.get("isActive"):
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    return campaign


def _catalog_usable_by(catalog_id: str, caller: str) -> Any:
    """Usable catalog per the #706/#509 visibility contract shared with getCatalog.

    Unknown, soft-deleted, or invisible catalogs are NOT_FOUND (never FORBIDDEN)
    so existence is not disclosed to a caller without access.
    """
    response = _catalogs().get_item(Key={"catalogId": catalog_id}, ConsistentRead=True)
    catalog = response.get("Item")
    if not catalog or catalog.get("isDeleted"):
        raise AppError(ErrorCode.NOT_FOUND, "Catalog not found")
    if not (
        catalog.get("isPublic")
        or catalog.get("catalogType") == "ADMIN_MANAGED"
        or catalog.get("ownerAccountId") == caller
    ):
        raise AppError(ErrorCode.NOT_FOUND, "Catalog not found")
    return catalog


def _reserve_join_code() -> str:
    """Generate a join code that does not collide with a live pointer.

    The pointer row itself carries attribute_not_exists in the create
    transaction, so a collision surfaces as a transaction CONFLICT; the
    pre-check plus bounded regeneration keeps that race vanishingly rare and
    makes collision handling observable in tests.
    """
    for _ in range(JOIN_CODE_MAX_ATTEMPTS):
        code = uuid.uuid4().hex[:JOIN_CODE_LENGTH].upper()
        existing = (
            _uc()
            .query(
                KeyConditionExpression=Key("pk").eq(f"{JOIN_CODE_KEY_PREFIX}{code}"),
                Limit=1,
            )
            .get("Items")
        )
        if not existing:
            return code
    raise AppError(ErrorCode.INTERNAL_ERROR, "Could not allocate a unique join code")


def _load_membership_result(result_id: str) -> Any:
    """Load a membership by its stored result id ``<unitCampaignId>#<profileId>``."""
    unit_campaign_id, profile_id = result_id.split("#", 1)
    item = (
        _uc()
        .get_item(
            Key={
                "pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}",
                "sk": f"{MEMBERSHIP_SK_PREFIX}{profile_id}",
            },
            ConsistentRead=True,
        )
        .get("Item")
    )
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "Membership not found")
    return item


# ---------------------------------------------------------------------------
# createUnitCampaign / updateUnitCampaign (leaves 1.5.1, 1.5.2)
# ---------------------------------------------------------------------------


def _campaign_wire_item(
    unit_campaign_id: str,
    unit_id: str,
    campaign_name: str,
    campaign_year: int,
    catalog_id: str,
    join_code: str,
    caller: str,
    now: str,
) -> Dict[str, Any]:
    return {
        "pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}",
        "sk": METADATA_SK,
        "unitCampaignId": unit_campaign_id,
        "unitId": unit_id,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "catalogId": catalog_id,
        "joinCode": join_code,
        "isActive": True,
        "version": 1,
        "createdByAccountId": caller,
        "updatedByAccountId": caller,
        "createdAt": now,
        "updatedAt": now,
    }


def _create_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate createUnitCampaign input shape; authz runs after the replay gate."""
    unit_id = args.get("unitId")
    if not unit_id or not isinstance(unit_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitId is required")
    campaign_name = _validate_campaign_name(args.get("campaignName"))
    campaign_year = _validate_campaign_year(args.get("campaignYear"))
    raw_catalog_id = args.get("catalogId")
    if not raw_catalog_id or not isinstance(raw_catalog_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "catalogId is required")
    catalog_id = raw_catalog_id if raw_catalog_id.startswith("CATALOG#") else f"CATALOG#{raw_catalog_id}"
    return {
        "unit_id": unit_id,
        "campaign_name": campaign_name,
        "campaign_year": campaign_year,
        "catalog_id": catalog_id,
    }


def _unit_exists(unit_id: str) -> None:
    """The target Unit must exist before any admin decision (NOT_FOUND first)."""
    item = _units().get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"}, ConsistentRead=True).get("Item")
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "Unit not found")


def _create_authz(bundle: Dict[str, Any], caller: str) -> None:
    """Existing-unit check, Unit Admin grant, then the usable-catalog check."""
    _unit_exists(bundle["unit_id"])
    _require_admin(caller, bundle["unit_id"])
    _catalog_usable_by(bundle["catalog_id"], caller)


def _create_fingerprint(args: Dict[str, Any]) -> Any:
    return normalized_fingerprint(
        {
            "unitId": args.get("unitId"),
            "campaignName": args.get("campaignName"),
            "campaignYear": args.get("campaignYear"),
            "catalogId": args.get("catalogId"),
        },
        drop_none=True,
    )


@with_error_handling(error_message="Failed to create Unit campaign")
def create_unit_campaign(event: Dict[str, Any], context: Any) -> Any:
    """Create a Unit Campaign with a reusable join code (CAMP-M-01)."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments", {}).get("input") or {}
    bundle = _create_input(args)
    key = _require_key(args)
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "createUnitCampaign", bundle["unit_id"], key)
    handled, replayed = runner.replay_or_reject(
        mk, _create_fingerprint(args), operation="createUnitCampaign", load_result=_get_unit_campaign
    )
    if handled:
        return replayed
    _create_authz(bundle, caller)

    join_code = _reserve_join_code()
    unit_campaign_id = f"uc-{uuid.uuid4().hex[:12]}"
    now = _now()
    campaign_item = _campaign_wire_item(
        unit_campaign_id,
        bundle["unit_id"],
        bundle["campaign_name"],
        bundle["campaign_year"],
        bundle["catalog_id"],
        join_code,
        caller,
        now,
    )
    pointer_item = {
        "pk": f"{JOIN_CODE_KEY_PREFIX}{join_code}",
        "sk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}",
        "unitCampaignId": unit_campaign_id,
        "createdAt": now,
    }
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=_create_fingerprint(args), result_id=unit_campaign_id)
    plan.add("Put", _wire_put(_uc(), campaign_item, {"ConditionExpression": "attribute_not_exists(pk)"}))
    plan.add(
        "Put",
        _wire_put(
            _uc(),
            pointer_item,
            {
                "ConditionExpression": "attribute_not_exists(#pk)",
                "ExpressionAttributeNames": {"#pk": "pk"},
            },
        ),
    )
    result = runner.execute(
        mk, plan, operation="createUnitCampaign", fingerprint=_create_fingerprint(args), result_id=unit_campaign_id
    )
    if isinstance(result, dict):
        return result
    return campaign_item


def _update_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate updateUnitCampaign input; only name/year/isActive are mutable."""
    name = args.get("campaignName")
    year = args.get("campaignYear")
    is_active = args.get("isActive")
    if name is not None:
        name = _validate_campaign_name(name)
    if year is not None:
        year = _validate_campaign_year(year)
    if is_active is not None and not isinstance(is_active, bool):
        raise AppError(ErrorCode.INVALID_INPUT, "isActive must be a boolean")
    return {"name": name, "year": year, "is_active": is_active}


def _update_fingerprint(args: Dict[str, Any]) -> Any:
    # The concurrency version is not request content: a retry legitimately
    # carries a freshly read version, under either wire shape.
    return normalized_fingerprint(
        {k: v for k, v in args.items() if k not in ("idempotency", "version", "expectedVersion")}
    )


def _apply_campaign_updates(current: Dict[str, Any], bundle: Dict[str, Any], caller: str, now: str) -> Dict[str, Any]:
    """The post-update campaign item: only name/year/isActive ever change."""
    next_item = dict(current)
    if bundle["name"] is not None:
        next_item["campaignName"] = bundle["name"]
    if bundle["year"] is not None:
        next_item["campaignYear"] = bundle["year"]
    if bundle["is_active"] is not None:
        next_item["isActive"] = bundle["is_active"]
    next_item["version"] = int(current.get("version", 1)) + 1
    next_item["updatedAt"] = now
    next_item["updatedByAccountId"] = caller
    return next_item


@with_error_handling(error_message="Failed to update Unit campaign")
def update_unit_campaign(event: Dict[str, Any], context: Any) -> Any:
    """Update name/year/isActive; catalogId is immutable (CAMP-M-02, CAMP-M-02-02)."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments", {}).get("input") or {}
    unit_campaign_id = args.get("unitCampaignId")
    if not unit_campaign_id or not isinstance(unit_campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    bundle = _update_input(args)
    key = _require_key(args)
    fingerprint = _update_fingerprint(args)
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "updateUnitCampaign", unit_campaign_id, key)
    handled, replayed = runner.replay_or_reject(
        mk, fingerprint, operation="updateUnitCampaign", load_result=_get_unit_campaign
    )
    if handled:
        return replayed

    current = _get_unit_campaign(unit_campaign_id)
    _require_admin(caller, current["unitId"])
    current_version = int(current.get("version", 1))
    if _expected_update_version(args) != current_version:
        raise AppError(ErrorCode.CONFLICT, "Unit campaign has been modified")

    next_item = _apply_campaign_updates(current, bundle, caller, _now())
    return _run_update_transaction(runner, mk, fingerprint, unit_campaign_id, next_item)


def _run_update_transaction(
    runner: Any, mk: Any, fingerprint: str, unit_campaign_id: str, next_item: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute the staged update plan and answer replays with the stored campaign."""
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fingerprint, result_id=unit_campaign_id)
    plan.add(
        "Put",
        _wire_put(
            _uc(),
            next_item,
            {
                "ConditionExpression": "#v = :v",
                "ExpressionAttributeNames": {"#v": "version"},
                "ExpressionAttributeValues": {":v": _serialize(int(next_item["version"]) - 1)},
            },
        ),
    )
    result = runner.execute(
        mk, plan, operation="updateUnitCampaign", fingerprint=fingerprint, result_id=unit_campaign_id
    )
    if isinstance(result, dict):
        return result
    return next_item


# ---------------------------------------------------------------------------
# joinUnitCampaign / removeUnitCampaignMembership (leaves 1.5.4, 1.5.5)
# ---------------------------------------------------------------------------


def _find_scout_campaign(campaign_id: str) -> Any:
    """Locate the Scout campaign by GSI (discovery only), then read it consistently.

    The GSI query only locates the base-table key; every authorization and
    join decision reads the strongly consistent base item (#438/#545 posture).
    """
    response = _campaigns().query(
        IndexName="campaignId-index",
        KeyConditionExpression=Key("campaignId").eq(campaign_id),
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    profile_id = items[0]["profileId"]
    campaign = (
        _campaigns().get_item(Key={"profileId": profile_id, "campaignId": campaign_id}, ConsistentRead=True).get("Item")
    )
    if not campaign:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    return campaign


def _find_membership_for_campaign(unit_campaign_id: str, campaign_id: str) -> Any:
    """The membership row (any status) linking this Scout campaign to this Unit Campaign."""
    response = _uc().query(
        IndexName="campaignId-index",
        KeyConditionExpression=Key("campaignId").eq(campaign_id),
    )
    for item in response.get("Items", []):
        if item.get("unitCampaignId") == unit_campaign_id and item.get("sk", "").startswith(MEMBERSHIP_SK_PREFIX):
            profile_id = item["sk"][len(MEMBERSHIP_SK_PREFIX) :]
            return (
                _uc()
                .get_item(
                    Key={
                        "pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}",
                        "sk": f"{MEMBERSHIP_SK_PREFIX}{profile_id}",
                    },
                    ConsistentRead=True,
                )
                .get("Item")
            )
    return None


def _read_guard(campaign_id: str) -> Any:
    return (
        _uc()
        .get_item(
            Key={"pk": f"{SCOUT_CAMPAIGN_KEY_PREFIX}{campaign_id}", "sk": MEMBERSHIP_GUARD_SK},
            ConsistentRead=True,
        )
        .get("Item")
    )


def _require_guard(campaign_id: str) -> Any:
    guard = _read_guard(campaign_id)
    if not guard:
        raise AppError(ErrorCode.NOT_FOUND, "Membership not found")
    return guard


def _guard_target_check(guard: Optional[Dict[str, Any]], unit_campaign_id: str) -> None:
    """The guard is the authoritative cross-campaign join lock (§8.2).

    A null guard target means no ACTIVE membership; any other non-matching
    target means this Scout campaign is joined elsewhere (CAMP-M-03-03).
    """
    active_target = guard.get("activeUnitCampaignId") if guard else None
    if active_target is not None and active_target != unit_campaign_id:
        raise AppError(
            ErrorCode.CONFLICT,
            "This campaign already has an active Unit Campaign membership",
        )


def _membership_identity_check(membership: Dict[str, Any], profile_id: str) -> None:
    """The roster identity must match the Scout campaign's profile (1.5.4)."""
    if membership.get("profileId") != profile_id:
        raise AppError(ErrorCode.CONFLICT, "Membership identity does not match the campaign profile")


def _join_membership_create_item(
    unit_campaign: Dict[str, Any], campaign_id: str, profile_id: str, caller: str, now: str
) -> Dict[str, Any]:
    return {
        "pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign['unitCampaignId']}",
        "sk": f"{MEMBERSHIP_SK_PREFIX}{profile_id}",
        "unitCampaignId": unit_campaign["unitCampaignId"],
        "unitId": unit_campaign["unitId"],
        "campaignId": campaign_id,
        "profileId": profile_id,
        "status": "ACTIVE",
        "joinedByAccountId": caller,
        "joinedAt": now,
        "version": 1,
    }


def _join_membership_rejoin_item(membership: Dict[str, Any], caller: str, now: str) -> Dict[str, Any]:
    """The rejoined membership: old removal audit fields cleared, versions incremented."""
    previous_version = int(membership.get("version", 1))
    item = {
        **membership,
        "status": "ACTIVE",
        "joinedByAccountId": caller,
        "joinedAt": now,
        "version": previous_version + 1,
    }
    # A full-Put rejoin clears the removal audit attributes (§1.5.4).
    item.pop("removedByAccountId", None)
    item.pop("removedAt", None)
    return item


def _membership_wire_put(next_membership: Dict[str, Any], previous_version: int) -> Dict[str, Any]:
    """Rejoin wires as a full Put: clears removed* attributes dropped from the item."""
    return _wire_put(
        _uc(),
        next_membership,
        {
            "ConditionExpression": "#v = :v",
            "ExpressionAttributeNames": {"#v": "version"},
            "ExpressionAttributeValues": {":v": _serialize(previous_version)},
        },
    )


def _membership_wire_create(next_membership: Dict[str, Any]) -> Dict[str, Any]:
    return _wire_put(
        _uc(),
        next_membership,
        {
            "ConditionExpression": "attribute_not_exists(#pk)",
            "ExpressionAttributeNames": {"#pk": "pk"},
        },
    )


def _join_guard_wire_put(
    campaign_id: str,
    profile_id: str,
    guard: Optional[Dict[str, Any]],
    unit_campaign_id: str,
    membership: Dict[str, Any],
    now: str,
) -> Dict[str, Any]:
    """Guard write: activeUnitCampaignId set, membershipVersion mirrors the membership."""
    key = {"pk": f"{SCOUT_CAMPAIGN_KEY_PREFIX}{campaign_id}", "sk": MEMBERSHIP_GUARD_SK}
    if guard:
        # The target check is part of the condition, not just a pre-read: the
        # guard row is the authoritative join lock, and only the transaction
        # can hold it (§8.2, CAMP-M-03). ``:a`` doubles as the SET value.
        return _wire_update(
            _uc(),
            key,
            "SET #a = :a, #mv = :mv, #u = :u",
            {"#a": "activeUnitCampaignId", "#mv": "membershipVersion", "#u": "updatedAt"},
            {
                ":a": unit_campaign_id,
                ":mv": membership["version"],
                ":u": now,
                ":pmv": int(guard.get("membershipVersion", 0)),
            },
            "#mv = :pmv AND (#a = :a OR attribute_not_exists(#a))",
        )
    guard_item = {
        **key,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "activeUnitCampaignId": unit_campaign_id,
        "membershipVersion": membership["version"],
        "updatedAt": now,
    }
    return _wire_put(
        _uc(),
        guard_item,
        {
            "ConditionExpression": "attribute_not_exists(#pk)",
            "ExpressionAttributeNames": {"#pk": "pk"},
        },
    )


def _scout_link_wire_update(profile_id: str, campaign_id: str, unit_campaign: Dict[str, Any]) -> Dict[str, Any]:
    """The Campaign's joined-scope link, written in the same transaction (§8.2).

    The campaigns table's hash key attribute is ``profileId`` (V2 schema), so
    the existence condition must name it — ``attribute_exists(pk)`` would fail
    on every join.
    """
    return _wire_update(
        _campaigns(),
        {"profileId": profile_id, "campaignId": campaign_id},
        "SET #u = :u, #uc = :uc",
        {"#u": "unitId", "#uc": "unitCampaignId", "#p": "profileId"},
        {":u": unit_campaign["unitId"], ":uc": unit_campaign["unitCampaignId"]},
        "attribute_exists(#p)",
    )


def _join_fingerprint(bundle: Dict[str, Any]) -> Any:
    """Over the join pair: the code locates the Unit Campaign, campaignId the
    Scout campaign; a different pair under one key is IDEM-02."""
    return normalized_fingerprint({"joinCode": bundle["join_code"], "campaignId": bundle["campaign_id"]})


def _join_input(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("arguments", {}).get("input") or {}
    join_code = _validate_join_code_shape(args.get("joinCode"))
    campaign_id = args.get("campaignId")
    if not campaign_id or not isinstance(campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "campaignId is required")
    return {"join_code": join_code, "campaign_id": campaign_id}


def _join_membership_wire_action(
    membership: Optional[Dict[str, Any]],
    unit_campaign: Dict[str, Any],
    campaign_id: str,
    profile_id: str,
    caller: str,
    now: str,
) -> Dict[str, Any]:
    if membership is None:
        return _membership_wire_create(
            _join_membership_create_item(unit_campaign, campaign_id, profile_id, caller, now)
        )
    previous_version = int(membership.get("version", 1))
    return _membership_wire_put(_join_membership_rejoin_item(membership, caller, now), previous_version)


def _active_unit_ids_for_caller(caller: str) -> set[str]:
    """Unit ids the caller holds an ACTIVE membership in (units table §5.2).

    The accountId-unitId-index projects grant rows too, so the sk filter is
    load-bearing; only MEMBERSHIP# rows with status ACTIVE count.
    """
    response = _units().query(
        IndexName="accountId-unitId-index",
        KeyConditionExpression=Key("accountId").eq(caller),
    )
    return {
        item["unitId"]
        for item in response.get("Items", [])
        if item.get("sk", "").startswith("MEMBERSHIP#") and item.get("status") == "ACTIVE" and item.get("unitId")
    }


def _require_unit_membership(caller: str, unit_campaign: Dict[str, Any]) -> None:
    """The caller must be an active member of the Unit; a valid code for
    another Unit resolves to NOT_FOUND so codes are not an existence oracle
    (CAMP-M-03-04)."""
    if unit_campaign["unitId"] not in _active_unit_ids_for_caller(caller):
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")


def _join_resolution(
    caller: str, campaign_id: str, unit_campaign: Dict[str, Any]
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
    """Authorization + state resolution for a join: unit membership, campaign
    WRITE access, guard lock, and the existing membership row (any status)."""
    _require_unit_membership(caller, unit_campaign)
    scout_campaign = _find_scout_campaign(campaign_id)
    profile_id = scout_campaign["profileId"]
    if not check_profile_access(caller, profile_id, "WRITE"):
        raise AppError(ErrorCode.FORBIDDEN, "Write access to the campaign profile is required")
    guard = _read_guard(campaign_id)
    _guard_target_check(guard, unit_campaign["unitCampaignId"])
    membership = _find_membership_for_campaign(unit_campaign["unitCampaignId"], campaign_id)
    if membership and membership.get("status") == "ACTIVE":
        raise AppError(
            ErrorCode.CONFLICT,
            "This campaign already has an active membership in this Unit Campaign",
        )
    if membership:
        _membership_identity_check(membership, profile_id)
        profile_id = membership["profileId"]
    return guard, membership, profile_id


def _run_join_transaction(
    runner: Any,
    mk: Any,
    bundle: Dict[str, Any],
    caller: str,
    unit_campaign: Dict[str, Any],
    campaign_id: str,
    profile_id: str,
    guard: Optional[Dict[str, Any]],
    membership: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Stage and execute the single §8.2 transaction; replay answers with the
    stored membership."""
    now = _now()
    next_membership = (
        _join_membership_rejoin_item(membership, caller, now)
        if membership
        else _join_membership_create_item(unit_campaign, campaign_id, profile_id, caller, now)
    )
    plan = WritePlan()
    result_id = f"{unit_campaign['unitCampaignId']}#{profile_id}"
    runner.stage_marker(plan, mk, fingerprint=_join_fingerprint(bundle), result_id=result_id)
    plan.add("Put", _join_membership_wire_action(membership, unit_campaign, campaign_id, profile_id, caller, now))
    # A never-joined Scout campaign gets a guard Put; an existing guard (any
    # history) is version-conditioned Updated.
    plan.add(
        "Update" if guard else "Put",
        _join_guard_wire_put(campaign_id, profile_id, guard, unit_campaign["unitCampaignId"], next_membership, now),
    )
    plan.add("Update", _scout_link_wire_update(profile_id, campaign_id, unit_campaign))
    result = runner.execute(
        mk, plan, operation="joinUnitCampaign", fingerprint=_join_fingerprint(bundle), result_id=result_id
    )
    if isinstance(result, dict):
        return result
    return next_membership


@with_error_handling(error_message="Failed to join Unit campaign")
def join_unit_campaign(event: Dict[str, Any], context: Any) -> Any:
    """Join a Scout campaign to a Unit Campaign by join code (CAMP-M-03).

    Single transaction: membership + guard + Campaign joined-scope link are
    all-or-nothing (data model §8.2). Authorization is a WRITE check on the
    Scout campaign's profile; the guard is the authoritative cross-campaign
    join lock (at most one ACTIVE membership per Scout campaign).
    """
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    bundle = _join_input(event)
    key = _require_key(event.get("arguments", {}).get("input") or {})
    # Replay short-circuits before the state reads below; the stored result id
    # is the membership key, so a completed retry returns the membership.
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "joinUnitCampaign", bundle["join_code"], key)
    handled, replayed = runner.replay_or_reject(
        mk, _join_fingerprint(bundle), operation="joinUnitCampaign", load_result=_load_membership_result
    )
    if handled:
        return replayed

    unit_campaign = _get_join_target(bundle["join_code"])
    guard, membership, profile_id = _join_resolution(caller, bundle["campaign_id"], unit_campaign)
    return _run_join_transaction(
        runner, mk, bundle, caller, unit_campaign, bundle["campaign_id"], profile_id, guard, membership
    )


def _remove_fingerprint(args: Dict[str, Any]) -> Any:
    return normalized_fingerprint(
        {
            "unitCampaignId": args.get("unitCampaignId"),
            "campaignId": args.get("campaignId"),
            "expectedMembershipVersion": args.get("expectedMembershipVersion"),
            "expectedGuardVersion": args.get("expectedGuardVersion"),
        }
    )


def _membership_removal_wire_update(
    membership: Dict[str, Any], caller: str, now: str, current_version: int, next_version: int
) -> Dict[str, Any]:
    return _wire_update(
        _uc(),
        {"pk": membership["pk"], "sk": membership["sk"]},
        "SET #s = :s, #rb = :rb, #ra = :ra, #v = :v",
        {"#s": "status", "#rb": "removedByAccountId", "#ra": "removedAt", "#v": "version"},
        {":s": "REMOVED", ":rb": caller, ":ra": now, ":v": next_version, ":pv": current_version},
        "#v = :pv",
    )


def _guard_removal_wire_update(
    campaign_id: str, unit_campaign_id: str, now: str, current_guard_version: int, next_version: int
) -> Dict[str, Any]:
    """Guard cleared on removal, and only when the guard still points at the
    membership being removed: a stale re-remove of a REMOVED row while the
    Scout campaign is actively joined to ANOTHER Unit Campaign must cancel the
    transaction, not silently unlink the campaign it is joined to (§8.2).
    The Campaign joined-scope link is NOT touched."""
    return _wire_update(
        _uc(),
        {"pk": f"{SCOUT_CAMPAIGN_KEY_PREFIX}{campaign_id}", "sk": MEMBERSHIP_GUARD_SK},
        "SET #mv = :mv, #u = :u REMOVE #a",
        {"#mv": "membershipVersion", "#u": "updatedAt", "#a": "activeUnitCampaignId"},
        {":mv": next_version, ":u": now, ":pmv": current_guard_version, ":uc": unit_campaign_id},
        "#mv = :pmv AND (attribute_not_exists(#a) OR #a = :uc)",
    )


def _require_membership(unit_campaign_id: str, profile_id: str) -> Any:
    """Direct base-table membership read by (unitCampaignId, profileId)."""
    item = (
        _uc()
        .get_item(
            Key={"pk": f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}", "sk": f"{MEMBERSHIP_SK_PREFIX}{profile_id}"},
            ConsistentRead=True,
        )
        .get("Item")
    )
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign membership not found")
    return item


def _remove_version_checks(args: Dict[str, Any], membership: Dict[str, Any], guard: Dict[str, Any]) -> int:
    """VER-01 on both versions: stale expectedMembership/GuardVersion is CONFLICT."""
    expected_membership_version = _expected_version(args, "expectedMembershipVersion")
    expected_guard_version = _expected_version(args, "expectedGuardVersion")
    current_membership_version = int(membership.get("version", 1))
    current_guard_version = int(guard.get("membershipVersion", 0))
    if expected_membership_version != current_membership_version:
        raise AppError(ErrorCode.CONFLICT, "Membership has been modified")
    if expected_guard_version != current_guard_version:
        raise AppError(ErrorCode.CONFLICT, "Membership guard has been modified")
    return current_membership_version


def _run_remove_transaction(
    runner: Any,
    mk: Any,
    fingerprint: str,
    result_id: str,
    membership: Dict[str, Any],
    campaign_id: str,
    caller: str,
    current_membership_version: int,
    current_guard_version: int,
) -> Dict[str, Any]:
    """Execute the removal transaction; the Campaign joined-scope link is untouched."""
    now = _now()
    next_membership_version = current_membership_version + 1
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fingerprint, result_id=result_id)
    plan.add(
        "Update",
        _membership_removal_wire_update(membership, caller, now, current_membership_version, next_membership_version),
    )
    plan.add(
        "Update",
        _guard_removal_wire_update(
            campaign_id, membership["unitCampaignId"], now, current_guard_version, next_membership_version
        ),
    )
    result = runner.execute(
        mk,
        plan,
        operation="removeUnitCampaignMembership",
        fingerprint=fingerprint,
        result_id=result_id,
    )
    if isinstance(result, dict):
        return result
    return {
        **membership,
        "status": "REMOVED",
        "removedByAccountId": caller,
        "removedAt": now,
        "version": next_membership_version,
    }


@with_error_handling(error_message="Failed to remove Unit campaign membership")
def remove_unit_campaign_membership(event: Dict[str, Any], context: Any) -> Any:
    """Remove a membership (Unit Admin only); campaign history and Orders keep their scope."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments", {}).get("input") or {}
    unit_campaign_id = args.get("unitCampaignId")
    if not unit_campaign_id or not isinstance(unit_campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    # The roster identity is the Scout campaign (RemoveUnitCampaignMembershipInput
    # carries campaignId, not profileId): its profile locates the membership key.
    campaign_id = args.get("campaignId")
    if not campaign_id or not isinstance(campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "campaignId is required")
    key = _require_key(args)
    fingerprint = _remove_fingerprint(args)
    # Replay short-circuits before the state reads below (IDEM-01): a completed
    # retry replays even if access or versions have since changed.
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "removeUnitCampaignMembership", unit_campaign_id, key)
    handled, replayed = runner.replay_or_reject(
        mk, fingerprint, operation="removeUnitCampaignMembership", load_result=_load_membership_result
    )
    if handled:
        return replayed

    # GSI locate (discovery only), then the strongly consistent base read
    # (#438/#545 posture): the profile the membership is keyed by.
    profile_id = _find_scout_campaign(campaign_id)["profileId"]
    membership = _require_membership(unit_campaign_id, profile_id)
    _require_admin(caller, membership["unitId"])
    guard_campaign_id = membership["campaignId"]
    guard = _require_guard(guard_campaign_id)
    current_membership_version = _remove_version_checks(args, membership, guard)
    current_guard_version = int(guard.get("membershipVersion", 0))

    return _run_remove_transaction(
        runner,
        mk,
        fingerprint,
        f"{unit_campaign_id}#{profile_id}",
        membership,
        guard_campaign_id,
        caller,
        current_membership_version,
        current_guard_version,
    )


# ---------------------------------------------------------------------------
# Queries (leaf 1.5.6)
# ---------------------------------------------------------------------------


def _parse_page(args: Dict[str, Any]) -> tuple[int, Any]:
    """The house PageInput contract: limit (default 50, clamped 1-100) and an
    opaque offset-string cursor (batch A ``unit_operations._parse_page``)."""
    page = args.get("page") or {}
    limit = page.get("limit", 50)
    try:
        limit = int(limit)
    except TypeError, ValueError:
        limit = 50
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    return limit, page.get("cursor")


def _paged(items: List[Dict[str, Any]], args: Dict[str, Any]) -> Dict[str, Any]:
    """Connection page over newest-first items: ``items`` plus ``pageInfo``.

    The cursor is a plain offset string issued by this resolver only (batch A
    pattern); an unparseable cursor restarts at zero rather than erroring.
    """
    limit, cursor = _parse_page(args)
    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0
    page_items = items[start : start + limit]
    next_cursor = str(start + limit) if start + limit < len(items) else None
    return {
        "items": page_items,
        "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None},
    }


@with_error_handling(error_message="Failed to resolve Unit campaign join info")
def unit_campaign_join_info(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Limited join preview: only Unit display name, campaign name/year, catalog name, active status."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments") or {}
    join_code = _validate_join_code_shape(args.get("joinCode"))
    campaign = _get_join_target(join_code)
    unit = (
        _units().get_item(Key={"pk": f"UNIT#{campaign['unitId']}", "sk": METADATA_SK}, ConsistentRead=True).get("Item")
    )
    if not unit:
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    catalog = _catalogs().get_item(Key={"catalogId": campaign["catalogId"]}, ConsistentRead=True).get("Item")
    if not catalog or catalog.get("isDeleted"):
        raise AppError(ErrorCode.NOT_FOUND, "Unknown join code")
    return {
        "unitDisplayName": unit.get("displayName"),
        "campaignName": campaign.get("campaignName"),
        "campaignYear": campaign.get("campaignYear"),
        "catalogName": catalog.get("catalogName"),
        "isActive": bool(campaign.get("isActive")),
    }


@with_error_handling(error_message="Failed to resolve Unit campaign")
def unit_campaign(event: Dict[str, Any], context: Any) -> Any:
    """Admin view of one Unit Campaign; non-admins get null (batch A `unit` precedent)."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    unit_campaign_id = (event.get("arguments") or {}).get("unitCampaignId")
    if not unit_campaign_id or not isinstance(unit_campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    campaign = _get_unit_campaign(unit_campaign_id)
    if not _is_unit_admin(caller, campaign["unitId"]):
        return None
    return campaign


def _unit_campaign_list_items(unit_id: str, is_active: Any) -> List[Dict[str, Any]]:
    """Metadata rows for a Unit's campaigns, newest first, with the in-memory
    active-state filter (the GSI is discovery only, same posture as batch A)."""
    response = _uc().query(
        IndexName="unitId-createdAt-index",
        KeyConditionExpression=Key("unitId").eq(unit_id),
    )
    items = [i for i in response.get("Items", []) if i.get("sk") == METADATA_SK]
    if is_active is not None:
        items = [i for i in items if bool(i.get("isActive")) == bool(is_active)]
    items.sort(key=lambda i: (i.get("createdAt") or "", i.get("unitCampaignId") or ""), reverse=True)
    return items


@with_error_handling(error_message="Failed to resolve Unit campaigns")
def unit_campaigns(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """A Unit's campaigns (unitId-createdAt-index is discovery only; filters run in memory)."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments") or {}
    unit_id = args.get("unitId")
    if not unit_id or not isinstance(unit_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitId is required")
    _require_admin(caller, unit_id)
    return _paged(_unit_campaign_list_items(unit_id, args.get("isActive")), args)


@with_error_handling(error_message="Failed to resolve Unit campaign catalog")
def unit_campaign_catalog(event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
    """The sales catalog behind a Unit Campaign; soft-deleted/missing catalogs resolve null."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    unit_campaign_id = (event.get("arguments") or {}).get("unitCampaignId")
    if not unit_campaign_id or not isinstance(unit_campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    campaign = _get_unit_campaign(unit_campaign_id)
    if not _is_unit_admin(caller, campaign["unitId"]):
        return None
    catalog = _catalogs().get_item(Key={"catalogId": campaign["catalogId"]}, ConsistentRead=True).get("Item")
    if not catalog or catalog.get("isDeleted"):
        return None
    return {
        "catalogId": catalog["catalogId"],
        "catalogName": catalog.get("catalogName"),
        "products": catalog.get("products", []),
    }


@with_error_handling(error_message="Failed to resolve Unit campaign roster")
def unit_campaign_roster(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """The membership roster; removed members stay visible until the cascade removes them."""
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    args = event.get("arguments") or {}
    unit_campaign_id = args.get("unitCampaignId")
    if not unit_campaign_id or not isinstance(unit_campaign_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitCampaignId is required")
    campaign = _get_unit_campaign(unit_campaign_id)
    _require_admin(caller, campaign["unitId"])
    response = _uc().query(
        KeyConditionExpression=Key("pk").eq(f"{UNIT_CAMPAIGN_KEY_PREFIX}{unit_campaign_id}")
        & Key("sk").begins_with(MEMBERSHIP_SK_PREFIX),
        ConsistentRead=True,
    )
    items = response.get("Items", [])
    if args.get("status") is not None:
        wanted = str(args["status"]).upper()
        items = [i for i in items if str(i.get("status", "")).upper() == wanted]
    items.sort(key=lambda i: (i.get("joinedAt") or "", i.get("profileId") or ""), reverse=True)
    return _paged(items, args)


def _dispatch(event: Dict[str, Any], context: Any) -> Any:
    field = (event.get("info") or {}).get("fieldName", "")
    handlers = {
        "createUnitCampaign": create_unit_campaign,
        "updateUnitCampaign": update_unit_campaign,
        "joinUnitCampaign": join_unit_campaign,
        "removeUnitCampaignMembership": remove_unit_campaign_membership,
        "unitCampaignJoinInfo": unit_campaign_join_info,
        "unitCampaign": unit_campaign,
        "unitCampaigns": unit_campaigns,
        "unitCampaignCatalog": unit_campaign_catalog,
        "unitCampaignRoster": unit_campaign_roster,
    }
    handler = handlers.get(field)
    if handler is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unknown field: {field}")
    return handler(event, context)


lambda_handler = with_error_handling(error_message="Unit campaign operation failed")(_dispatch)
