"""Unit mutation handlers (delivery checklist §1.2).

One Lambda serves the three Stage 1 Unit write surfaces, routed on
``info.fieldName`` exactly as ``public_orders_router`` routes the public-orders
Lambda, and driven by the event shape the Stage 1 fixtures build
(``tests/unit/show_sell_fixtures.unit_operation_event``):

- ``createUnit`` (§1.2.1) — any authenticated Account becomes the Unit's first
  admin; the Unit, the creator grant, and the bootstrap-scope idempotency marker
  commit in one transaction.
- ``updateUnit`` (§1.2.2) — a current Unit Admin plus ``expectedVersion``; only
  metadata/settings fields are writable, and the exact-geography duplicate gate
  runs again when the geography changes.
- ``revokeUnitAccessGrant`` (§1.2.3) — a current Unit Admin plus
  ``expectedVersion`` plus ``adminCount > 1``; deletes exactly one grant and
  decrements the authoritative count in the same transaction.

Nothing here re-derives what Stage 1 already established: identity, settings
validation and item shape come from :mod:`src.utils.unit_models`, authorization
from :mod:`src.utils.unit_auth`, and the idempotency/conditional-write contract
from :mod:`src.utils.mutations` — marker staged first in the plan, 90-action
counting, ``CONFLICT`` versus ``RESOURCE_BUSY`` classification.

Every plan here is 3 actions, so the 90-action ceiling is nowhere near binding
at Stage 1; the writes still go through ``WritePlan`` so a later stage cannot
grow a plan without being counted. Grant rows and ``adminCount`` have one write
owner: this module plus ``redeemUnitInvite`` (§1.3.2), which is what makes the
add/revoke race resolvable by condition alone.

Error details (the ``DUPLICATE_UNIT_METADATA`` subcode) stay on the ``AppError``:
``utils.handlers.lambda_handler`` forwards only ``errorCode`` and ``message``
across the Lambda boundary, and forwarding an allowlisted subcode into GraphQL
``extensions`` is the AppSync JS resolver's job (impact map §3.1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, cast

from botocore.exceptions import ClientError

try:  # pragma: no cover
    from utils import unit_auth, unit_models
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils import unit_auth, unit_models
    from ..utils.import_fallback import import_from_utils


AppError, ErrorCode = import_from_utils("errors", "AppError", "ErrorCode")
get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
batch_get_chunked = import_from_utils("dynamodb", "batch_get_chunked")
get_dynamodb_client = import_from_utils("dynamodb", "get_dynamodb_client")
ensure_account_id = import_from_utils("ids", "ensure_account_id")
paginate_page = import_from_utils("pagination", "paginate_page")
get_logger = import_from_utils("logging", "get_logger")
(
    BOOTSTRAP_SCOPE,
    IdempotentMutationRunner,
    WritePlan,
    marker_keys,
    normalized_fingerprint,
    utc_now_iso,
) = import_from_utils(
    "mutations",
    "BOOTSTRAP_SCOPE",
    "IdempotentMutationRunner",
    "WritePlan",
    "marker_keys",
    "normalized_fingerprint",
    "utc_now_iso",
)
# ``unit_auth`` and ``unit_models`` are imported as modules rather than unpacked
# into locals: the name list they expose is long, and a name-by-name unpack is
# ordering-sensitive wiring that fails silently when either side gains a symbol.
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.errors import AppError as AppErrorType
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    with_error_handling = import_from_utils("handlers", "lambda_handler")

CREATE_UNIT_FIELD = "createUnit"
UPDATE_UNIT_FIELD = "updateUnit"
REVOKE_GRANT_FIELD = "revokeUnitAccessGrant"
CREATE_INVITE_FIELD = "createUnitInvite"
REDEEM_INVITE_FIELD = "redeemUnitInvite"
REVOKE_INVITE_FIELD = "revokeUnitInvite"
UNIT_INVITES_FIELD = "unitInvites"
MY_UNITS_FIELD = "myUnits"
UNIT_FIELD = "unit"
UNIT_ADMINS_FIELD = "unitAdmins"

MAX_ACTIVE_UNIT_INVITES = 20
INVITE_FAILURES_PER_HOUR = 10
# The §6.6 counter contract on the existing throttle table: its own key prefix
# and window bucket keep it apart from public-order share-token throttling.
_THROTTLE_KEY_PREFIX = "UNIT_INVITE_REDEMPTION"
_THROTTLE_TTL_SECONDS = 2 * 60 * 60

# The fields ``UpdateUnitInput`` may carry. Anything else in the payload is
# ignored: ``unitId`` and ``adminCount`` are not writable through this surface,
# so a caller must not be able to smuggle them in as extra keys.
_METADATA_FIELDS: tuple[str, ...] = ("unitType", "unitNumber", "city", "state")
_SETTINGS_FIELDS: tuple[str, ...] = ("displayName", "timezone", "splitDefault", "councilNeedBasis")
_WRITABLE_FIELDS: tuple[str, ...] = _METADATA_FIELDS + _SETTINGS_FIELDS

# One normalizer per writable field, so the change set is validated by exactly the
# same rules the create path applies through ``build_unit_item``.
_NORMALIZERS: Dict[str, Callable[[Any], Any]] = {
    "unitType": lambda value: unit_models.normalize_required_text(value, "unitType"),
    "unitNumber": unit_models.normalize_unit_number,
    "city": lambda value: unit_models.normalize_required_text(value, "city"),
    "state": lambda value: unit_models.normalize_required_text(value, "state"),
    "displayName": lambda value: unit_models.normalize_optional_text(value, "displayName"),
    "timezone": unit_models.normalize_timezone,
    "splitDefault": unit_models.normalize_split_default,
    "councilNeedBasis": unit_models.normalize_council_need_basis,
}


# --- Event reading ---------------------------------------------------------------


def _require_input(event: Dict[str, Any]) -> Dict[str, Any]:
    """Read the mutation's ``input`` object."""
    arguments = event.get("arguments")
    raw_input = arguments.get("input") if isinstance(arguments, Mapping) else None
    if not isinstance(raw_input, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "input is required")
    return raw_input


