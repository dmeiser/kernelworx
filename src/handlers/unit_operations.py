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

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, cast

try:  # pragma: no cover
    from utils import unit_auth, unit_models
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils import unit_auth, unit_models
    from ..utils.import_fallback import import_from_utils


AppError, ErrorCode = import_from_utils("errors", "AppError", "ErrorCode")
get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
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
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    with_error_handling = import_from_utils("handlers", "lambda_handler")

CREATE_UNIT_FIELD = "createUnit"
UPDATE_UNIT_FIELD = "updateUnit"
REVOKE_GRANT_FIELD = "revokeUnitAccessGrant"

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


# --- Entrypoint ------------------------------------------------------------------


@with_error_handling(error_message="Failed to update the Unit")
def handle_unit_operation(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route one Unit mutation event to the resolver that owns it.

    ``context`` is the Lambda invocation context, unused by the routing itself.
    """
    field_name = str((event.get("info") or {}).get("fieldName", ""))
    if field_name not in {CREATE_UNIT_FIELD, UPDATE_UNIT_FIELD, REVOKE_GRANT_FIELD}:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported operation: {field_name}")

    caller_id = get_caller_id(event)
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "A signed-in account is required")

    get_logger(__name__).debug("Unit mutation received", field_name=field_name, caller_id=caller_id)
    if field_name == CREATE_UNIT_FIELD:
        return _create_unit(event, caller_id)
    if field_name == UPDATE_UNIT_FIELD:
        return _update_unit(event, caller_id)
    return _revoke_grant(event, caller_id)