def _idempotency_key(payload: Mapping[str, Any]) -> str:
    """Read ``idempotency.idempotencyKey``; its shape is enforced by the marker helper."""
    idempotency = payload.get("idempotency")
    if not isinstance(idempotency, Mapping) or idempotency.get("idempotencyKey") is None:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotency.idempotencyKey is required")
    return str(idempotency["idempotencyKey"])


def _expected_version(payload: Mapping[str, Any]) -> int:
    """Read ``version.expectedVersion`` (optimistic concurrency)."""
    version_input = payload.get("version")
    if not isinstance(version_input, Mapping) or version_input.get("expectedVersion") is None:
        raise AppError(ErrorCode.INVALID_INPUT, "version.expectedVersion is required")
    value = version_input["expectedVersion"]
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise AppError(ErrorCode.INVALID_INPUT, "version.expectedVersion must be an integer")
    try:
        return int(value)
    except ValueError, ArithmeticError:
        raise AppError(ErrorCode.INVALID_INPUT, "version.expectedVersion must be an integer") from None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    """The request fingerprint a retry must reproduce exactly.

    ``drop_none`` makes an omitted optional field and an explicit null the same
    request, which is what "normalized" means in API contract §3.1.
    """
    return str(normalized_fingerprint(payload, drop_none=True))


def _resource_id(payload: Mapping[str, Any], field: str) -> str:
    """Read a required identifier from the input (``unitId`` / ``accountId``)."""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} is required")
    return value.strip()


# --- Output projection -----------------------------------------------------------


def _number(value: Any) -> int:
    """Coerce a DynamoDB number (``Decimal``) to the integer the SDL declares."""
    return int(value)


def unit_payload(unit: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a Unit item onto the ``Unit`` GraphQL type.

    ``pk``/``sk`` are storage detail and never leave the handler; the remaining
    fields match the SDL one-for-one.
    """
    return {
        "unitId": unit["unitId"],
        "unitType": unit["unitType"],
        "unitNumber": _number(unit["unitNumber"]),
        "city": unit["city"],
        "state": unit["state"],
        "displayName": unit.get("displayName"),
        "metadataKey": unit.get("metadataKey"),
        "timezone": unit["timezone"],
        "splitDefault": unit["splitDefault"],
        "councilNeedBasis": unit["councilNeedBasis"],
        "adminCount": _number(unit["adminCount"]),
        "version": _number(unit["version"]),
        "createdAt": unit["createdAt"],
        "updatedAt": unit["updatedAt"],
        "createdByAccountId": unit["createdByAccountId"],
    }


def grant_payload(grant: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a grant item onto the ``UnitAccessGrant`` type."""
    return {
        "unitId": grant["unitId"],
        "accountId": grant["accountId"],
        "role": grant["role"],
        "createdByAccountId": grant["createdByAccountId"],
        "createdAt": grant["createdAt"],
    }


def _wire_key(key: Mapping[str, str]) -> Dict[str, Dict[str, str]]:
    """Encode a key pair as DynamoDB AttributeValues (wire form)."""
    return {name: {"S": value} for name, value in key.items()}


def _wire(value: Any) -> Dict[str, Any]:
    """Encode a Python value as a DynamoDB AttributeValue (wire form).

    Only strings and integers occur in the Stage 1 Unit payloads; a boolean
    would arrive as a string here, which is why no Stage 1 Unit field is stored
    as a DynamoDB boolean.
    """
    if isinstance(value, int):
        return {"N": str(value)}
    return {"S": str(value)}


# --- Duplicate gate --------------------------------------------------------------


def _duplicate_gate(metadata_key: str, confirmed: Any, *, exclude_unit_id: Optional[str] = None) -> None:
    """Require ``duplicateConfirmed`` before writing an exact type/number/city/state match.

    The match is a warning, never a block: confirming creates a genuinely
    distinct Unit — no merge, no shared admin — which is what two unrelated Units
    with the same number in the same city need (UNIT-M-01-02). Only the count is
    reported: another tenant's ``unitId`` is not disclosed, because
    ``metadataKey`` is a lookup key and not an access path (§5.1).
    """
    if confirmed is True:
        return
    matches = [
        match for match in unit_models.find_units_with_metadata(metadata_key) if match.get("unitId") != exclude_unit_id
    ]
    if not matches:
        return
    raise AppError(
        ErrorCode.INVALID_INPUT,
        "A Unit with exactly this type, number, city, and state already exists. "
        "Resend with duplicateConfirmed set to true to create a separate Unit.",
        details={"subcode": "DUPLICATE_UNIT_METADATA", "existingUnitCount": len(matches)},
    )


def _marker(*, caller_id: str, operation: str, scope: str, idempotency_key: str) -> Any:
    """Resolve this request's marker address on the units table."""
    return marker_keys(
        table_key="units",
        table_name=tables.units.table_name,
        actor_id=caller_id,
        operation=operation,
        scope=scope,
        idempotency_key=idempotency_key,
    )


def _replay(
    runner: Any, keys: Any, fingerprint: str, operation: str, load_result: Callable[[str], Any]
) -> Optional[Dict[str, Any]]:
    """Answer a completed or in-flight retry before any domain rule re-runs.

    A retry whose first attempt committed must return the original result with no
    new effect — which means the replay has to be consulted BEFORE the duplicate
    gate, the version guard, or the "grant still exists" check, each of which the
    first attempt's own write would now fail. The marker key carries the actor,
    so a replay can only be answered for the caller that made the original call.
    """
    handled, replayed = runner.replay_or_reject(keys, fingerprint, operation=operation, load_result=load_result)
    return cast(Optional[Dict[str, Any]], replayed) if handled else None


# --- createUnit (§1.2.1) ---------------------------------------------------------


def _unit_from_input(payload: Mapping[str, Any], *, unit_id: str, caller_id: str, now_iso: str) -> Dict[str, Any]:
    """Build the Unit item from the raw input (the builder validates every field)."""
    return dict(
        unit_models.build_unit_item(
            unit_id=unit_id,
            unit_type=payload.get("unitType"),
            unit_number=payload.get("unitNumber"),
            city=payload.get("city"),
            state=payload.get("state"),
            timezone_name=payload.get("timezone"),
            created_by_account_id=caller_id,
            now_iso=now_iso,
            split_default=payload.get("splitDefault"),
            council_need_basis=payload.get("councilNeedBasis"),
            display_name=payload.get("displayName"),
        )
    )


def _put_action(item: Mapping[str, Any]) -> Dict[str, Any]:
    """A conditional Put that may never overwrite an existing row.

    ``Put`` carries the key inside the item itself, and every value rides in
    DynamoDB wire form — the plan is submitted to the plain client, which passes
    AttributeValues through untouched.
    """
    return {
        "TableName": tables.units.table_name,
        "Item": {name: _wire(value) for name, value in item.items()},
        "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
        "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _create_payload(unit_id: str) -> Dict[str, Any]:
    """Rebuild the ``CreateUnitPayload`` for a fresh write or a completed retry."""
    unit = unit_models.read_unit(unit_id)
    if unit is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "created Unit could not be loaded")
    unit = dict(unit)
    grant = unit_auth.read_grant(str(unit["unitId"]), str(unit["createdByAccountId"]))
    if grant is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "creator access grant could not be loaded")
    return {"unit": unit_payload(unit), "grant": grant_payload(grant)}


def _create_unit(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Create a Unit plus the creator's first admin grant in one transaction.

    The marker's resource scope is the fixed ``BOOTSTRAP`` value rather than the
    new ``unitId``: a bootstrap marker cannot depend on a Unit the transaction
    has not created yet (data model §8.9), so the retry stays answerable even
    though the identity is fresh on every attempt (UNIT-M-01-04). The replay
    check runs before the duplicate gate so a completed retry replays instead of
    tripping over the Unit its own first attempt created.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=CREATE_UNIT_FIELD, scope=BOOTSTRAP_SCOPE, idempotency_key=key)
    replayed = _replay(runner, keys, fingerprint, CREATE_UNIT_FIELD, lambda stored: _create_payload(str(stored)))
    if replayed is not None:
        return replayed

    unit_id = str(unit_models.new_unit_id())
    now_iso = utc_now_iso()
    unit_item = _unit_from_input(payload, unit_id=unit_id, caller_id=caller_id, now_iso=now_iso)
    _duplicate_gate(str(unit_item["metadataKey"]), payload.get("duplicateConfirmed"))

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_id)
    plan.add("Put", _put_action(unit_item))
    plan.add(
        "Put",
        _put_action(
            unit_models.build_grant_item(
                unit_id=unit_id, account_id=caller_id, created_by_account_id=caller_id, now_iso=now_iso
            )
        ),
    )
    runner.execute(
        keys,
        plan,
        operation=CREATE_UNIT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: _create_payload(str(stored)),
    )
    log.info("Unit created", unit_id=unit_id, caller_id=caller_id)
    return _create_payload(unit_id)


# --- updateUnit (§1.2.2) ---------------------------------------------------------


def _changed_fields(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize only the writable fields the caller actually sent."""
    changes: Dict[str, Any] = {}
    for field in _WRITABLE_FIELDS:
        if field in payload:
            changes[field] = _NORMALIZERS[field](payload[field])
    if not changes:
        raise AppError(ErrorCode.INVALID_INPUT, "At least one Unit field must change")
    return changes


def _refresh_metadata_key(current: Mapping[str, Any], changes: Dict[str, Any]) -> None:
    """Recompute ``metadataKey`` after a geography change; never rename implicitly.

    The stored display name is left alone: when it was generated the admin can
    regenerate it by sending the field, and when it was chosen by hand a
    geography edit must not rename the Unit behind the admin's back.
    """
    if not _GEOGRAPHY.intersection(changes):
        return
    merged: Dict[str, Any] = {field: current.get(field) for field in _METADATA_FIELDS}
    merged.update({field: changes[field] for field in changes if field in _METADATA_FIELDS})
    changes["metadataKey"] = unit_models.normalized_metadata_key(
        str(merged["unitType"]), int(merged["unitNumber"]), str(merged["city"]), str(merged["state"])
    )


_GEOGRAPHY: frozenset[str] = frozenset(_METADATA_FIELDS)


def _require_stored_unit(unit_id: str) -> Dict[str, Any]:
    """Load a Unit this handler just wrote; a missing row is an internal fault."""
    unit = unit_models.read_unit(unit_id)
    if unit is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "updated Unit could not be loaded")
    return dict(unit)


def _versioned_unit_update(unit_id: str, changes: Mapping[str, Any], *, expected_version: int) -> Dict[str, Any]:
    """The conditional Unit update: one version guard covering every written field."""
    names: Dict[str, str] = {"#version": "version", "#updatedAt": "updatedAt"}
    values: Dict[str, Any] = {
        ":expectedVersion": {"N": str(expected_version)},
        ":one": {"N": "1"},
        ":updatedAt": {"S": utc_now_iso()},
    }
    sets: List[str] = ["#version = #version + :one", "#updatedAt = :updatedAt"]
    for field, value in changes.items():
        names[f"#{field}"] = field
        values[f":{field}"] = _wire(value)
        sets.append(f"#{field} = :{field}")
    return {
        "TableName": tables.units.table_name,
        "Key": _wire_key(unit_models.unit_metadata_key(unit_id)),
        "UpdateExpression": "SET " + ", ".join(sets),
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
        "ConditionExpression": "#version = :expectedVersion",
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _update_unit(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Apply a Unit Admin's metadata/settings change under ``expectedVersion``.

    The replay check runs before the version guard for the same reason the
    duplicate gate sits behind it: a completed retry must return the original
    result rather than a ``CONFLICT`` against the version its own first attempt
    wrote.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    expected_version = _expected_version(payload)
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=UPDATE_UNIT_FIELD, scope=unit_id, idempotency_key=key)
    replayed = _replay(
        runner, keys, fingerprint, UPDATE_UNIT_FIELD, lambda stored: unit_payload(_require_stored_unit(str(stored)))
    )
    if replayed is not None:
        return replayed

    unit_auth.require_unit_admin(caller_id, unit_id)
    current = unit_models.load_unit_or_not_found(unit_id)
    changes = _changed_fields(payload)
    _refresh_metadata_key(current, changes)
    if "metadataKey" in changes:
        _duplicate_gate(str(changes["metadataKey"]), payload.get("duplicateConfirmed"), exclude_unit_id=unit_id)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_id)
    plan.add("Update", _versioned_unit_update(unit_id, changes, expected_version=expected_version))
    runner.execute(
        keys,
        plan,
        operation=UPDATE_UNIT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: unit_payload(_require_stored_unit(str(stored))),
    )
    refreshed = _require_stored_unit(unit_id)
    log.info("Unit updated", unit_id=unit_id, caller_id=caller_id, version=refreshed["version"])
    return unit_payload(refreshed)


# --- revokeUnitAccessGrant (§1.2.3) ----------------------------------------------


def _grant_count_update(unit_id: str, *, expected_version: int) -> Dict[str, Any]:
    """The conditional decrement that keeps ``adminCount`` authoritative.

    ``adminCount > 1`` rides in the condition, not just in the pre-check, so two
    racing revocations cannot take the Unit below its final admin: the loser's
    transaction is cancelled whole, marker included.
    """
    return {
        "TableName": tables.units.table_name,
        "Key": _wire_key(unit_models.unit_metadata_key(unit_id)),
        "UpdateExpression": "SET #adminCount = #adminCount - :one, #version = #version + :one, #updatedAt = :updatedAt",
        "ExpressionAttributeNames": {"#adminCount": "adminCount", "#version": "version", "#updatedAt": "updatedAt"},
        "ExpressionAttributeValues": {
            ":one": {"N": "1"},
            ":expectedVersion": {"N": str(expected_version)},
            ":floor": {"N": "1"},
            ":updatedAt": {"S": utc_now_iso()},
        },
        "ConditionExpression": "#version = :expectedVersion AND #adminCount > :floor",
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _revoke_grant(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Delete one grant and decrement ``adminCount`` atomically.

    Revoking the caller's own grant is allowed while another admin remains — the
    product renders no self-removal control, and the direct-API denial of the
    final grant (UNIT-M-06-02) comes from the same guard either way. The replay
    check runs first so an identical retry of a completed revocation cannot fall
    over the grant its own first attempt deleted.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    target_account_id = _resource_id(payload, "accountId")
    expected_version = _expected_version(payload)
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=REVOKE_GRANT_FIELD, scope=unit_id, idempotency_key=key)
    replayed = _replay(
        runner, keys, fingerprint, REVOKE_GRANT_FIELD, lambda stored: unit_payload(_require_stored_unit(str(stored)))
    )
    if replayed is not None:
        return replayed

    unit_auth.require_unit_admin(caller_id, unit_id)
    unit = unit_models.load_unit_or_not_found(unit_id)
    if unit_auth.read_grant(unit_id, target_account_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "Unit access grant not found")
    if _number(unit.get("adminCount")) <= 1:
        raise AppError(ErrorCode.CONFLICT, "This is the last Unit admin; grant another admin before revoking one.")

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_id)
    plan.add(
        "Delete",
        {
            "TableName": tables.units.table_name,
            "Key": _wire_key(unit_models.grant_key(unit_id, target_account_id)),
            "ConditionExpression": "attribute_exists(#pk) AND attribute_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )
    plan.add("Update", _grant_count_update(unit_id, expected_version=expected_version))
    runner.execute(
        keys,
        plan,
        operation=REVOKE_GRANT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: unit_payload(_require_stored_unit(str(stored))),
    )
    refreshed = _require_stored_unit(unit_id)
    log.info(
        "Unit access grant revoked",
        unit_id=unit_id,
        caller_id=caller_id,
        revoked_account_id=target_account_id,
        admin_count=refreshed["adminCount"],
    )
    return unit_payload(refreshed)


# --- Unit invites (§1.3.1, §1.3.2, §1.3.3) --------------------------------------


def invite_payload(invite: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an invite item onto the ``UnitInvite`` type.

    ``expiresAtEpoch`` is storage/TTL detail and is never returned: the caller
    sees the expiry it acts on, not the moment DynamoDB may delete the row.
    """
    return {
        "inviteCode": invite["inviteCode"],
        "unitId": invite["unitId"],
        "createdByAccountId": invite["createdByAccountId"],
        "createdAt": invite["createdAt"],
        "expiresAt": invite["expiresAt"],
    }


def _require_active_admin(caller_id: str, unit_id: str) -> Dict[str, Any]:
    """Read the caller's grant and return the Unit, denying everything else."""
    unit_auth.require_unit_admin(caller_id, unit_id)
    return dict(unit_models.load_unit_or_not_found(unit_id))


def _page_argument(event: Dict[str, Any]) -> Optional[Mapping[str, Any]]:
    """Read the optional ``page: PageInput`` of a list resolver."""
    arguments = event.get("arguments")
    page = arguments.get("page") if isinstance(arguments, Mapping) else None
    if page is None:
        return None
    if not isinstance(page, Mapping):
        raise AppError(ErrorCode.INVALID_INPUT, "page must be an object")
    return page


def _query_argument(event: Dict[str, Any], name: str) -> str:
    """Read a required top-level query argument (``unitId``)."""
    arguments = event.get("arguments")
    value = arguments.get(name) if isinstance(arguments, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        raise AppError(ErrorCode.INVALID_INPUT, f"{name} is required")
    return value.strip()


def _create_invite(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Issue a 16-character, 14-day, single-use admin invite (§1.3.1).

    The 20-active-invite ceiling is counted over invites that are still
    redeemable: an expired row the TTL has not collected yet, and a redeemed or
    revoked row (deleted), do not consume a slot. The ceiling is checked before
    the marker is staged, so a rejected request leaves no idempotency marker
    behind and the caller's next attempt is a real attempt.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=CREATE_INVITE_FIELD, scope=unit_id, idempotency_key=key)
    replayed = _replay(runner, keys, fingerprint, CREATE_INVITE_FIELD, lambda stored: _loaded_invite(str(stored)))
    if replayed is not None:
        return replayed

    _require_active_admin(caller_id, unit_id)
    active = unit_models.list_active_invites(unit_id)
    if len(active) >= MAX_ACTIVE_UNIT_INVITES:
        raise AppError(
            ErrorCode.CONFLICT,
            f"This Unit already has {MAX_ACTIVE_UNIT_INVITES} active invites. Revoke one before creating another.",
            details={"subcode": "INVITE_LIMIT_REACHED", "activeInvites": len(active)},
        )

    invite_code = unit_models.new_invite_code()
    item = unit_models.build_invite_item(
        invite_code=invite_code,
        unit_id=unit_id,
        created_by_account_id=caller_id,
        created_at=datetime.now(timezone.utc),
    )
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=invite_code)
    plan.add("Put", _put_action(item))
    runner.execute(
        keys,
        plan,
        operation=CREATE_INVITE_FIELD,
        fingerprint=fingerprint,
        result_id=invite_code,
        load_result=lambda stored: _loaded_invite(str(stored)),
    )
    log.info("Unit invite created", unit_id=unit_id, caller_id=caller_id, invite_expires_at=item["expiresAt"])
    return _loaded_invite(invite_code)


def _loaded_invite(invite_code: str) -> Dict[str, Any]:
    """Load the invite a request just created or must replay."""
    invite = unit_models.read_invite(invite_code)
    if invite is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "unit invite could not be loaded")
    return invite_payload(invite)


def _current_redemption_window() -> tuple[str, int]:
    """The UTC hour bucket the §6.6 counter is keyed on, and its start instant."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%dT%H"), int(now.timestamp())


def _record_failed_redemption(account_id: str) -> None:
    """Count one failed redemption and reject attempt 11 in the current UTC hour.

    Increment-then-read is the atomic check the data model asks for: two racing
    failures cannot both believe they were the tenth. A successful redemption and
    a replay never call this, and the window expires on its own TTL rather than
    needing a cleanup path.
    """
    window_start, window_epoch = _current_redemption_window()
    throttle_key = f"{_THROTTLE_KEY_PREFIX}#{account_id}#WINDOW#{window_start}"
    now_iso = utc_now_iso()
    try:
        updated = get_dynamodb_client().update_item(
            TableName=tables.public_order_throttles.table_name,
            Key={"key": {"S": throttle_key}},
            UpdateExpression=(
                "SET #attempts = if_not_exists(#attempts, :zero) + :one, "
                "#accountId = :accountId, #windowStart = :windowStart, "
                "#createdAt = if_not_exists(#createdAt, :now), #updatedAt = :now, #expiresAt = :expiresAt"
            ),
            ExpressionAttributeNames={
                "#attempts": "attempts",
                "#accountId": "accountId",
                "#windowStart": "windowStart",
                "#createdAt": "createdAt",
                "#updatedAt": "updatedAt",
                "#expiresAt": "expiresAt",
            },
            ExpressionAttributeValues={
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":accountId": {"S": account_id},
                ":windowStart": {"S": window_start},
                ":now": {"S": now_iso},
                ":expiresAt": {"N": str(window_epoch + _THROTTLE_TTL_SECONDS)},
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as exc:
        raise _attempt_counter_failure(exc) from exc
    if _counter_attempts(updated) > INVITE_FAILURES_PER_HOUR:
        raise AppError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            "Too many failed invite redemptions. Try again later.",
            details={"subcode": "INVITE_REDEMPTION_THROTTLE", "window": window_start},
        )


_RETRYABLE_COUNTER_ERRORS: frozenset[str] = frozenset(
    {"ProvisionedThroughputExceededException", "ThrottlingException", "TooManyRequestsException"}
)


def _counter_attempts(updated: Mapping[str, Any]) -> int:
    """Read this attempt's count out of the wire-form UPDATED_NEW attributes."""
    value = updated.get("Attributes", {}).get("attempts", {})
    raw = value.get("N") if isinstance(value, Mapping) else None
    try:
        return int(raw) if raw is not None else 0
    except TypeError, ValueError:
        # A counter that cannot be read is a counter that did not count: fail the
        # request rather than silently allowing unlimited attempts.
        raise AppError(ErrorCode.DATABASE_ERROR, "failed to read the invite attempt counter") from None


def _attempt_counter_failure(exc: ClientError) -> "AppErrorType":
    """A busy counter is retryable; anything else is a storage fault.

    The distinction matters to the caller: ``RESOURCE_BUSY`` means the same
    redemption may be retried, while a failed counter write must not be reported
    as a bad invite code.
    """
    code = str(exc.response.get("Error", {}).get("Code", ""))
    if code in _RETRYABLE_COUNTER_ERRORS:
        return cast(
            "AppErrorType", AppError(ErrorCode.RESOURCE_BUSY, "The invite attempt counter is busy. Try again shortly.")
        )
    return cast("AppErrorType", AppError(ErrorCode.DATABASE_ERROR, "failed to record the invite attempt"))


def _redeemed_payload(unit_id: str, account_id: str) -> Dict[str, Any]:
    """Load the grant a redemption produced (or must replay)."""
    grant = unit_auth.read_grant(unit_id, account_id)
    if grant is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "redeemed Unit access grant could not be loaded")
    return grant_payload(grant)


def _redeem_invite(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Redeem a single-use invite into a Unit Admin grant (§1.3.2).

    Ordering carries the contract:

    1. the idempotency replay is answered first, so a retry of a completed
       redemption is never throttled or re-validated (UNIT-M-05-04);
    2. the marker is scoped to the ``inviteCode`` because redemption deletes the
       invite and the marker has to outlive it (§3.1);
    3. an unusable code — unknown, malformed, expired, already consumed — is
       counted and answered ``NOT_FOUND`` identically, so the caller learns
       nothing about which case it hit;
    4. an already-held grant returns that grant without touching ``adminCount``
       (§5.2) and still consumes the code, so a code cannot be banked;
    5. otherwise the grant, the ``adminCount`` increment, the invite deletion and
       the marker commit as one transaction. Two redeemers of one code: the
       loser's delete condition fails and the whole transaction is cancelled.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    invite_code = str(payload.get("inviteCode") or "")
    runner = IdempotentMutationRunner()

    # A malformed code cannot have a completed attempt behind it, so it is
    # answered before the marker work — and counted, because code guessing is
    # exactly what the §6.6 window exists to bound.
    if not unit_models.is_valid_invite_code(invite_code):
        _record_failed_redemption(caller_id)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")

    keys = _marker(caller_id=caller_id, operation=REDEEM_INVITE_FIELD, scope=invite_code, idempotency_key=key)
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        REDEEM_INVITE_FIELD,
        lambda stored: _redeemed_payload(str(stored), caller_id),
    )
    if replayed is not None:
        return replayed

    invite = unit_models.read_invite(invite_code)
    if invite is None:
        _record_failed_redemption(caller_id)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    unit_id = str(invite["unitId"])
    if unit_models.read_unit(unit_id) is None:
        _record_failed_redemption(caller_id)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_id)
    plan.add("Delete", _delete_invite_action(invite))
    existing = unit_auth.read_grant(unit_id, caller_id)
    if existing is None:
        grant = unit_models.build_grant_item(
            unit_id=unit_id,
            account_id=caller_id,
            created_by_account_id=str(invite["createdByAccountId"]),
            now_iso=utc_now_iso(),
        )
        plan.add("Put", _put_action(grant))
        plan.add("Update", _grant_count_increment(unit_id))
    runner.execute(
        keys,
        plan,
        operation=REDEEM_INVITE_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: _redeemed_payload(str(stored), caller_id),
    )
    log.info("Unit invite redeemed", unit_id=unit_id, caller_id=caller_id, already_admin=existing is not None)
    return _redeemed_payload(unit_id, caller_id)


def _delete_invite_action(invite: Mapping[str, Any]) -> Dict[str, Any]:
    """Delete the invite only if it is still there — the single-use guard."""
    return {
        "TableName": tables.units.table_name,
        "Key": _wire_key({"pk": str(invite["pk"]), "sk": str(invite["sk"])}),
        "ConditionExpression": "attribute_exists(#pk) AND attribute_exists(#sk)",
        "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _grant_count_increment(unit_id: str) -> Dict[str, Any]:
    """The conditional ``adminCount`` increment that rides beside the grant Put."""
    return {
        "TableName": tables.units.table_name,
        "Key": _wire_key(unit_models.unit_metadata_key(unit_id)),
        "UpdateExpression": "SET #adminCount = if_not_exists(#adminCount, :zero) + :one, #version = if_not_exists(#version, :zero) + :one, #updatedAt = :updatedAt",
        "ExpressionAttributeNames": {
            "#pk": "pk",
            "#adminCount": "adminCount",
            "#version": "version",
            "#updatedAt": "updatedAt",
        },
        "ExpressionAttributeValues": {
            ":zero": {"N": "0"},
            ":one": {"N": "1"},
            ":updatedAt": {"S": utc_now_iso()},
        },
        "ConditionExpression": "attribute_exists(#pk)",
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _revoke_invite(event: Dict[str, Any], caller_id: str) -> bool:
    """Revoke an unused invite (§1.3.3).

    A redeemed, revoked, or expired code is already gone and answers
    ``NOT_FOUND``; only an identical retry of the caller's own completed
    revocation replays to ``true``, because the marker is consulted before the
    code is looked up.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    invite_code = str(payload.get("inviteCode") or "")
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=REVOKE_INVITE_FIELD, scope=unit_id, idempotency_key=key)
    replayed = _replay(runner, keys, fingerprint, REVOKE_INVITE_FIELD, lambda stored: True)
    if replayed is not None:
        return True

    _require_active_admin(caller_id, unit_id)
    invite = unit_models.read_invite(invite_code) if unit_models.is_valid_invite_code(invite_code) else None
    if invite is None or str(invite["unitId"]) != unit_id:
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=invite_code)
    plan.add("Delete", _delete_invite_action(invite))
    runner.execute(
        keys,
        plan,
        operation=REVOKE_INVITE_FIELD,
        fingerprint=fingerprint,
        result_id=invite_code,
        load_result=lambda stored: True,
    )
    log.info("Unit invite revoked", unit_id=unit_id, caller_id=caller_id)
    return True


# --- Unit and roster queries (§1.3.3 listing, §1.3.4) ---------------------------


def _list_invites(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The Unit's active, unused invites — codes included for admins only."""
    unit_id = _query_argument(event, "unitId")
    _require_active_admin(caller_id, unit_id)
    items = [invite_payload(invite) for invite in unit_models.list_active_invites(unit_id)]
    return dict(paginate_page(items, f"{UNIT_INVITES_FIELD}#{unit_id}", _page_argument(event)))


def _my_units(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The Units the caller holds a grant on — never a Unit they were not granted."""
    unit_ids = unit_auth.list_unit_ids_for_account(caller_id)
    items = [unit_payload(unit) for unit_id in unit_ids if (unit := unit_models.read_unit(unit_id)) is not None]
    return dict(paginate_page(items, f"{MY_UNITS_FIELD}#{caller_id}", _page_argument(event)))


def _get_unit(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One Unit's settings and authoritative admin count, for its admins."""
    unit_id = _query_argument(event, "unitId")
    unit = _require_active_admin(caller_id, unit_id)
    return unit_payload(unit)


def _account_directory(account_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-read the Account rows behind a roster, keyed by bare sub.

    Read only for the fields administration needs (email and name); a missing
    Account still appears in the roster with those fields null, because the grant
    — not the Account row — is what makes someone an admin.
    """
    directory: Dict[str, Dict[str, Any]] = {}
    # ``batch_get_chunked`` makes no call for an empty key list, so no special case.
    keys = [{"accountId": ensure_account_id(account_id)} for account_id in account_ids]
    batch_get_chunked(tables.accounts.table_name, keys, on_item=lambda item: _remember_account(directory, item))
    return directory


def _remember_account(directory: Dict[str, Dict[str, Any]], item: Dict[str, Any]) -> None:
    """Index one Account row by its bare sub for the roster join."""
    directory[str(item.get("accountId", "")).split("#", 1)[-1]] = item


def _account_name(account: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The display name a roster shows, from the Account's Cognito name parts."""
    if account is None:
        return None
    parts = [str(part) for part in (account.get("givenName"), account.get("familyName")) if part]
    return " ".join(parts) if parts else None


def _list_admins(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The Unit's current grants; a revoked admin is gone from the next read."""
    unit_id = _query_argument(event, "unitId")
    _require_active_admin(caller_id, unit_id)
    grants = unit_auth.list_unit_grants(unit_id)
    directory = _account_directory([str(grant["accountId"]) for grant in grants])
    items = []
    for grant in grants:
        account = directory.get(str(grant["accountId"]))
        admin = grant_payload(grant)
        admin["email"] = account.get("email") if account is not None else None
        admin["name"] = _account_name(account)
        items.append(admin)
    return dict(paginate_page(items, f"{UNIT_ADMINS_FIELD}#{unit_id}", _page_argument(event)))


# --- Entrypoint ------------------------------------------------------------------


_RESOLVERS: Dict[str, Callable[[Dict[str, Any], str], Any]] = {
    CREATE_UNIT_FIELD: _create_unit,
    UPDATE_UNIT_FIELD: _update_unit,
    REVOKE_GRANT_FIELD: _revoke_grant,
    CREATE_INVITE_FIELD: _create_invite,
    REDEEM_INVITE_FIELD: _redeem_invite,
    REVOKE_INVITE_FIELD: _revoke_invite,
    UNIT_INVITES_FIELD: _list_invites,
    MY_UNITS_FIELD: _my_units,
    UNIT_FIELD: _get_unit,
    UNIT_ADMINS_FIELD: _list_admins,
}


@with_error_handling(error_message="Failed to process the Unit request")
def handle_unit_operation(event: Dict[str, Any], context: Any) -> Any:
    """Route one Unit request to the resolver that owns it.

    Stage 1 puts the Unit's reads and writes behind one Lambda: the queries need
    the same grant lookup as the mutations, and splitting them would put tenant
    isolation in two places. ``context`` is the Lambda invocation context,
    unused by the routing itself.
    """
    field_name = str((event.get("info") or {}).get("fieldName", ""))
    resolver = _RESOLVERS.get(field_name)
    if resolver is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported operation: {field_name}")

    caller_id = get_caller_id(event)
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "A signed-in account is required")

    get_logger(__name__).debug("Unit request received", field_name=field_name, caller_id=caller_id)
    return resolver(event, caller_id)
