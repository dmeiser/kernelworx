"""Unit and inventory handlers (delivery checklist §1.2, §2.2).

One Lambda serves the Stage 1 Unit/Unit Campaign write surfaces and the Stage 2
inventory balance writes, routed on ``info.fieldName`` exactly as
``public_orders_router`` routes the public-orders Lambda, and driven by the event
shape the Stage 1 fixtures build
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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from botocore.exceptions import ClientError

try:  # pragma: no cover
    from utils import (
        allocation_models,
        inventory_models,
        order_fulfillment_models,
        show_and_sell_models,
        unit_auth,
        unit_campaign_models,
        unit_models,
    )
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils import (
        allocation_models,
        inventory_models,
        order_fulfillment_models,
        show_and_sell_models,
        unit_auth,
        unit_campaign_models,
        unit_models,
    )
    from ..utils.import_fallback import import_from_utils


AppError, ErrorCode = import_from_utils("errors", "AppError", "ErrorCode")
get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
batch_get_chunked = import_from_utils("dynamodb", "batch_get_chunked")
get_dynamodb_client = import_from_utils("dynamodb", "get_dynamodb_client")
ensure_account_id = import_from_utils("ids", "ensure_account_id")
batch_check_profile_access = import_from_utils("auth", "batch_check_profile_access")
check_profile_access = import_from_utils("auth", "check_profile_access")
require_profile_access = import_from_utils("auth", "require_profile_access")
paginate_page = import_from_utils("pagination", "paginate_page")
get_logger = import_from_utils("logging", "get_logger")
(
    BOOTSTRAP_SCOPE,
    IdempotentMutationRunner,
    MAX_TRANSACTION_ACTIONS,
    WritePlan,
    marker_keys,
    normalized_fingerprint,
    utc_now_iso,
    wire_key,
    wire_value,
) = import_from_utils(
    "mutations",
    "BOOTSTRAP_SCOPE",
    "IdempotentMutationRunner",
    "MAX_TRANSACTION_ACTIONS",
    "WritePlan",
    "marker_keys",
    "normalized_fingerprint",
    "utc_now_iso",
    "wire_key",
    "wire_value",
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
CREATE_UNIT_CAMPAIGN_FIELD = "createUnitCampaign"
UPDATE_UNIT_CAMPAIGN_FIELD = "updateUnitCampaign"
JOIN_PREVIEW_FIELD = "unitCampaignJoinInfo"
JOIN_UNIT_CAMPAIGN_FIELD = "joinUnitCampaign"
REMOVE_MEMBERSHIP_FIELD = "removeUnitCampaignMembership"
UNIT_CAMPAIGN_FIELD = "unitCampaign"
UNIT_CAMPAIGNS_FIELD = "unitCampaigns"
UNIT_CAMPAIGN_CATALOG_FIELD = "unitCampaignCatalog"
UNIT_CAMPAIGN_ROSTER_FIELD = "unitCampaignRoster"
RECORD_RECEIPT_FIELD = "recordInventoryReceipt"
ADJUST_INVENTORY_FIELD = "adjustInventory"
ADJUST_COUNCIL_FIELD = "adjustCouncilOnOrder"
INVENTORY_POSITIONS_FIELD = "inventoryPositions"
INVENTORY_MOVEMENTS_FIELD = "inventoryMovements"
ISSUE_STOCK_FIELD = "issueStockToScout"
RETURN_STOCK_FIELD = "returnStockFromScout"
SCOUT_CUSTODY_FIELD = "scoutCustodyBalances"
MY_SCOUT_CUSTODY_FIELD = "myScoutCustody"
FULFILL_LINE_FIELD = "fulfillIndividualOrderLine"
REVERSE_FULFILLMENT_FIELD = "reverseIndividualOrderFulfillment"
ORDER_FULFILLMENTS_FIELD = "orderFulfillments"
UNIT_SCOUT_ORDERS_FIELD = "unitScoutCampaignOrders"

# Stage 3.1 — the Show & Sell event aggregate (§3.1.2-§3.1.5).
CREATE_SHOW_AND_SELL_FIELD = "createShowAndSell"
UPDATE_SHOW_AND_SELL_FIELD = "updateShowAndSell"
CANCEL_SHOW_AND_SELL_FIELD = "cancelShowAndSell"
SHOW_AND_SELL_FIELD = "showAndSell"
SHOW_AND_SELLS_FIELD = "showAndSells"
UNIT_CAMPAIGN_OPPORTUNITIES_FIELD = "unitCampaignOpportunities"
SHOW_AND_SELL_OPPORTUNITY_FIELD = "showAndSellOpportunity"
SHOW_AND_SELL_ID_ARGUMENT = "showAndSellId"

# Stage 3.2 — event stock assignment and the raw allocation read (§3.2.3-§3.2.4).
ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD = "assignShowAndSellInventory"
EVENT_INVENTORY_ALLOCATIONS_FIELD = "eventInventoryAllocations"

# Stage 3.3 — the slot board (§3.3.2-§3.3.3).
UPSERT_SLOT_FIELD = "upsertShowAndSellSlot"
DELETE_SLOT_FIELD = "deleteShowAndSellSlot"

# Argument names that carry no write intent, so they stay out of the writable-field
# check.  ``idempotency`` and ``version`` are the mutation contract's own envelopes and
# ``showAndSellId`` names the row being addressed; every other name in the input is a
# field the caller is offering to change, which is what makes a smuggled ``startAt`` a
# refusal rather than an ignored key.
_EVENT_INPUT_BOOKKEEPING = frozenset({"idempotency", "version", SHOW_AND_SELL_ID_ARGUMENT})

MAX_ACTIVE_UNIT_INVITES = 20
INVITE_FAILURES_PER_HOUR = 10
# The filter set that pins an ``inventoryMovements`` cursor to the read it came from.
# Order matters: the token is what makes a cursor from one filtered page unusable on
# another filter combination.
_MOVEMENT_FILTER_ORDER: tuple[str, ...] = (
    "productId",
    "movementType",
    "showAndSellId",
    "profileId",
    "startAt",
    "endAt",
)
# The filter set that pins an ``eventInventoryAllocations`` cursor to the read it came
# from (PAGE-01): the same rule as the movement read, over this read's three filters.
_ALLOCATION_FILTER_ORDER: tuple[str, ...] = ("productId", "showAndSellId", "status")
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


def _read_expected_version(payload: Mapping[str, Any], field: str) -> Optional[int]:
    """Read ``<field>.expectedVersion`` when the caller sent that version block at all.

    A slot upsert carries two optimistic-concurrency numbers — the event's always, and
    the slot's only when it is editing a slot the caller has read — so the block itself
    is what says which of the two the caller means to move. Absent is a real answer;
    present-but-shapeless is not.
    """
    version_input = payload.get(field)
    if version_input is None:
        return None
    if not isinstance(version_input, Mapping) or version_input.get("expectedVersion") is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field}.expectedVersion is required")
    value = version_input["expectedVersion"]
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise AppError(ErrorCode.INVALID_INPUT, f"{field}.expectedVersion must be an integer")
    try:
        return int(value)
    except ValueError, ArithmeticError:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field}.expectedVersion must be an integer") from None


def _expected_version(payload: Mapping[str, Any]) -> int:
    """Read ``version.expectedVersion`` (optimistic concurrency)."""
    value = _read_expected_version(payload, "version")
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, "version.expectedVersion is required")
    return value


def _fingerprint(payload: Mapping[str, Any]) -> str:
    """The request fingerprint a retry must reproduce exactly.

    ``drop_none`` makes an omitted optional field and an explicit null the same
    request, which is what "normalized" means in API contract §3.1 for a create: both
    spellings ask for the same row.
    """
    return str(normalized_fingerprint(payload, drop_none=True))


def _update_fingerprint(payload: Mapping[str, Any]) -> str:
    """The fingerprint of an update, where an omitted field and a null are different requests.

    SDL §6 makes ``address`` (omitted) leave the row alone and ``address: null`` clear
    it, and the same shape holds for the split and We Owe settings. Folding nulls away
    would give those two requests one fingerprint, so a retry of "change the location"
    would answer a later "clear the address" as already done — and write nothing.
    """
    return str(normalized_fingerprint(payload))


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


def _once(builder: Callable[[], Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    """Evaluate a result builder at most once.

    The marker back-fill and the handler's own return must agree on exactly what
    this mutation produced. Two separate reads could disagree when another writer
    moves the row in between, and then the stored replay answer would not be the
    answer the caller actually received.
    """
    stored: Dict[str, Dict[str, Any]] = {}

    def read() -> Dict[str, Any]:
        if not stored:
            stored["value"] = builder()
        return stored["value"]

    return read


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
        "Item": {name: wire_value(value) for name, value in item.items()},
        "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
        "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _loaded_or_internal(row: Optional[Mapping[str, Any]], what: str) -> Dict[str, Any]:
    """The row a result is read from, or the internal fault when it is gone.

    Every caller of this has just committed the row, or is replaying a marker
    that says it committed. A row that cannot be read back is therefore not a
    caller error and never a ``NOT_FOUND`` answer: it means the handler cannot
    say what its own write produced, which is exactly what ``INTERNAL_ERROR``
    reports. ``what`` names the row so the log identifies the fault without
    describing the caller's data.
    """
    if row is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"{what}")
    return dict(row)


def _create_payload(unit_id: str) -> Dict[str, Any]:
    """Rebuild the ``CreateUnitPayload`` for a fresh write or a completed retry."""
    unit = _loaded_or_internal(unit_models.read_unit(unit_id), "created Unit could not be loaded")
    grant = _loaded_or_internal(
        unit_auth.read_grant(str(unit["unitId"]), str(unit["createdByAccountId"])),
        "creator access grant could not be loaded",
    )
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
    build_result = _once(lambda: _create_payload(unit_id))
    runner.execute(
        keys,
        plan,
        operation=CREATE_UNIT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: _create_payload(str(stored)),
        result_payload=build_result,
    )
    log.info("Unit created", unit_id=unit_id, caller_id=caller_id)
    return build_result()


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
    return _loaded_or_internal(unit_models.read_unit(unit_id), "updated Unit could not be loaded")


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
        values[f":{field}"] = wire_value(value)
        sets.append(f"#{field} = :{field}")
    return {
        "TableName": tables.units.table_name,
        "Key": wire_key(unit_models.unit_metadata_key(unit_id)),
        "UpdateExpression": "SET " + ", ".join(sets),
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
        "ConditionExpression": "#version = :expectedVersion",
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _update_unit(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Apply a Unit Admin's metadata/settings change under ``expectedVersion``.

    Current authorization runs FIRST: a caller whose admin grant was revoked
    since the original attempt gets the same denial here as any other request,
    not a replayed answer. Behind it, the replay check runs before the version
    guard for the same reason the duplicate gate sits behind it: a completed
    retry must return the original result rather than a ``CONFLICT`` against the
    version its own first attempt wrote.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    expected_version = _expected_version(payload)
    runner = IdempotentMutationRunner()

    keys = _marker(caller_id=caller_id, operation=UPDATE_UNIT_FIELD, scope=unit_id, idempotency_key=key)
    unit_auth.require_unit_admin(caller_id, unit_id)
    replayed = _replay(
        runner, keys, fingerprint, UPDATE_UNIT_FIELD, lambda stored: unit_payload(_require_stored_unit(str(stored)))
    )
    if replayed is not None:
        return replayed

    current = unit_models.load_unit_or_not_found(unit_id)
    changes = _changed_fields(payload)
    _refresh_metadata_key(current, changes)
    if "metadataKey" in changes:
        _duplicate_gate(str(changes["metadataKey"]), payload.get("duplicateConfirmed"), exclude_unit_id=unit_id)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_id)
    plan.add("Update", _versioned_unit_update(unit_id, changes, expected_version=expected_version))
    build_result = _once(lambda: unit_payload(_require_stored_unit(unit_id)))
    runner.execute(
        keys,
        plan,
        operation=UPDATE_UNIT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: unit_payload(_require_stored_unit(str(stored))),
        result_payload=build_result,
    )
    result = build_result()
    log.info("Unit updated", unit_id=unit_id, caller_id=caller_id, version=result["version"])
    return result


# --- revokeUnitAccessGrant (§1.2.3) ----------------------------------------------


def _grant_count_update(unit_id: str, *, expected_version: int) -> Dict[str, Any]:
    """The conditional decrement that keeps ``adminCount`` authoritative.

    ``adminCount > 1`` rides in the condition, not just in the pre-check, so two
    racing revocations cannot take the Unit below its final admin: the loser's
    transaction is cancelled whole, marker included.
    """
    return {
        "TableName": tables.units.table_name,
        "Key": wire_key(unit_models.unit_metadata_key(unit_id)),
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
    final grant (UNIT-M-06-02) comes from the same guard either way. The caller's
    current admin status is checked first, so a revoked caller cannot use a
    replay to read the answer an earlier attempt produced; behind it, the replay
    check runs before the grant lookup so an identical retry of a completed
    revocation cannot fall over the grant its own first attempt deleted.
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
    unit_auth.require_unit_admin(caller_id, unit_id)
    replayed = _replay(
        runner, keys, fingerprint, REVOKE_GRANT_FIELD, lambda stored: unit_payload(_require_stored_unit(str(stored)))
    )
    if replayed is not None:
        return replayed

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
            "Key": wire_key(unit_models.grant_key(unit_id, target_account_id)),
            "ConditionExpression": "attribute_exists(#pk) AND attribute_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )
    plan.add("Update", _grant_count_update(unit_id, expected_version=expected_version))
    build_result = _once(lambda: unit_payload(_require_stored_unit(unit_id)))
    runner.execute(
        keys,
        plan,
        operation=REVOKE_GRANT_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: unit_payload(_require_stored_unit(str(stored))),
        result_payload=build_result,
    )
    result = build_result()
    log.info(
        "Unit access grant revoked",
        unit_id=unit_id,
        caller_id=caller_id,
        revoked_account_id=target_account_id,
        admin_count=result["adminCount"],
    )
    return result


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
    _require_active_admin(caller_id, unit_id)
    replayed = _replay(runner, keys, fingerprint, CREATE_INVITE_FIELD, lambda stored: _loaded_invite(str(stored)))
    if replayed is not None:
        return replayed

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
    build_result = _once(lambda: _loaded_invite(invite_code))
    runner.execute(
        keys,
        plan,
        operation=CREATE_INVITE_FIELD,
        fingerprint=fingerprint,
        result_id=invite_code,
        load_result=lambda stored: _loaded_invite(str(stored)),
        result_payload=build_result,
    )
    log.info("Unit invite created", unit_id=unit_id, caller_id=caller_id, invite_expires_at=item["expiresAt"])
    # The invite this call created is stored on the marker, so a retry of it is
    # answered even after the code is redeemed or revoked and the row is gone.
    return build_result()


def _loaded_invite(invite_code: str) -> Dict[str, Any]:
    """Load the invite a request just created or must replay."""
    return invite_payload(_loaded_or_internal(unit_models.read_invite(invite_code), "unit invite could not be loaded"))


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
    grant = _loaded_or_internal(
        unit_auth.read_grant(unit_id, account_id), "redeemed Unit access grant could not be loaded"
    )
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
    build_result = _once(lambda: _redeemed_payload(unit_id, caller_id))
    runner.execute(
        keys,
        plan,
        operation=REDEEM_INVITE_FIELD,
        fingerprint=fingerprint,
        result_id=unit_id,
        load_result=lambda stored: _redeemed_payload(str(stored), caller_id),
        result_payload=build_result,
    )
    log.info("Unit invite redeemed", unit_id=unit_id, caller_id=caller_id, already_admin=existing is not None)
    # The grant the redemption produced rides on the marker: the invite row is
    # deleted by this very transaction, and the grant can be revoked afterwards,
    # so neither is a reliable place to re-derive the answer from.
    return build_result()


def _delete_invite_action(invite: Mapping[str, Any]) -> Dict[str, Any]:
    """Delete the invite only if it is still there — the single-use guard."""
    return {
        "TableName": tables.units.table_name,
        "Key": wire_key({"pk": str(invite["pk"]), "sk": str(invite["sk"])}),
        "ConditionExpression": "attribute_exists(#pk) AND attribute_exists(#sk)",
        "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _grant_count_increment(unit_id: str) -> Dict[str, Any]:
    """The conditional ``adminCount`` increment that rides beside the grant Put."""
    return {
        "TableName": tables.units.table_name,
        "Key": wire_key(unit_models.unit_metadata_key(unit_id)),
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
    _require_active_admin(caller_id, unit_id)
    replayed = _replay(runner, keys, fingerprint, REVOKE_INVITE_FIELD, lambda stored: True)
    if replayed is not None:
        return True

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
        result_payload=lambda: True,
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


# --- Unit Campaign mutations and roster queries (§1.5) ---------------------------


def campaign_payload(campaign: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a Unit Campaign item onto ``UnitCampaignAdmin``.

    The join code is included because this is the admin projection: the
    member-safe path is ``unitCampaignJoinInfo``, which carries no code, no IDs,
    and no settings (API contract §3.2 participant allowlist).
    """
    return {
        "unitCampaignId": campaign["unitCampaignId"],
        "unitId": campaign["unitId"],
        "campaignName": campaign["campaignName"],
        "campaignYear": _number(campaign["campaignYear"]),
        "catalogId": campaign["catalogId"],
        "joinCode": campaign["joinCode"],
        "isActive": bool(campaign["isActive"]),
        "version": _number(campaign["version"]),
        "createdAt": campaign["createdAt"],
        "updatedAt": campaign["updatedAt"],
        "createdByAccountId": campaign["createdByAccountId"],
        "updatedByAccountId": campaign["updatedByAccountId"],
    }


def membership_payload(
    membership: Mapping[str, Any], *, display: Mapping[str, Any], guard_version: Optional[int] = None
) -> Dict[str, Any]:
    """Project a membership item onto ``UnitCampaignMembership``.

    Removal audit is returned as null rather than omitted: a REMOVED roster entry
    is history the admin is entitled to see, and who removed it and when is why
    the record was never deleted (§5.6).

    ``guardVersion`` rides along only where a guard row was read — the roster, for
    the sake of a removal the admin can actually perform from it. Removal requires
    both row versions, so a roster that answered only the membership version would
    leave the second half of the pair unknowable.

    ``display`` comes from :func:`unit_campaign_models.roster_display`: the Scout's
    name, their Campaign's name, and the catalog that Campaign sells from. It is read
    text rather than a stored copy, so a Scout who changes their name is shown by the
    name they have now, and a profile or Campaign row that cannot be read answers
    empty/null instead of making the roster row disappear.
    """
    return {
        "unitCampaignId": membership["unitCampaignId"],
        "unitId": membership["unitId"],
        "campaignId": membership["campaignId"],
        "profileId": membership["profileId"],
        "scoutName": str(display.get("scoutName", "")),
        "campaignName": str(display.get("campaignName", "")),
        "scoutCampaignCatalogId": display.get("scoutCampaignCatalogId"),
        "status": membership["status"],
        "joinedByAccountId": membership["joinedByAccountId"],
        "joinedAt": membership["joinedAt"],
        "removedByAccountId": membership.get("removedByAccountId"),
        "removedAt": membership.get("removedAt"),
        "version": _number(membership["version"]),
        "guardVersion": None if guard_version is None else _number(guard_version),
    }


def _campaign_marker(*, caller_id: str, operation: str, scope: str, idempotency_key: str) -> Any:
    """Resolve this request's marker address on the unit_campaigns table.

    Campaign-domain markers live on the campaign aggregate table rather than the
    Units table so a Unit-scoped audit or cleanup sweep sees them (§8.9).
    """
    return marker_keys(
        table_key="unit_campaigns",
        table_name=tables.unit_campaigns.table_name,
        actor_id=caller_id,
        operation=operation,
        scope=scope,
        idempotency_key=idempotency_key,
    )


def _positive_int(payload: Mapping[str, Any], field: str, *, minimum: int = 1) -> int:
    """Read a required version field at the top level of the input.

    ``minimum`` is 1 for the Stage 1 versions, which start at 1 on the row that created
    them. §5.19's ``fulfillmentVersion`` is the exception the parameter exists for: an
    unfulfilled Order — including every row written before Wave 3 — sits at version 0, and
    a caller has to be able to name that zero to fill the first line.
    """
    value = payload.get(field)
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} is required")
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must be an integer")
    try:
        number = int(value)
    except ValueError, ArithmeticError:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must be an integer") from None
    if number < minimum:
        raise AppError(ErrorCode.INVALID_INPUT, f"{field} must not be below {minimum}")
    return number


def _campaign_admin_guard(event: Dict[str, Any], caller_id: str, name: str) -> Dict[str, Any]:
    """Load the addressed Unit Campaign and require admin of its Unit.

    Tenancy comes from the campaign's own ``unitId``, never from a unit id the
    caller supplies: a campaign id is not an access path, and this is the single
    place the four campaign-scoped reads derive tenancy from (§1.5.6, AUTH-U).
    """
    unit_campaign_id = _query_argument(event, name)
    campaign: Dict[str, Any] = dict(unit_campaign_models.load_unit_campaign_or_not_found(unit_campaign_id))
    unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))
    return campaign


# --- createUnitCampaign (§1.5.1) -------------------------------------------------

# A generated code that collides is re-generated rather than rejected: the
# collision is a 1-in-36^16 event, and a create the user must re-type is a worse
# outcome than one more read. The ceiling keeps a storage fault from turning the
# loop into a stall.
_JOIN_CODE_ATTEMPTS = 3


def _fresh_join_code() -> str:
    """A join code no pointer claims (§5.5 uniqueness as a read)."""
    for _ in range(_JOIN_CODE_ATTEMPTS):
        code = str(unit_campaign_models.new_join_code())
        if not unit_campaign_models.join_code_taken(code):
            return code
    raise AppError(ErrorCode.CONFLICT, "Could not allocate a unique join code. Retry the create.")


def _require_usable_catalog(catalog_id: str, caller_id: str) -> None:
    """Require the referenced catalog to exist, be selectable, and be this caller's to use.

    The catalog arrives as an id the caller typed, so the read path's authorization
    rule has to be applied here too: without it, a Unit admin could point a campaign
    at another account's private catalog and read its products through the campaign.
    A catalog the caller cannot see answers as not found.
    """
    catalog = unit_campaign_models.read_catalog(catalog_id)
    if catalog is None or not unit_campaign_models.catalog_visible_to(catalog, caller_id):
        raise AppError(ErrorCode.NOT_FOUND, "Catalog not found")
    if not unit_campaign_models.catalog_is_usable(catalog):
        raise AppError(ErrorCode.INVALID_INPUT, "That catalog is deleted and cannot be used by a new Unit Campaign.")


def _created_campaign_payload(unit_campaign_id: str) -> Dict[str, Any]:
    """Reload a campaign this handler just wrote, for the result and for replay."""
    campaign = _loaded_or_internal(
        unit_campaign_models.read_unit_campaign(unit_campaign_id), "created Unit Campaign could not be loaded"
    )
    return campaign_payload(campaign)


def _create_campaign(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Create a Unit Campaign and its join-code pointer in one transaction.

    The join code is generated server-side and never derived from the campaign's
    name or year, so renaming a campaign cannot orphan the code its Scouts hold.
    The parent Unit's id is the marker's resource scope — unlike ``createUnit``,
    whose Unit does not exist yet and therefore bootstraps (§8.9).
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_id = _resource_id(payload, "unitId")
    catalog_id = _resource_id(payload, "catalogId")
    runner = IdempotentMutationRunner()

    keys = _campaign_marker(
        caller_id=caller_id, operation=CREATE_UNIT_CAMPAIGN_FIELD, scope=unit_id, idempotency_key=key
    )
    # Authorization runs before the replay: a caller whose admin grant was
    # revoked since the original attempt gets the same denial as any other
    # request, not a replayed answer.
    unit_auth.require_unit_admin(caller_id, unit_id)
    _require_usable_catalog(catalog_id, caller_id)

    replayed = _replay(
        runner,
        keys,
        fingerprint,
        CREATE_UNIT_CAMPAIGN_FIELD,
        lambda stored: _created_campaign_payload(str(stored)),
    )
    if replayed is not None:
        return replayed

    unit_campaign_id = str(unit_campaign_models.new_unit_campaign_id())
    now_iso = utc_now_iso()
    campaign = unit_campaign_models.build_unit_campaign_item(
        unit_campaign_id=unit_campaign_id,
        unit_id=unit_id,
        campaign_name=payload.get("campaignName"),
        campaign_year=payload.get("campaignYear"),
        catalog_id=catalog_id,
        join_code=_fresh_join_code(),
        created_by_account_id=caller_id,
        now_iso=now_iso,
    )
    pointer = unit_campaign_models.build_join_code_pointer_item(
        join_code=campaign["joinCode"], unit_campaign_id=unit_campaign_id, now_iso=now_iso
    )

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_campaign_id)
    for action, body in unit_campaign_models.create_campaign_actions(campaign, pointer):
        plan.add(action, body)
    build_result = _once(lambda: _created_campaign_payload(unit_campaign_id))
    runner.execute(
        keys,
        plan,
        operation=CREATE_UNIT_CAMPAIGN_FIELD,
        fingerprint=fingerprint,
        result_id=unit_campaign_id,
        load_result=lambda stored: _created_campaign_payload(str(stored)),
        result_payload=build_result,
    )
    log.info(
        "Unit Campaign created",
        unit_campaign_id=unit_campaign_id,
        unit_id=unit_id,
        caller_id=caller_id,
        catalog_id=catalog_id,
    )
    # The created row rides on the marker, because a deactivation or a catalog
    # change after this write would otherwise move the answer a retry replays.
    return build_result()


# --- updateUnitCampaign (§1.5.2) -------------------------------------------------

# The keys a campaign update legitimately carries that are also immutable storage
# fields: the locator and the concurrency token. Everything else named in
# ``IMMUTABLE_CAMPAIGN_FIELDS`` arriving in the input is a refused write.
_CAMPAIGN_UPDATE_PASSTHROUGH: frozenset[str] = frozenset({"unitCampaignId", "version", "idempotency"})


def _campaign_changes(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Only name, year, and isActive are writable; immutability is refused, not ignored.

    ``catalogId`` is what inventory, Order origin, and event product identity key
    on, so a metadata update that relocated it would move a campaign's whole
    product identity implicitly. A caller who wants a different catalog gets a
    new Unit Campaign (CAMP-M-02-02).
    """
    smuggled = {
        field: payload[field]
        for field in payload
        if field in unit_campaign_models.IMMUTABLE_CAMPAIGN_FIELDS and field not in _CAMPAIGN_UPDATE_PASSTHROUGH
    }
    unit_campaign_models.reject_immutable_campaign_changes(smuggled)

    changes: Dict[str, Any] = {}
    if "campaignName" in payload:
        changes["campaignName"] = unit_models.normalize_required_text(payload["campaignName"], "campaignName")
    if "campaignYear" in payload:
        changes["campaignYear"] = unit_campaign_models.normalize_campaign_year(payload["campaignYear"])
    if "isActive" in payload:
        if not isinstance(payload["isActive"], bool):
            raise AppError(ErrorCode.INVALID_INPUT, "isActive must be a boolean")
        changes["isActive"] = payload["isActive"]
    if not changes:
        raise AppError(ErrorCode.INVALID_INPUT, "At least one Unit Campaign field must change")
    return changes


def _versioned_campaign_update(
    unit_campaign_id: str, changes: Mapping[str, Any], *, expected_version: int, caller_id: str
) -> Dict[str, Any]:
    """The conditional campaign update: one version guard over every written field.

    Deactivation writes this row and nothing else — no inventory adjustment, no
    obligation change, no balance rewrite (CAMP-M-02-01). Active state is a
    predicate the join and listing paths read, not a counter to unwind.
    """
    names: Dict[str, str] = {"#version": "version", "#updatedAt": "updatedAt", "#updatedBy": "updatedByAccountId"}
    values: Dict[str, Any] = {
        ":expectedVersion": wire_value(expected_version),
        ":one": wire_value(1),
        ":updatedAt": wire_value(utc_now_iso()),
        ":updatedBy": wire_value(caller_id),
    }
    sets: List[str] = ["#version = #version + :one", "#updatedAt = :updatedAt", "#updatedBy = :updatedBy"]
    for field, value in changes.items():
        names[f"#{field}"] = field
        values[f":{field}"] = wire_value(value)
        sets.append(f"#{field} = :{field}")
    return {
        "TableName": tables.unit_campaigns.table_name,
        "Key": wire_key(unit_campaign_models.unit_campaign_metadata_key(unit_campaign_id)),
        "UpdateExpression": "SET " + ", ".join(sets),
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
        "ConditionExpression": "#version = :expectedVersion",
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }


def _update_campaign(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Rename, re-year, or deactivate a Unit Campaign under ``expectedVersion``.

    Tenancy is read off the stored campaign rather than the request, so an admin
    of one Unit cannot write another Unit's campaign by guessing its id. Current
    authorization runs first: a caller whose grant lapsed answers FORBIDDEN, not a
    replayed campaign. Behind it, the replay check precedes the version guard for
    the usual reason: a completed retry must not collide with the version its own
    first attempt wrote.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_campaign_id = _resource_id(payload, "unitCampaignId")
    expected_version = _expected_version(payload)
    runner = IdempotentMutationRunner()

    keys = _campaign_marker(
        caller_id=caller_id, operation=UPDATE_UNIT_CAMPAIGN_FIELD, scope=unit_campaign_id, idempotency_key=key
    )
    campaign = unit_campaign_models.load_unit_campaign_or_not_found(unit_campaign_id)
    unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        UPDATE_UNIT_CAMPAIGN_FIELD,
        lambda stored: _created_campaign_payload(str(stored)),
    )
    if replayed is not None:
        return replayed

    changes = _campaign_changes(payload)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_campaign_id)
    plan.add(
        "Update",
        _versioned_campaign_update(unit_campaign_id, changes, expected_version=expected_version, caller_id=caller_id),
    )
    build_result = _once(lambda: _created_campaign_payload(unit_campaign_id))
    runner.execute(
        keys,
        plan,
        operation=UPDATE_UNIT_CAMPAIGN_FIELD,
        fingerprint=fingerprint,
        result_id=unit_campaign_id,
        load_result=lambda stored: _created_campaign_payload(str(stored)),
        result_payload=build_result,
    )
    refreshed = build_result()
    log.info(
        "Unit Campaign updated",
        unit_campaign_id=unit_campaign_id,
        caller_id=caller_id,
        version=refreshed["version"],
        changed=sorted(changes),
    )
    return refreshed


# --- unitCampaignJoinInfo (§1.5.3) -----------------------------------------------

_JOIN_CODE_UNUSABLE = "Join code not found or no longer active"


def _display_name(unit: Mapping[str, Any]) -> str:
    """The Unit name a Scout sees before joining.

    ``displayName`` is optional storage, so the metadata a Unit is always
    required to carry forms the fallback: the preview field is non-null, and a
    Unit with no chosen name still has a truthful one.
    """
    stored = unit.get("displayName")
    if stored:
        return str(stored)
    return f"{unit['unitType']} {unit['unitNumber']} ({unit['city']}, {unit['state']})"


def _join_preview_payload(unit_campaign: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the member-safe preview, and nothing else, from a resolved campaign.

    The five fields below are the whole allowlist §3.2 gives a bare join code: no
    join code, no campaign or unit ids, no catalog id, no settings, no roster, no
    counts. A later field added here is a disclosure, which is why the projection
    is written out rather than filtered from the item.
    """
    unit = unit_models.read_unit(str(unit_campaign["unitId"]))
    catalog = unit_campaign_models.read_catalog(str(unit_campaign["catalogId"]))
    if unit is None or catalog is None:
        # A pointer to a campaign whose Unit or catalog is gone is unusable, and
        # the only honest answer is the one an unknown code already gets.
        raise AppError(ErrorCode.NOT_FOUND, _JOIN_CODE_UNUSABLE)
    return {
        "unitDisplayName": _display_name(unit),
        "campaignName": unit_campaign["campaignName"],
        "campaignYear": _number(unit_campaign["campaignYear"]),
        "catalogName": str(catalog["catalogName"]),
        "isActive": bool(unit_campaign["isActive"]),
    }


def _join_info(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Resolve a join code for any authenticated Account (§1.5.3).

    Two consistent reads — pointer, then the campaign it names — so a code that
    was just revoked or a campaign that was just deactivated stops answering
    immediately rather than from a cache. Unknown, malformed, dangling, and
    inactive codes answer identically: a probe learns nothing about which case it
    hit, and an anonymous caller never reaches here (AUTH-C-01).
    """
    unit_campaign = unit_campaign_models.resolve_join_code(
        unit_campaign_models.normalize_join_code(_query_argument(event, "joinCode"))
    )
    if unit_campaign is None:
        raise AppError(ErrorCode.NOT_FOUND, _JOIN_CODE_UNUSABLE)
    preview = _join_preview_payload(unit_campaign)
    # The caller is recorded, never the code: a join code is a credential, and a
    # code being walked through an account is the enumeration this read invites.
    get_logger(__name__).info(
        "Unit Campaign join preview served",
        caller_id=caller_id,
        unit_campaign_id=unit_campaign["unitCampaignId"],
    )
    return preview


# --- joinUnitCampaign (§1.5.4) ---------------------------------------------------


def _joined_membership_payload(unit_campaign_id: str, campaign_id: str) -> Dict[str, Any]:
    """Reload the membership a join wrote, for the result and for a replay.

    The Scout identity comes from the Campaign row rather than from the caller:
    the fingerprint already binds ``campaignId``, so a replay resolves the same
    Profile the original attempt did.
    """
    scout = unit_campaign_models.read_scout_campaign(campaign_id)
    membership = unit_campaign_models.read_membership(unit_campaign_id, str(scout["profileId"])) if scout else None
    member = _loaded_or_internal(membership, "joined membership could not be loaded")
    return membership_payload(
        member, display=unit_campaign_models.membership_display(str(member["profileId"]), campaign_id)
    )


def _join_scout_profile(caller_id: str, campaign_id: str) -> str:
    """The Profile the joining Campaign belongs to, after the Owner/WRITE check.

    Authorization is the existing Profile Owner/WRITE rule: the join is an act of
    the Scout, not an appointment by a Unit Admin, which is why a READ-only share
    and a substituted ``campaignId`` both fail here (CAMP-M-03-02). A Campaign the
    caller cannot see is absent rather than forbidden.
    """
    scout = unit_campaign_models.read_scout_campaign(campaign_id)
    if scout is None:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    profile_id = str(scout["profileId"])
    require_profile_access(caller_id, profile_id, "WRITE")
    return profile_id


def _join_target_campaign(join_code: str) -> Dict[str, Any]:
    """The Unit Campaign a code names.

    An unknown code, a redeemed code, and a code on a campaign the Unit closed
    answer identically — the same refusal a code that never existed earns, so the
    endpoint cannot be walked to enumerate Units.
    """
    unit_campaign: Dict[str, Any] | None = unit_campaign_models.resolve_join_code(join_code)
    if unit_campaign is None:
        raise AppError(ErrorCode.NOT_FOUND, _JOIN_CODE_UNUSABLE)
    return unit_campaign


def _join_guard(campaign_id: str, unit_campaign_id: str) -> Dict[str, Any] | None:
    """The Campaign's join guard, unless it is already held by another campaign.

    One Scout Campaign belongs to one Unit Campaign at a time; the guard row is
    where that is written, so leaving a roster is a precondition to joining this
    one rather than a silent hand-off between Units.
    """
    guard: Dict[str, Any] | None = unit_campaign_models.read_membership_guard(campaign_id)
    target = unit_campaign_models.guard_active_unit_campaign_id(guard)
    if target is not None and target != unit_campaign_id:
        raise AppError(
            ErrorCode.CONFLICT,
            "This Scout Campaign is already joined to another Unit Campaign; leave that roster before joining this one.",
        )
    return guard


def _joinable_membership(unit_campaign_id: str, profile_id: str, campaign_id: str) -> Dict[str, Any] | None:
    """The roster row this join would write, if a joinable one exists.

    A row that belongs to a different Scout Campaign, or one already ACTIVE, is a
    conflict rather than a re-write: the roster identifies one Campaign per Scout,
    and a second active membership in the same campaign would double-count the
    Scout's participation.
    """
    membership: Dict[str, Any] | None = unit_campaign_models.read_membership(unit_campaign_id, profile_id)
    if membership is not None and str(membership["campaignId"]) != campaign_id:
        raise AppError(ErrorCode.CONFLICT, "This Scout's roster entry belongs to a different Scout Campaign.")
    if membership is not None and str(membership["status"]) == unit_campaign_models.MEMBERSHIP_STATUS_ACTIVE:
        raise AppError(ErrorCode.CONFLICT, "This Scout Campaign already has an active membership here.")
    return membership


def _stage_join_plan(
    runner: Any,
    keys: Any,
    fingerprint: str,
    membership: Dict[str, Any] | None,
    member: Dict[str, Any],
    campaign_id: str,
    profile_id: str,
    unit_campaign: Dict[str, Any],
    unit_campaign_id: str,
    guard: Dict[str, Any] | None,
    now_iso: str,
) -> Any:
    # `WritePlan` arrives through `import_from_utils`, which is untyped, so the
    # plan is returned as Any rather than a name mypy cannot see through.
    """The four rows a join moves, in one plan: marker, roster, guard, Campaign link.

    A row that already exists is reactivated against its own version rather than
    overwritten, so a second join after a removal is a transition the roster
    history can show — not a rewrite of the row that records the removal.
    """
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_campaign_id)
    if membership is None:
        plan.add(*unit_campaign_models.put_membership_action(member))
    else:
        plan.add(
            *unit_campaign_models.reactivate_membership_action(member, expected_version=_number(membership["version"]))
        )
    plan.add(
        *unit_campaign_models.guard_claim_action(
            campaign_id=campaign_id,
            profile_id=profile_id,
            active_unit_campaign_id=unit_campaign_id,
            unit_id=str(unit_campaign["unitId"]),
            expected_membership_version=_number(guard["membershipVersion"]) if guard is not None else None,
            now_iso=now_iso,
        )
    )
    plan.add(
        *unit_campaign_models.campaign_latest_link_action(
            profile_id=profile_id,
            campaign_id=campaign_id,
            unit_id=str(unit_campaign["unitId"]),
            unit_campaign_id=unit_campaign_id,
        )
    )
    return plan


def _join_campaign(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Join a Scout Campaign to a Unit Campaign with its code (§1.5.4).

    Four rows commit together — membership, guard, the Campaign's joined-scope
    link, and the marker — so a Scout is never a member in one row and unjoined
    in another. Every refusal (unknown code, guard held elsewhere, a roster row
    that is not this Campaign's, an already-active membership) is decided before
    any row is written, so a join that is refused leaves nothing behind.

    The replay check runs first here, unlike the admin-gated mutations: the join
    is an act of the Scout, not an admin, so there is no revoked-admin exposure
    for SEC-1 to close, and a code holder or Scout must be able to replay the
    answer its committed attempt produced. The business refusals stay behind the
    replay for the same reason — a completed retry answers the original
    membership instead of re-running guards that may since have changed.

    The idempotency marker is scoped to the join code: the same code plus the
    same key is one join, however many campaigns the caller names in between.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    join_code = unit_campaign_models.normalize_join_code(_resource_id(payload, "joinCode"))
    campaign_id = _resource_id(payload, "campaignId")
    runner = IdempotentMutationRunner()

    keys = _campaign_marker(
        caller_id=caller_id, operation=JOIN_UNIT_CAMPAIGN_FIELD, scope=join_code, idempotency_key=key
    )
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        JOIN_UNIT_CAMPAIGN_FIELD,
        lambda stored: _joined_membership_payload(str(stored), campaign_id),
    )
    if replayed is not None:
        return replayed

    profile_id = _join_scout_profile(caller_id, campaign_id)
    unit_campaign = _join_target_campaign(join_code)
    unit_campaign_id = str(unit_campaign["unitCampaignId"])
    guard = _join_guard(campaign_id, unit_campaign_id)
    membership = _joinable_membership(unit_campaign_id, profile_id, campaign_id)

    now_iso = utc_now_iso()
    member = unit_campaign_models.build_membership_item(
        unit_campaign_id=unit_campaign_id,
        unit_id=str(unit_campaign["unitId"]),
        campaign_id=campaign_id,
        profile_id=profile_id,
        joined_by_account_id=caller_id,
        now_iso=now_iso,
    )
    plan = _stage_join_plan(
        runner,
        keys,
        fingerprint,
        membership,
        member,
        campaign_id,
        profile_id,
        unit_campaign,
        unit_campaign_id,
        guard,
        now_iso,
    )
    build_result = _once(lambda: _joined_membership_payload(unit_campaign_id, campaign_id))
    runner.execute(
        keys,
        plan,
        operation=JOIN_UNIT_CAMPAIGN_FIELD,
        fingerprint=fingerprint,
        result_id=unit_campaign_id,
        load_result=lambda stored: _joined_membership_payload(str(stored), campaign_id),
        result_payload=build_result,
    )
    log.info(
        "Scout Campaign joined",
        unit_campaign_id=unit_campaign_id,
        campaign_id=campaign_id,
        caller_id=caller_id,
        rejoined=membership is not None,
    )
    # The membership rides on the marker: a removal after this write blanks the
    # guard and flips the row, so re-reading them would answer the removal, not
    # this join.
    return build_result()


# --- removeUnitCampaignMembership (§1.5.5) ---------------------------------------


def _remove_membership(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Set a roster entry REMOVED and free the Scout Campaign's guard (§1.5.5).

    Removal is a status transition, never a delete: signups, work, credit,
    custody, and Orders keep pointing at this record, and the Campaign keeps its
    joined-scope link, so joined history survives a removal (API-FIX-05). What
    removal does change is eligibility, and it changes it in one transaction: the
    guard version this write bumps is exactly the version a signup conditions on,
    so a signup racing the removal is cancelled rather than committed after it
    (CAMP-M-04-02).

    Two versions are required because two rows move. A caller holding either one
    stale loses the whole transaction — the roster is never REMOVED while the
    slot is still claimed (§1.5.5, VER-01).

    Current authorization runs first: a caller whose admin grant was revoked
    since the original attempt gets the same denial as any other request, not a
    replayed membership.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_campaign_id = _resource_id(payload, "unitCampaignId")
    campaign_id = _resource_id(payload, "campaignId")
    membership_version = _positive_int(payload, "expectedMembershipVersion")
    guard_version = _positive_int(payload, "expectedGuardVersion")
    runner = IdempotentMutationRunner()

    keys = _campaign_marker(
        caller_id=caller_id, operation=REMOVE_MEMBERSHIP_FIELD, scope=unit_campaign_id, idempotency_key=key
    )
    campaign = unit_campaign_models.load_unit_campaign_or_not_found(unit_campaign_id)
    unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        REMOVE_MEMBERSHIP_FIELD,
        lambda stored: _joined_membership_payload(str(stored), campaign_id),
    )
    if replayed is not None:
        return replayed

    scout = unit_campaign_models.read_scout_campaign(campaign_id)
    if scout is None:
        raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
    membership = unit_campaign_models.read_membership(unit_campaign_id, str(scout["profileId"]))
    if membership is None or str(membership["campaignId"]) != campaign_id:
        raise AppError(ErrorCode.NOT_FOUND, "Roster entry not found")

    now_iso = utc_now_iso()
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=unit_campaign_id)
    plan.add(
        *unit_campaign_models.remove_membership_action(
            unit_campaign_id=unit_campaign_id,
            profile_id=str(scout["profileId"]),
            expected_version=membership_version,
            removed_by_account_id=caller_id,
            now_iso=now_iso,
        )
    )
    plan.add(
        *unit_campaign_models.guard_release_action(
            campaign_id=campaign_id,
            expected_membership_version=guard_version,
            expected_unit_campaign_id=unit_campaign_id,
            now_iso=now_iso,
        )
    )
    build_result = _once(lambda: _joined_membership_payload(unit_campaign_id, campaign_id))
    runner.execute(
        keys,
        plan,
        operation=REMOVE_MEMBERSHIP_FIELD,
        fingerprint=fingerprint,
        result_id=unit_campaign_id,
        load_result=lambda stored: _joined_membership_payload(str(stored), campaign_id),
        result_payload=build_result,
    )
    log.info(
        "Unit Campaign membership removed",
        unit_campaign_id=unit_campaign_id,
        campaign_id=campaign_id,
        caller_id=caller_id,
    )
    # The removed row rides on the marker, so a retry answers the removal it
    # produced rather than the row's current (possibly rejoined) state.
    return build_result()


# --- campaign and roster queries (§1.5.6) ----------------------------------------


def _get_campaign(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One campaign's administrative view, join code and version included.

    A Scout who holds the join code uses ``unitCampaignJoinInfo`` instead: this
    query answers nothing to an account without a grant on the parent Unit
    (UNIT-Q-07-02, AUTH-U).
    """
    return campaign_payload(_campaign_admin_guard(event, caller_id, "unitCampaignId"))


def _optional_boolean(event: Dict[str, Any], name: str) -> Optional[bool]:
    """Read an optional boolean filter argument (``isActive``)."""
    arguments = event.get("arguments")
    value = arguments.get(name) if isinstance(arguments, Mapping) else None
    if value is None:
        return None
    if not isinstance(value, bool):
        raise AppError(ErrorCode.INVALID_INPUT, f"{name} must be a boolean")
    return value


def _list_campaigns(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """A Unit's campaigns, newest first, optionally filtered by active state.

    The active filter is part of the cursor's scope: a cursor issued for the
    active list is refused against the deactivated list rather than silently
    skipping rows (PAGE-01, UNIT-Q-08-01).
    """
    unit_id = _query_argument(event, "unitId")
    unit_auth.require_unit_admin(caller_id, unit_id)
    is_active = _optional_boolean(event, "isActive")
    items = [
        campaign_payload(campaign)
        for campaign in unit_campaign_models.list_unit_campaigns(unit_id)
        if is_active is None or bool(campaign["isActive"]) == is_active
    ]
    filter_token = "all" if is_active is None else str(is_active).lower()
    return dict(paginate_page(items, f"{UNIT_CAMPAIGNS_FIELD}#{unit_id}#{filter_token}", _page_argument(event)))


def _catalog_products(catalog: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The catalog's products in display order (the SDL ``Product`` shape).

    Returned as stored, including a catalog later soft-deleted: a campaign's
    sales sheets and Order history keep their product names and prices, which is
    why deletion is refused while a campaign references the catalog and is not
    allowed to rewrite the campaign.
    """
    products = [item for item in (catalog.get("products") or []) if isinstance(item, Mapping)]
    return [
        {
            "productId": str(item["productId"]),
            "productName": str(item["productName"]),
            "description": item.get("description"),
            "price": float(item["price"]),
            "sortOrder": int(item["sortOrder"]),
        }
        for item in sorted(products, key=lambda product: int(product["sortOrder"]))
    ]


def _campaign_catalog(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The campaign's catalog and products, for browser sales sheets (§1.5.6).

    Admin-only: products and prices are not participant data at Stage 1, and the
    join preview gives the catalog's name alone.
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    catalog = unit_campaign_models.read_catalog(str(campaign["catalogId"]))
    # The id comes from the campaign row rather than from the caller, so this is not
    # a lookup-by-id hole. It is still a disclosure path: the catalog had to be
    # answerable to the admin who attached it, so that is the identity the rule is
    # checked against — a campaign written around someone else's private catalog by
    # any path that skipped the create check answers as missing, while a co-admin of
    # a campaign legitimately built on another admin's catalog still reads it.
    if catalog is None or not unit_campaign_models.catalog_visible_to(
        catalog, str(campaign.get("createdByAccountId") or "")
    ):
        raise AppError(ErrorCode.NOT_FOUND, "catalog could not be loaded")
    return {
        "catalogId": str(catalog["catalogId"]),
        "catalogName": str(catalog["catalogName"]),
        "products": _catalog_products(catalog),
    }


def _list_roster(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """A campaign's roster, removed history included unless filtered out (§1.5.6).

    Removed entries stay because the credit, Orders, and custody that belong to a
    Scout who left are still this campaign's history; filtering to ACTIVE is a
    presentation choice, not a deletion (UNIT-Q-09-01).
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    arguments = event.get("arguments")
    raw_status = arguments.get("status") if isinstance(arguments, Mapping) else None
    status = None if raw_status is None else unit_campaign_models.normalize_membership_status(raw_status)
    unit_campaign_id = str(campaign["unitCampaignId"])
    members = unit_campaign_models.list_memberships(unit_campaign_id, status=status)
    displays = unit_campaign_models.roster_display(members)
    items = []
    for membership in members:
        # Only an ACTIVE row can be removed, so only an ACTIVE row needs its guard
        # version read back. A REMOVED row's slot is already free, and answering
        # null says so without inventing a version for a row no mutation accepts.
        guard_version = None
        if str(membership["status"]) == unit_campaign_models.MEMBERSHIP_STATUS_ACTIVE:
            guard = unit_campaign_models.read_membership_guard(str(membership["campaignId"]))
            if guard is not None:
                guard_version = _number(guard["membershipVersion"])
        items.append(
            membership_payload(
                membership,
                display=displays[str(membership["profileId"])],
                guard_version=guard_version,
            )
        )
    return dict(
        paginate_page(
            items, f"{UNIT_CAMPAIGN_ROSTER_FIELD}#{unit_campaign_id}#{status or 'ALL'}", _page_argument(event)
        )
    )


# --- Stage 2 inventory writes (§2.2) ---------------------------------------------


def _inventory_marker(*, caller_id: str, operation: str, scope: str, idempotency_key: str) -> Any:
    """Resolve this request's marker address on the inventory table.

    A stock marker lives on the table whose rows the mutation writes, so one
    campaign's audit or cleanup sweep sees the requests that touched its stock and a
    receipt does not put a row on the Units aggregate (§8.9). The resource scope is
    the Unit Campaign, which every inventory mutation addresses.
    """
    return marker_keys(
        table_key="inventory",
        table_name=tables.inventory.table_name,
        actor_id=caller_id,
        operation=operation,
        scope=scope,
        idempotency_key=idempotency_key,
    )


def _campaign_for_inventory_write(payload: Mapping[str, Any], caller_id: str) -> Dict[str, Any]:
    """Load the addressed Unit Campaign and require admin of its Unit.

    Tenancy comes from the campaign's own ``unitId``, never from a Unit id in the
    request: a campaign id is not an access path, and this is the same rule the
    campaign-scoped reads use (§1.5.6, AUTH-U).
    """
    unit_campaign_id = _resource_id(payload, "unitCampaignId")
    campaign: Dict[str, Any] = dict(unit_campaign_models.load_unit_campaign_or_not_found(unit_campaign_id))
    unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))
    return campaign


def _catalog_product_ids(catalog: Mapping[str, Any]) -> set[str]:
    """The product ids a campaign's catalog offers."""
    products = catalog.get("products") or []
    return {str(item["productId"]) for item in products if isinstance(item, Mapping) and item.get("productId")}


def _catalog_or_not_found(campaign: Mapping[str, Any]) -> Mapping[str, Any]:
    """The campaign's own catalog row, or the same ``NOT_FOUND`` a missing catalog answers."""
    catalog = cast(Optional[Mapping[str, Any]], unit_campaign_models.read_catalog(str(campaign["catalogId"])))
    if catalog is None:
        raise AppError(ErrorCode.NOT_FOUND, "The campaign's catalog could not be loaded")
    return catalog


def _require_catalog_product(campaign: Mapping[str, Any], product_id: str) -> None:
    """Require a receipt's product to be one this campaign sells (§2.2.1).

    A receipt is how stock enters the catalog a Scout can buy from, so stock for a
    product the campaign does not offer is stock nobody can sell and nothing can
    account for at finalization. The catalog named on the campaign row is the
    allowlist; the caller does not choose it.

    An adjustment is deliberately NOT gated this way: a catalog that dropped a
    product still leaves Kernels in the physical count, and an admin has to be able
    to count them out. Refusing the adjustment would strand the stock in a balance
    no one may correct.
    """
    catalog = _catalog_or_not_found(campaign)
    if product_id not in _catalog_product_ids(catalog):
        raise AppError(ErrorCode.INVALID_INPUT, "productId is not a product of this campaign's catalog")


def _require_catalog_products(campaign: Mapping[str, Any], product_ids: Sequence[str]) -> None:
    """Require every product of one batch to be one this campaign sells (§2.2.1, EVT-M-04).

    The same allowlist as :func:`_require_catalog_product`, applied once per batch: the
    catalog named on the campaign row is the allowlist and the caller does not choose it,
    and an assignment for a product the campaign cannot sell is stock nothing can account
    for at finalization. It names every product it refused rather than the first, because
    a Kernel correcting a 16-line entry should not have to discover the second bad id on
    the next attempt.
    """
    offered = _catalog_product_ids(_catalog_or_not_found(campaign))
    missing = sorted({product_id for product_id in product_ids if product_id not in offered})
    if missing:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "productId is not a product of this campaign's catalog: " + ", ".join(missing),
        )


def _balance_quantity(existing: Optional[Mapping[str, Any]], attribute: str) -> int:
    """One quantity on the read balance, or zero for a product with no balance row."""
    if existing is None:
        return 0
    return _number(existing.get(attribute, 0))


def _require_balance_floor(existing: Optional[Mapping[str, Any]], delta: int) -> None:
    """Refuse an adjustment whose result breaks §4.1 before anything is staged.

    The same floor rides the write condition, so this is not the race guard — the
    condition is. What the pre-check buys is the right verdict for a request that was
    impossible the moment it arrived: ``INVALID_INPUT`` the caller can act on, rather
    than ``CONFLICT``, which tells them to re-read something that never changed.
    """
    physical = _balance_quantity(existing, inventory_models.KERNEL_PHYSICAL_QTY)
    reserved = _balance_quantity(existing, inventory_models.SOLD_IN_POSSESSION_QTY)
    if physical + delta < 0:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "quantityDelta would leave fewer Kernels in physical stock than this campaign holds",
        )
    if physical + delta < reserved:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"quantityDelta would take physical stock below the {reserved} Kernels already reserved for We Owe",
        )


def _require_council_floor(existing: Optional[Mapping[str, Any]], delta: int) -> None:
    """Refuse an on-order adjustment that would drive the separate balance negative."""
    if _balance_quantity(existing, inventory_models.COUNCIL_ON_ORDER_QTY) + delta < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "quantityDelta would leave Council-on-order below zero")


def _stage_balance_change(
    plan: Any,
    unit_campaign_id: str,
    product_id: str,
    existing: Optional[Mapping[str, Any]],
    *,
    kernel_physical_delta: int,
    council_on_order_delta: int,
    occurred_at: str,
) -> int:
    """Stage the one balance write this mutation makes, and report the version it produces.

    A DynamoDB transaction may not address the same item twice, so a delta cannot
    ride a read-then-increment pair; the write is chosen from the read this request
    already took. Two shapes:

    - no row yet — a conditional ``Put`` of the post-delta balance. The
      ``attribute_not_exists`` guard is what makes two concurrent first receipts of one
      product cancel one another instead of each starting from zero, and because the
      pre-check rejected a delta that would take zero below itself, the row this
      creates is legal by construction.
    - a row exists — a version-guarded increment carrying the §4.1 floors in its
      condition, so a writer whose read went stale loses the whole transaction rather
      than driving physical stock under what We Owe already reserved.
    """
    if existing is None:
        item = inventory_models.build_inventory_balance_item(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            kernel_physical_qty=kernel_physical_delta,
            council_on_order_qty=council_on_order_delta,
            now_iso=occurred_at,
        )
        plan.add(*inventory_models.put_inventory_balance_action(item))
        return 1
    current_version = _number(existing[inventory_models.VERSION_ATTRIBUTE])
    plan.add(
        *inventory_models.inventory_balance_delta_action(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            existing=existing,
            expected_version=current_version,
            kernel_physical_delta=kernel_physical_delta,
            council_on_order_delta=council_on_order_delta,
            now_iso=occurred_at,
        )
    )
    return current_version + 1


def _position_sections(unit_campaign_id: str, product_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """The balance, allocation, and custody rows behind one product, read consistently."""
    return dict(inventory_models.inventory_position_rows(unit_campaign_id, product_id))


def _balance_payload(balance: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a stored ``InventoryBalance`` row onto the SDL fields (§5.7)."""
    return {
        "unitCampaignId": str(balance["unitCampaignId"]),
        "productId": str(balance["productId"]),
        "kernelPhysicalQty": _number(balance[inventory_models.KERNEL_PHYSICAL_QTY]),
        "soldInPossessionQty": _number(balance[inventory_models.SOLD_IN_POSSESSION_QTY]),
        "councilOnOrderQty": _number(balance[inventory_models.COUNCIL_ON_ORDER_QTY]),
        "version": _number(balance[inventory_models.VERSION_ATTRIBUTE]),
        "createdAt": str(balance["createdAt"]),
        "updatedAt": str(balance["updatedAt"]),
    }


def _zero_position(unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    """The balance half of a position that has no row yet.

    A catalog product with nothing received is a real state of a campaign's stock, so
    it answers with zeros at version 0 rather than as missing: version 0 says no row
    exists behind the number.
    """
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "kernelPhysicalQty": 0,
        "soldInPossessionQty": 0,
        "councilOnOrderQty": 0,
        "version": 0,
        "createdAt": None,
        "updatedAt": None,
    }


def _position_payload(
    unit_campaign_id: str,
    product_id: str,
    sections: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """One product's position: its stored balance plus the §7 quantities derived from the rows.

    The derived quantities are computed from the allocation and custody rows on every
    read, never from a stored copy, so a page cannot show a number some earlier write
    forgot to update.
    """
    buckets = sections if sections is not None else _position_sections(unit_campaign_id, product_id)
    balance = buckets["balance"][0] if buckets["balance"] else None
    derived = inventory_models.derived_inventory_quantities(balance, buckets["allocations"], buckets["custody"])
    stored = _balance_payload(balance) if balance is not None else _zero_position(unit_campaign_id, product_id)
    return {**stored, **derived}


def _written_position(unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    """Rebuild a position this handler just wrote; a missing row is an internal fault."""
    if not _position_sections(unit_campaign_id, product_id)["balance"]:
        raise AppError(ErrorCode.INTERNAL_ERROR, "updated inventory balance could not be loaded")
    return _position_payload(unit_campaign_id, product_id)


def _movement_payload(movement: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an append-only ``InventoryMovement`` row onto the SDL fields (§5.8)."""
    version = movement.get(inventory_models.INVENTORY_VERSION_ATTRIBUTE)
    return {
        "movementId": str(movement[inventory_models.MOVEMENT_ID_ATTRIBUTE]),
        "unitCampaignId": str(movement[inventory_models.UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        "productId": str(movement[inventory_models.PRODUCT_ID_ATTRIBUTE]),
        "movementType": str(movement[inventory_models.MOVEMENT_TYPE_ATTRIBUTE]),
        "kernelPhysicalDelta": _number(movement.get(inventory_models.KERNEL_PHYSICAL_DELTA, 0)),
        "soldPossessionDelta": _number(movement.get(inventory_models.SOLD_POSSESSION_DELTA, 0)),
        "withScoutDelta": _number(movement.get(inventory_models.WITH_SCOUT_DELTA, 0)),
        "assignedDelta": _number(movement.get(inventory_models.ASSIGNED_DELTA, 0)),
        "councilOnOrderDelta": _number(movement.get(inventory_models.COUNCIL_ON_ORDER_DELTA, 0)),
        "profileId": movement.get(inventory_models.PROFILE_ID_ATTRIBUTE),
        "showAndSellId": movement.get(inventory_models.SHOW_AND_SELL_ID_ATTRIBUTE),
        "saleId": movement.get(inventory_models.SALE_ID_ATTRIBUTE),
        "orderId": movement.get(inventory_models.ORDER_ID_ATTRIBUTE),
        "weOweId": movement.get(inventory_models.WE_OWE_ID_ATTRIBUTE),
        "fulfillmentId": movement.get(inventory_models.FULFILLMENT_ID_ATTRIBUTE),
        "finalizationId": movement.get(inventory_models.FINALIZATION_ID_ATTRIBUTE),
        "reason": movement.get(inventory_models.REASON_ATTRIBUTE),
        "actorAccountId": str(movement[inventory_models.ACTOR_ACCOUNT_ID_ATTRIBUTE]),
        "occurredAt": str(movement[inventory_models.OCCURRED_AT_ATTRIBUTE]),
        "inventoryVersion": None if version is None else _number(version),
        "idempotencyKey": str(movement[inventory_models.IDEMPOTENCY_KEY_ATTRIBUTE]),
    }


def _apply_balance_change(
    payload: Mapping[str, Any],
    campaign: Mapping[str, Any],
    *,
    caller_id: str,
    field: str,
    movement_type: str,
    product_id: str,
    kernel_physical_delta: int,
    council_on_order_delta: int,
    reason: Optional[str],
    occurred_at: str,
) -> Dict[str, Any]:
    """Commit one balance change, its movement, and its marker in one transaction.

    The three Stage 2 balance writes differ only in which quantity moves, whether the
    product has to be in the catalog, and whether a reason is mandatory. Everything
    else is the same contract and lives here once: current authorization ahead of the
    replay (a revoked admin gets the denial, not a replayed answer), the replay ahead
    of the floor check (a completed retry must not collide with the version its own
    first attempt wrote, and a retry of a rejected request is still rejected), the
    marker staged first in the plan, and one conditional balance write paired with one
    appended movement (§8.4, §8.9).

    The movement's ``inventoryVersion`` is the version the balance write produces. The
    version guard inside that write is what makes the statement true: a writer whose
    read went stale cancels the whole plan, so no movement is ever recorded against a
    balance this request did not change.
    """
    log = get_logger(__name__)
    unit_campaign_id = str(campaign["unitCampaignId"])
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()
    keys = _inventory_marker(caller_id=caller_id, operation=field, scope=unit_campaign_id, idempotency_key=key)
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        field,
        lambda stored: _written_position(unit_campaign_id, str(stored)),
    )
    if replayed is not None:
        return replayed

    existing = inventory_models.read_inventory_balance(unit_campaign_id, product_id)
    if kernel_physical_delta:
        _require_balance_floor(existing, kernel_physical_delta)
    if council_on_order_delta:
        _require_council_floor(existing, council_on_order_delta)

    movement_id = str(inventory_models.new_inventory_movement_id())
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=product_id)
    version = _stage_balance_change(
        plan,
        unit_campaign_id,
        product_id,
        existing,
        kernel_physical_delta=kernel_physical_delta,
        council_on_order_delta=council_on_order_delta,
        occurred_at=occurred_at,
    )
    plan.add(
        *inventory_models.put_inventory_movement_action(
            inventory_models.build_inventory_movement_item(
                movement_id=movement_id,
                unit_campaign_id=unit_campaign_id,
                product_id=product_id,
                movement_type=movement_type,
                actor_account_id=caller_id,
                occurred_at=occurred_at,
                idempotency_key=key,
                kernel_physical_delta=kernel_physical_delta,
                council_on_order_delta=council_on_order_delta,
                reason=reason,
                inventory_version=version,
            )
        )
    )
    build_result = _once(lambda: _written_position(unit_campaign_id, product_id))
    runner.execute(
        keys,
        plan,
        operation=field,
        fingerprint=fingerprint,
        result_id=product_id,
        load_result=lambda stored: _written_position(unit_campaign_id, str(stored)),
        result_payload=build_result,
    )
    log.info(
        "Inventory balance changed",
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        movement_type=movement_type,
        movement_id=movement_id,
        version=version,
        caller_id=caller_id,
    )
    return build_result()


# --- recordInventoryReceipt (§2.2.1) ---------------------------------------------


def _record_receipt(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Receive stock into one product's physical balance.

    A receipt moves ``kernelPhysicalQty`` and nothing else: it creates no Order, no
    payment, no credit, and no We Owe obligation, which is what keeps the stock count
    the admin enters separate from the money a Show & Sell settles (§2.2.1). The
    product must be in the campaign's catalog; ``occurredAt`` is the business moment
    the stock arrived, which the admin may backdate because the audit trail records
    what happened rather than what the terminal saw.
    """
    payload = _require_input(event)
    campaign = _campaign_for_inventory_write(payload, caller_id)
    product_id = inventory_models.normalize_inventory_id(payload.get("productId"), "productId")
    quantity = inventory_models.normalize_quantity(payload.get("quantity"), "quantity", minimum=1)
    occurred_at = inventory_models.normalize_moment(payload.get("occurredAt") or utc_now_iso(), "occurredAt")
    _require_catalog_product(campaign, product_id)
    return _apply_balance_change(
        payload,
        campaign,
        caller_id=caller_id,
        field=RECORD_RECEIPT_FIELD,
        movement_type=inventory_models.RECEIPT,
        product_id=product_id,
        kernel_physical_delta=quantity,
        council_on_order_delta=0,
        reason=None,
        occurred_at=occurred_at,
    )


# --- adjustInventory (§2.2.2) ----------------------------------------------------


def _adjust_inventory(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Move physical stock by a signed amount, with a mandatory reason.

    The reason is not decoration: an adjustment is the one path that changes stock
    with no Order and no event behind it, so the audit row has to say why — a counted
    miscount, damage, a gift, a trade. A trade or gift still adjusts only stock here:
    taking payment for it is a different operation with its own record, and an
    adjustment that also moved money would make the two balances impossible to
    reconcile against each other (INV-M-02-02).
    """
    payload = _require_input(event)
    campaign = _campaign_for_inventory_write(payload, caller_id)
    product_id = inventory_models.normalize_inventory_id(payload.get("productId"), "productId")
    delta = inventory_models.normalize_signed_delta(payload.get("quantityDelta"), "quantityDelta", nonzero=True)
    reason = inventory_models.normalize_reason(payload.get("reason"), "reason", required=True)
    occurred_at = inventory_models.normalize_moment(payload.get("occurredAt") or utc_now_iso(), "occurredAt")
    return _apply_balance_change(
        payload,
        campaign,
        caller_id=caller_id,
        field=ADJUST_INVENTORY_FIELD,
        movement_type=inventory_models.STOCK_ADJUSTMENT,
        product_id=product_id,
        kernel_physical_delta=delta,
        council_on_order_delta=0,
        reason=reason,
        occurred_at=occurred_at,
    )


# --- adjustCouncilOnOrder (§2.2.3) -----------------------------------------------


def _adjust_council(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Move the separate Council-on-order balance and nothing else.

    Council-on-order is expected supply the Council has promised to bring: it is
    counted beside the campaign's Kernels, never inside them, so this write touches
    ``councilOnOrderQty`` alone and leaves physical, sellable, assigned, custody, and
    We Owe demand exactly as they were. It is deliberately not derived from the
    campaign's Council Needs — a need is a request, an on-order is a promise, and
    auto-subtracting one from the other would make both unreadable (§4.1).
    """
    payload = _require_input(event)
    campaign = _campaign_for_inventory_write(payload, caller_id)
    product_id = inventory_models.normalize_inventory_id(payload.get("productId"), "productId")
    delta = inventory_models.normalize_signed_delta(payload.get("quantityDelta"), "quantityDelta", nonzero=True)
    reason = inventory_models.normalize_reason(payload.get("reason"), "reason", required=False)
    occurred_at = inventory_models.normalize_moment(payload.get("occurredAt") or utc_now_iso(), "occurredAt")
    return _apply_balance_change(
        payload,
        campaign,
        caller_id=caller_id,
        field=ADJUST_COUNCIL_FIELD,
        movement_type=inventory_models.COUNCIL_ON_ORDER_ADJUST,
        product_id=product_id,
        kernel_physical_delta=0,
        council_on_order_delta=delta,
        reason=reason,
        occurred_at=occurred_at,
    )


# --- Stage 2 inventory reads (§2.2.4) --------------------------------------------


def _optional_argument(event: Dict[str, Any], name: str) -> Any:
    """One optional top-level query argument, as the caller sent it."""
    arguments = event.get("arguments")
    return arguments.get(name) if isinstance(arguments, Mapping) else None


def _inventory_positions(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """What a campaign holds per product, with the derived quantities computed server-side.

    An explicit ``productIds`` list answers in the order the caller asked, and answers
    a product with no balance row at zero — the admin screen has to show the catalog
    product that nothing has been received for. Without a list, the products the
    campaign has inventory rows for come back in sort-key order.
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    product_ids = inventory_models.normalize_product_ids(_optional_argument(event, "productIds"))
    sections = inventory_models.campaign_product_sections(unit_campaign_id, product_ids or None)
    if product_ids:
        positions = [_position_payload(unit_campaign_id, pid, sections[pid]) for pid in product_ids]
    else:
        positions = [_position_payload(unit_campaign_id, pid, bucket) for pid, bucket in sections.items()]
    scope = f"{INVENTORY_POSITIONS_FIELD}#{unit_campaign_id}#{','.join(product_ids) if product_ids else 'ALL'}"
    return dict(paginate_page(positions, scope, _page_argument(event)))


def _movement_filters(event: Dict[str, Any]) -> Dict[str, Any]:
    """The validated ``inventoryMovements`` filter set, with the date range split open."""
    start_at, end_at = inventory_models.normalize_date_range(_optional_argument(event, "dateRange"))
    values: Dict[str, Any] = {"startAt": start_at, "endAt": end_at}
    for name in ("productId", "showAndSellId", "profileId"):
        raw = _optional_argument(event, name)
        values[name] = None if raw is None else inventory_models.normalize_inventory_id(raw, name)
    raw_type = _optional_argument(event, "movementType")
    values["movementType"] = None if raw_type is None else inventory_models.normalize_movement_type(raw_type)
    return values


def _inventory_movements(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One campaign's movement history, newest first, with §5.8 filters.

    Every filter is part of the cursor scope, so a cursor from a product-filtered page
    cannot walk an unfiltered history: the caller would receive rows they never asked
    for, and the page boundary would misreport what the filter selected (PAGE-01).
    The read returns rows in business-time order and this reverses them, because an
    audit screen opens at the most recent change (§5.1 ``newest first``).
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    filters = _movement_filters(event)
    rows = inventory_models.list_inventory_movements(
        unit_campaign_id,
        product_id=filters["productId"],
        movement_type=filters["movementType"],
        show_and_sell_id=filters["showAndSellId"],
        profile_id=filters["profileId"],
        start_at=filters["startAt"],
        end_at=filters["endAt"],
    )
    items = [_movement_payload(row) for row in reversed(rows)]
    token = "#".join("" if filters[name] is None else str(filters[name]) for name in _MOVEMENT_FILTER_ORDER)
    return dict(paginate_page(items, f"{INVENTORY_MOVEMENTS_FIELD}#{unit_campaign_id}#{token}", _page_argument(event)))


# --- Scout custody (§2.3) --------------------------------------------------------


def _custody_payload(custody: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a stored ``ScoutCustodyBalance`` row onto the SDL fields (§5.9).

    The projection carries no actor or account field: the same shape answers the
    admin board and the Scout's own read, and a participant-facing custody list that
    named which admin issued the stock would be a leak the §2.3.3 contract refuses
    (INV-Q-05-01).
    """
    return {
        "unitCampaignId": str(custody[inventory_models.UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        "productId": str(custody[inventory_models.PRODUCT_ID_ATTRIBUTE]),
        "profileId": str(custody[inventory_models.PROFILE_ID_ATTRIBUTE]),
        "campaignId": str(custody[inventory_models.CAMPAIGN_ID_ATTRIBUTE]),
        "withScoutQty": _number(custody.get(inventory_models.WITH_SCOUT_QTY, 0)),
        "version": _number(custody[inventory_models.VERSION_ATTRIBUTE]),
        "createdAt": str(custody[inventory_models.CREATED_AT_ATTRIBUTE]),
        "updatedAt": str(custody[inventory_models.UPDATED_AT_ATTRIBUTE]),
    }


def _custody_row_for_profile(custody_rows: List[Dict[str, Any]], profile_id: str) -> Optional[Dict[str, Any]]:
    """The one custody row of this product that belongs to ``profile_id``."""
    for row in custody_rows:
        if str(row[inventory_models.PROFILE_ID_ATTRIBUTE]) == profile_id:
            return row
    return None


def _issued_roster_identity(unit_campaign_id: str, campaign_id: str, profile_id: str) -> Dict[str, Any]:
    """The roster row an issue requires: this Scout, ACTIVE, and this Campaign.

    §2.3.1 makes the roster the eligibility gate, and the row is read consistently
    because the write that follows is decided by it. Three refusals, each naming
    what the caller has to fix:

    - no row — this Scout has never joined, so there is no identity to issue to
      (``NOT_FOUND``: there is nothing here to act on);
    - ``REMOVED`` — the Scout left the roster, and issuing more stock to a Scout who
      is no longer selling strands it (spec AC-47 keeps their existing custody
      intact; it does not invite more);
    - a different ``campaignId`` — the roster names one Scout Campaign per Scout, so
      a request naming another is not the same Scout (§2.3.1 "exact Campaign/Profile
      identity", CAMP-M-03's identity rule on the write side).
    """
    membership: Dict[str, Any] | None = unit_campaign_models.read_membership(unit_campaign_id, profile_id)
    if membership is None:
        raise AppError(ErrorCode.NOT_FOUND, "This Scout is not on this campaign's roster")
    if str(membership["status"]) != unit_campaign_models.MEMBERSHIP_STATUS_ACTIVE:
        raise AppError(ErrorCode.CONFLICT, "This Scout's roster entry is REMOVED; rejoin before stock is issued")
    if str(membership["campaignId"]) != campaign_id:
        raise AppError(ErrorCode.CONFLICT, "This Scout's roster entry belongs to a different Scout Campaign")
    return membership


def _require_unassigned_stock(
    balance: Optional[Mapping[str, Any]], allocations: List[Dict[str, Any]], quantity: int
) -> None:
    """Refuse an issue that would take stock an open Show & Sell already promises.

    CUST-01 lets a Kernel issue only *available unassigned* stock: the quantity a
    campaign holds that is neither reserved for We Owe nor still claimed by an OPEN
    allocation. Checking ``kernelPhysicalQty`` alone would let a Kernel hand a Scout
    the Kernels tomorrow's event is holding, and the event would arrive short with no
    row anywhere saying why.

    Like the adjustment floor in :func:`_require_balance_floor`, this pre-check buys
    the actionable verdict, not the race guard: the balance's version pin plus its
    ``kernelPhysicalQty >= quantity`` condition are what cancel the loser of a race
    for the last Kernel, and every allocation write bumps that same version (§3.2.3).
    """
    unassigned = inventory_models.unassigned_kernel_qty(balance, allocations)
    if quantity > unassigned:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"quantity exceeds the {unassigned} unassigned Kernels this campaign holds for that product",
        )


def _stage_custody_change(
    plan: Any,
    unit_campaign_id: str,
    product_id: str,
    profile_id: str,
    campaign_id: str,
    existing: Optional[Mapping[str, Any]],
    *,
    with_scout_delta: int,
    occurred_at: str,
) -> int:
    """Stage this request's custody write and report the version it produces.

    The same two shapes as the balance half (§8.4): a conditional ``Put`` when this
    Scout holds none of this product yet, and a version-guarded increment with the
    ``withScoutQty >= 0`` floor in its condition afterwards. ``campaignId`` is written
    only on the create path — it is part of the custody's identity (§5.9 "the Scout
    Campaign used for individual sales"), so a later issue to a re-joined Scout does
    not silently re-point stock the Scout already holds at a different Campaign.
    """
    if existing is None:
        item = inventory_models.build_scout_custody_balance_item(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            profile_id=profile_id,
            campaign_id=campaign_id,
            with_scout_qty=with_scout_delta,
            now_iso=occurred_at,
        )
        plan.add(*inventory_models.put_scout_custody_action(item))
        return 1
    current_version = _number(existing[inventory_models.VERSION_ATTRIBUTE])
    plan.add(
        *inventory_models.scout_custody_delta_action(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            profile_id=profile_id,
            existing=existing,
            expected_version=current_version,
            with_scout_delta=with_scout_delta,
            now_iso=occurred_at,
        )
    )
    return current_version + 1


def _custody_position_and_balance(unit_campaign_id: str, product_id: str, profile_id: str) -> Dict[str, Any]:
    """What one issue produced: the product's position and that Scout's custody."""
    custody = inventory_models.read_scout_custody(unit_campaign_id, product_id, profile_id)
    return {
        "inventoryPosition": _written_position(unit_campaign_id, product_id),
        "custodyBalance": _custody_payload(_loaded_or_internal(custody, "updated custody balance could not be loaded")),
    }


def _custody_identity_payload(unit_campaign_id: str, profile_id: str) -> Dict[str, Any]:
    """Every product one Scout holds in one campaign: positions plus custody balances.

    This is the recovery answer for a ``returnStockFromScout`` whose marker lost its
    payload back-fill (§8.9). It is derivable from the custody rows alone because a
    return never deletes a custody row — it drives ``withScoutQty`` to zero and leaves
    the version history — so the products a committed return touched are exactly the
    products still carrying a row for this Scout.
    """
    rows = inventory_models.campaign_custody_rows(unit_campaign_id, profile_id=profile_id)
    return {
        "inventoryPositions": [
            _position_payload(unit_campaign_id, str(row[inventory_models.PRODUCT_ID_ATTRIBUTE])) for row in rows
        ],
        "custodyBalances": [_custody_payload(row) for row in rows],
    }


def _write_custody_movements(
    plan: Any,
    unit_campaign_id: str,
    *,
    movement_type: str,
    profile_id: str,
    occurred_at: str,
    idempotency_key: str,
    caller_id: str,
    movements: List[tuple[str, int, int, int]],
) -> None:
    """Append one movement per product a custody write moved (§5.8).

    ``movements`` is ``(productId, kernelPhysicalDelta, withScoutDelta, balanceVersion)``
    in the request's own order, so the audit trail and the returned lists read the way
    the caller sent them. Two things the row must get right: the ``profileId``, because
    a custody movement that does not say whose trunk the stock went into cannot be
    traced to anything, and the ``inventoryVersion`` of the balance this same
    transaction wrote, because that is how an audit reader lines the movement up
    against the aggregate it produced.
    """
    for product_id, kernel_delta, scout_delta, balance_version in movements:
        plan.add(
            *inventory_models.put_inventory_movement_action(
                inventory_models.build_inventory_movement_item(
                    movement_id=str(inventory_models.new_inventory_movement_id()),
                    unit_campaign_id=unit_campaign_id,
                    product_id=product_id,
                    movement_type=movement_type,
                    actor_account_id=caller_id,
                    occurred_at=occurred_at,
                    idempotency_key=idempotency_key,
                    kernel_physical_delta=kernel_delta,
                    with_scout_delta=scout_delta,
                    profile_id=profile_id,
                    inventory_version=balance_version,
                )
            )
        )


# --- issueStockToScout (§2.3.1) --------------------------------------------------


def _issue_stock(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Move unassigned Kernel stock into one Scout's custody.

    Four rows, one transaction: the idempotency marker, the product's balance down,
    the Scout's custody up, and one ``SCOUT_ISSUE`` movement. That pairing is the
    whole point of CUST-01 — total unit-owned stock does not change, so a balance
    that moved without its custody row (or the reverse) is stock that left the
    campaign through a door nothing recorded. The result is both halves of the move:
    the product's position and the custody balance.

    Nothing here sells anything: no Order, no sale, no We Owe, no credit (AC-03).
    Issuing is a delivery of stock, and the money only ever follows a sale.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    campaign = _campaign_for_inventory_write(payload, caller_id)
    unit_campaign_id = str(campaign["unitCampaignId"])
    campaign_id = inventory_models.normalize_inventory_id(payload.get("campaignId"), "campaignId")
    profile_id = inventory_models.normalize_inventory_id(payload.get("profileId"), "profileId")
    product_id = inventory_models.normalize_inventory_id(payload.get("productId"), "productId")
    quantity = inventory_models.normalize_quantity(payload.get("quantity"), "quantity", minimum=1)
    occurred_at = inventory_models.normalize_moment(payload.get("occurredAt") or utc_now_iso(), "occurredAt")

    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()
    keys = _inventory_marker(
        caller_id=caller_id, operation=ISSUE_STOCK_FIELD, scope=unit_campaign_id, idempotency_key=key
    )
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        ISSUE_STOCK_FIELD,
        lambda _stored: _custody_position_and_balance(unit_campaign_id, product_id, profile_id),
    )
    if replayed is not None:
        return replayed

    _issued_roster_identity(unit_campaign_id, campaign_id, profile_id)
    sections = _position_sections(unit_campaign_id, product_id)
    balance = sections["balance"][0] if sections["balance"] else None
    custody = _custody_row_for_profile(sections["custody"], profile_id)
    if custody is not None and str(custody[inventory_models.CAMPAIGN_ID_ATTRIBUTE]) != campaign_id:
        raise AppError(ErrorCode.CONFLICT, "This Scout's custody of that product belongs to a different Scout Campaign")
    _require_unassigned_stock(balance, sections["allocations"], quantity)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=product_id)
    version = _stage_balance_change(
        plan,
        unit_campaign_id,
        product_id,
        balance,
        kernel_physical_delta=-quantity,
        council_on_order_delta=0,
        occurred_at=occurred_at,
    )
    _stage_custody_change(
        plan,
        unit_campaign_id,
        product_id,
        profile_id,
        campaign_id,
        custody,
        with_scout_delta=quantity,
        occurred_at=occurred_at,
    )
    _write_custody_movements(
        plan,
        unit_campaign_id,
        movement_type=inventory_models.SCOUT_ISSUE,
        profile_id=profile_id,
        occurred_at=occurred_at,
        idempotency_key=key,
        caller_id=caller_id,
        movements=[(product_id, -quantity, quantity, version)],
    )
    build_result = _once(lambda: _custody_position_and_balance(unit_campaign_id, product_id, profile_id))
    runner.execute(
        keys,
        plan,
        operation=ISSUE_STOCK_FIELD,
        fingerprint=fingerprint,
        result_id=product_id,
        load_result=lambda _stored: _custody_position_and_balance(unit_campaign_id, product_id, profile_id),
        result_payload=build_result,
    )
    log.info(
        "Stock issued to Scout",
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        profile_id=profile_id,
        quantity=quantity,
        balance_version=version,
        caller_id=caller_id,
    )
    return build_result()


# --- returnStockFromScout (§2.3.2) -----------------------------------------------


def _returned_custody(
    unit_campaign_id: str, campaign_id: str, profile_id: str, items: List[tuple[str, int]]
) -> List[Dict[str, Any]]:
    """Read and check every custody row a return touches, before any of it is staged.

    §2.3.2 refuses an over-return "before writing", and the whole batch shares one
    verdict: returning four of a product the Scout holds three of fails the batch, and
    the three of the other product is not partially returned (INV-M-05-02). So every
    row is read and checked here first; only a batch that survives comes back, and the
    caller stages it without reading again.

    The custody row, not the roster, carries the identity for a return. A Scout can be
    removed from the roster, or the whole campaign deactivated, and still be holding
    Kernels (AC-47 keeps that custody standing); refusing the return then would strand
    the stock with no path back, which is the opposite of CUST-06. So the checks are
    that the custody exists, and that the ``campaignId`` the caller named is the one
    the custody row itself records.
    """
    rows: List[Dict[str, Any]] = []
    for product_id, quantity in items:
        custody = inventory_models.read_scout_custody(unit_campaign_id, product_id, profile_id)
        if custody is None:
            raise AppError(ErrorCode.INVALID_INPUT, "That Scout holds none of that product to return")
        if str(custody[inventory_models.CAMPAIGN_ID_ATTRIBUTE]) != campaign_id:
            raise AppError(ErrorCode.CONFLICT, "That custody belongs to a different Scout Campaign")
        held = _number(custody.get(inventory_models.WITH_SCOUT_QTY, 0))
        if quantity > held:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                f"quantity exceeds the {held} Kernels that Scout holds of that product",
            )
        rows.append({"productId": product_id, "quantity": quantity, "custody": custody})
    return rows


def _returned_positions(unit_campaign_id: str, profile_id: str, planned: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The batch's answer: each returned product's position and custody, in request order."""
    positions: List[Dict[str, Any]] = []
    balances: List[Dict[str, Any]] = []
    for entry in planned:
        product_id = str(entry["productId"])
        positions.append(_written_position(unit_campaign_id, product_id))
        custody = inventory_models.read_scout_custody(unit_campaign_id, product_id, profile_id)
        balances.append(_custody_payload(_loaded_or_internal(custody, "returned custody balance could not be loaded")))
    return {"inventoryPositions": positions, "custodyBalances": balances}


def _return_stock(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Take a Scout's unsold custody back into Kernel stock, one atomic batch.

    The batch is what "one click" means operationally: a Kernel standing at a Scout's
    door with two of X and three of Y must not end up with the X returned and the Y
    lost because a second request failed. Every product's balance up, custody down, and
    ``SCOUT_RETURN`` movement ride the same ``TransactWriteItems`` as the marker, so
    INV-M-05-01's "both updated balances in one atomic result" and INV-M-05-02's
    whole-batch refusal are the same mechanism (§8.4).

    The 90-action budget is enforced by ``WritePlan`` while the plan is staged: the
    91st action raises before a single DynamoDB call is made, which is INV-M-05-03's
    "fails before writing", and the caller splits the return into batches that each
    fit. Counting it here as well would put the same budget in two places and let them
    drift.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    campaign = _campaign_for_inventory_write(payload, caller_id)
    unit_campaign_id = str(campaign["unitCampaignId"])
    campaign_id = inventory_models.normalize_inventory_id(payload.get("campaignId"), "campaignId")
    profile_id = inventory_models.normalize_inventory_id(payload.get("profileId"), "profileId")
    items = inventory_models.normalize_return_items(payload.get("items"))
    occurred_at = inventory_models.normalize_moment(payload.get("occurredAt") or utc_now_iso(), "occurredAt")

    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()
    keys = _inventory_marker(
        caller_id=caller_id, operation=RETURN_STOCK_FIELD, scope=unit_campaign_id, idempotency_key=key
    )
    replayed = _replay(
        runner,
        keys,
        fingerprint,
        RETURN_STOCK_FIELD,
        lambda stored: _custody_identity_payload(unit_campaign_id, str(stored)),
    )
    if replayed is not None:
        return replayed

    membership = unit_campaign_models.read_membership(unit_campaign_id, profile_id)
    if membership is not None and str(membership["campaignId"]) != campaign_id:
        raise AppError(ErrorCode.CONFLICT, "This Scout's roster entry belongs to a different Scout Campaign")
    planned = _returned_custody(unit_campaign_id, campaign_id, profile_id, items)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=profile_id)
    movements: List[tuple[str, int, int, int]] = []
    for entry in planned:
        product_id = str(entry["productId"])
        quantity = int(entry["quantity"])
        existing = inventory_models.read_inventory_balance(unit_campaign_id, product_id)
        version = _stage_balance_change(
            plan,
            unit_campaign_id,
            product_id,
            existing,
            kernel_physical_delta=quantity,
            council_on_order_delta=0,
            occurred_at=occurred_at,
        )
        _stage_custody_change(
            plan,
            unit_campaign_id,
            product_id,
            profile_id,
            campaign_id,
            entry["custody"],
            with_scout_delta=-quantity,
            occurred_at=occurred_at,
        )
        movements.append((product_id, quantity, -quantity, version))
    _write_custody_movements(
        plan,
        unit_campaign_id,
        movement_type=inventory_models.SCOUT_RETURN,
        profile_id=profile_id,
        occurred_at=occurred_at,
        idempotency_key=key,
        caller_id=caller_id,
        movements=movements,
    )
    build_result = _once(lambda: _returned_positions(unit_campaign_id, profile_id, planned))
    runner.execute(
        keys,
        plan,
        operation=RETURN_STOCK_FIELD,
        fingerprint=fingerprint,
        result_id=profile_id,
        load_result=lambda stored: _custody_identity_payload(unit_campaign_id, str(stored)),
        result_payload=build_result,
    )
    log.info(
        "Scout custody returned",
        unit_campaign_id=unit_campaign_id,
        profile_id=profile_id,
        products=len(planned),
        actions=plan.action_count,
        caller_id=caller_id,
    )
    return build_result()


# --- scoutCustodyBalances / myScoutCustody (§2.3.3) ------------------------------


def _scout_custody_balances(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """What a campaign has out with its Scouts: per Scout, per product, and in total.

    CUST-02 requires both views, and the aggregate is computed over the filtered set
    rather than the current page: a board paging through forty custody rows still has
    to show the one number the Kernel acts on, and a total that changed with the page
    would be a second source of truth (RPT-09 keeps it separate from every stock-need
    calculation).
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    raw_profile = _optional_argument(event, "profileId")
    raw_product = _optional_argument(event, "productId")
    profile_id = None if raw_profile is None else inventory_models.normalize_inventory_id(raw_profile, "profileId")
    product_id = None if raw_product is None else inventory_models.normalize_inventory_id(raw_product, "productId")
    rows = inventory_models.campaign_custody_rows(unit_campaign_id, profile_id=profile_id, product_id=product_id)
    page = dict(
        paginate_page(
            [_custody_payload(row) for row in rows],
            f"{SCOUT_CUSTODY_FIELD}#{unit_campaign_id}#{profile_id or 'ALL'}#{product_id or 'ALL'}",
            _page_argument(event),
        )
    )
    page["totalWithScoutQty"] = sum(_number(row.get(inventory_models.WITH_SCOUT_QTY, 0)) for row in rows)
    return page


def _my_scout_custody(event: Dict[str, Any], caller_id: str) -> List[Dict[str, Any]]:
    """One Scout's own custody in one campaign, for the people who may see that Scout.

    Two doors, and only one of them has to open (§5.1): a Profile READ/Owner/WRITE
    holder acting for their own Scout, or a Unit Admin of the campaign addressed. The
    admin door is checked first because it is the cheaper and more common one, and a
    failed admin check is not the answer on its own — Riley holds READ on Avery's
    profile and needs the read to work without any Unit grant at all (INV-Q-05-01).

    What makes this participant-safe is the scope, not a projection: the rows come
    from one campaign partition and are filtered to one ``profileId``, so no other
    Scout's row can appear, and the payload carries no actor, reason, or movement
    field to begin with. Riley asking for Blake's custody is refused by the profile
    check; a revoked share stops working the day the share row is deleted
    (INV-Q-05's revoked-access case).
    """
    profile_id = inventory_models.normalize_inventory_id(_query_argument(event, "profileId"), "profileId")
    campaign: Dict[str, Any] = dict(
        unit_campaign_models.load_unit_campaign_or_not_found(_query_argument(event, "unitCampaignId"))
    )
    try:
        unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))
    except AppError:
        require_profile_access(caller_id, profile_id, "READ")
    rows = inventory_models.campaign_custody_rows(str(campaign["unitCampaignId"]), profile_id=profile_id)
    return [_custody_payload(row) for row in rows]


# --- Individual Order fulfillment (§2.4) ------------------------------------------

# All three §2.4 surfaces authorize with the same read and the same rule: the Order's
# own immutable ``unitId`` (§5.19, API-FIX-05) decides whose admin may act, and a Unit id
# in the request is never consulted (AUTH-U). That is also why fulfillment is a Unit
# surface at all: its stock source is Unit stock, and an Order with no originating Unit
# has no Unit Admin to ask and no balance to draw from.


def _order_fulfillment_marker(*, caller_id: str, operation: str, order_id: str, idempotency_key: str) -> Any:
    """Resolve this request's marker address on the order_fulfillments table.

    The marker lives on the table whose rows the mutation appends (§8.9), so one Order's
    fulfillment history and the record of the request that wrote it sit under one
    partition prefix. The resource scope is the Order, which is what every §2.4 mutation
    addresses — not the Unit Campaign, because an Order's originating scope is fixed at
    sale time while the campaign's current link is not.
    """
    return marker_keys(
        table_key="order_fulfillments",
        table_name=tables.order_fulfillments.table_name,
        actor_id=caller_id,
        operation=operation,
        scope=order_id,
        idempotency_key=idempotency_key,
    )


def _reload_order(key: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """The stored Order row one key pair addresses, or ``None``.

    The ``orders`` table is hash-keyed on ``campaignId``, and an Order id carries it —
    ``ORDER#<bare campaign id>#<suffix>``, minted and parsed by
    :mod:`src.utils.order_keys` — so the pair resolves to one strongly consistent
    ``GetItem`` on the base table. No index is involved, and that matters because an
    authorization decision follows this read: an eventually consistent GSI can still
    project a stale row, which is not a proof of anything (§8.4).

    Both callers hand over a pair they resolved rather than an id: an id that embeds no
    campaign is a malformed request, and answering that here would hide the difference
    between "you sent something this path cannot address" and "there is no such Order".
    """
    response = tables.orders.get_item(
        Key={"campaignId": key["campaignId"], "orderId": key["orderId"]},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return dict(item) if item else None


def _order_key_or_refuse(order_id: str) -> Dict[str, str]:
    """The base-table key an Order id addresses, or the refusal when it addresses none.

    A legacy ``ORDER#<uuid>`` row embeds no campaign, and guessing one would let a
    fulfillment write against whichever row the guess happened to hit.
    """
    key = order_fulfillment_models.order_row_key(order_id)
    if key is None:
        raise AppError(ErrorCode.INVALID_INPUT, "orderId must carry its campaign: ORDER#<campaignId>#<suffix>")
    return {"campaignId": str(key["campaignId"]), "orderId": str(key["orderId"])}


def _order_for_fulfillment(order_id: str, caller_id: str) -> Dict[str, Any]:
    """The Order a §2.4 mutation acts on, with admin of its originating Unit required.

    Three refusals, each the answer the caller can act on:

    - an id that names no campaign is ``INVALID_INPUT``: the request itself is malformed,
      and picking a campaign would let the write land on whichever row the pick hit;
    - no row is ``NOT_FOUND``: there is nothing here to fulfill or reverse;
    - no ``unitId`` is ``FORBIDDEN``, not ``NOT_FOUND``. The Order exists and the caller
      may even own it, but §2.4 is a Unit surface and an independent sale has no Unit
      scope to administer — and API-FIX-05 keeps that scope immutable precisely so a
      later roster join cannot make this answer change.

    ``require_unit_admin`` then answers any caller without a grant on that Unit, so
    tenancy never comes from the request (AUTH-U).
    """
    order = _reload_order(_order_key_or_refuse(order_id))
    if order is None:
        raise AppError(ErrorCode.NOT_FOUND, "Order not found")
    unit_id = order.get(order_fulfillment_models.UNIT_ID_ATTRIBUTE)
    if not unit_id:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "this Order has no originating Unit, so no Unit Admin may fulfill or reverse its lines",
        )
    unit_auth.require_unit_admin(caller_id, str(unit_id))
    return order


def _line_item_payload(line: Mapping[str, Any]) -> Dict[str, Any]:
    """One stored Order line on the SDL ``LineItem`` shape, §5.19's additions included.

    ``fulfilledQuantity`` absent reads as 0 and ``lineItemId`` absent reads as null, which
    is what §10.2 requires of a pre-Wave-3 row: every line answers with the same shape,
    and a legacy Order can be fulfilled without anything being backfilled first.
    """
    return {
        "productId": line.get("productId"),
        "productName": line.get("productName"),
        "quantity": _number(line.get("quantity", 0)),
        "pricePerUnit": float(line.get("pricePerUnit", 0)),
        "subtotal": float(line.get("subtotal", 0)),
        "lineItemId": line.get("lineItemId"),
        "fulfilledQuantity": _number(line.get("fulfilledQuantity", 0)),
    }


def _order_payload(order: Mapping[str, Any]) -> Dict[str, Any]:
    """A stored Order row on the SDL ``Order`` type, as a fulfillment result returns it.

    The row's own attributes with the storage keys dropped: an Order row is written by
    the ``createOrder``/``publicCreateOrder`` pipelines, so this handler returns what
    those owners stored rather than a second copy of the shape that could drift from
    them. ``fulfillments`` is deliberately absent — that field has its own resolver,
    which answers the participant-safe projection to every caller (§10.2) — and
    ``fulfillmentVersion`` absent reads as 0, the version every unfulfilled Order is at.
    """
    return {
        "orderId": order.get(order_fulfillment_models.ORDER_ID_ATTRIBUTE),
        "profileId": order.get(order_fulfillment_models.PROFILE_ID_ATTRIBUTE),
        "campaignId": order.get(order_fulfillment_models.CAMPAIGN_ID_ATTRIBUTE),
        "customerName": order.get("customerName"),
        "customerPhone": order.get("customerPhone"),
        "customerAddress": order.get("customerAddress"),
        "orderDate": order.get("orderDate"),
        "paymentMethod": order.get("paymentMethod"),
        "lineItems": [_line_item_payload(line) for line in order_fulfillment_models.order_line_items(order)],
        "totalAmount": float(order.get("totalAmount", 0)),
        "notes": order.get("notes"),
        "status": order.get("status"),
        "confirmedBy": order.get("confirmedBy"),
        "confirmedAt": order.get("confirmedAt"),
        "createdAt": order.get("createdAt"),
        "updatedAt": order.get("updatedAt"),
        "unitId": order.get(order_fulfillment_models.UNIT_ID_ATTRIBUTE),
        "unitCampaignId": order.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE),
        "fulfillmentVersion": _number(order.get(order_fulfillment_models.FULFILLMENT_VERSION_ATTRIBUTE, 0)),
    }


def _fulfillment_answer(order: Mapping[str, Any], record_field: str) -> Callable[[str], Dict[str, Any]]:
    """Build the answer one §2.4 mutation produced, from the rows it committed.

    One builder serves the fresh write and the replay of a completed request, and both
    read the stored rows instead of the values the request carried: the answer has to be
    what the transaction committed, and a replay that re-derived it from the caller's own
    payload would report an intent that a condition may have refused. ``record_field`` is
    ``fulfillment`` or ``reversal`` — the SDL names the two payloads apart, and which
    word the record sits under is the only difference between the answers.

    The builder is handed the row authorization already read, and re-reads the Order by
    that row's own stored key pair: the id the caller sent is the id the row carries
    (``orders`` is got by that exact pair), so no second parse of caller input sits
    between the check and the answer.

    ``inventoryPosition`` is present exactly when Kernel stock moved. A Scout-custody or
    external-Council change has no Kernel position to report, and answering with a
    position that did not change would read as though it had.
    """
    stored_order_id = str(order[order_fulfillment_models.ORDER_ID_ATTRIBUTE])
    key = {"campaignId": str(order[order_fulfillment_models.CAMPAIGN_ID_ATTRIBUTE]), "orderId": stored_order_id}

    def answer(fulfillment_id: str) -> Dict[str, Any]:
        row = order_fulfillment_models.find_fulfillment(stored_order_id, fulfillment_id)
        row = _loaded_or_internal(row, "the fulfillment record this request wrote could not be loaded")
        order_row = _loaded_or_internal(_reload_order(key), "the fulfilled Order could not be loaded")
        payload: Dict[str, Any] = {
            "order": _order_payload(order_row),
            record_field: order_fulfillment_models.fulfillment_payload(row),
        }
        if str(row[order_fulfillment_models.SOURCE_ATTRIBUTE]) == order_fulfillment_models.SOURCE_KERNEL_STOCK:
            payload["inventoryPosition"] = _written_position(
                str(row[order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE]),
                str(row[order_fulfillment_models.PRODUCT_ID_ATTRIBUTE]),
            )
        return payload

    return answer


def _require_fulfillment_scope(row: Mapping[str, Any]) -> str:
    """The Unit Campaign whose stock a §2.4 mutation moves.

    §5.19 captures the Order's originating scope immutably at sale time, so the balance
    or custody the stock comes from is the one the Order names — never the one the caller
    happens to be looking at now, which a later join could have changed. Called only for
    a source that moves Unit stock: an external-Council change moves nothing and has no
    scope to resolve, so requiring one there would refuse a request that touches no row.
    """
    scope = row.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE)
    if not scope:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "this Order has no originating Unit Campaign, so Unit stock cannot be consumed for it",
        )
    return str(scope)


def _stage_fulfillment_movement(
    plan: Any,
    *,
    unit_campaign_id: str,
    product_id: str,
    movement_id: str,
    movement_type: str,
    caller_id: str,
    occurred_at: str,
    idempotency_key: str,
    order_id: str,
    fulfillment_id: str,
    kernel_physical_delta: int,
    with_scout_delta: int,
    profile_id: Optional[str],
    inventory_version: Optional[int],
) -> None:
    """Append the §5.8 movement one fulfillment or reversal caused.

    The row carries both links — ``orderId`` and ``fulfillmentId`` — because that is how
    an audit reader answers "which Kernels did this record move, against which record"
    without a join; the builder enforces the link rule per movement type, so a movement
    that lost a link cannot be written at all. ``profileId`` rides only the custody half:
    a custody movement has to say whose trunk the stock came out of, and Kernel stock has
    no Scout to name.

    ``inventoryVersion`` is the balance version this transaction produced, and it is
    ``None`` for a custody-only movement: no aggregate balance moved, and inventing a
    version for a row that did not change would put a number in the audit trail that
    nothing can check it against.
    """
    plan.add(
        *inventory_models.put_inventory_movement_action(
            inventory_models.build_inventory_movement_item(
                movement_id=movement_id,
                unit_campaign_id=unit_campaign_id,
                product_id=product_id,
                movement_type=movement_type,
                actor_account_id=caller_id,
                occurred_at=occurred_at,
                idempotency_key=idempotency_key,
                kernel_physical_delta=kernel_physical_delta,
                with_scout_delta=with_scout_delta,
                profile_id=profile_id,
                order_id=order_id,
                fulfillment_id=fulfillment_id,
                inventory_version=inventory_version,
            )
        )
    )


# --- fulfillIndividualOrderLine (§2.4.3) ------------------------------------------


def _fulfill_line(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Fill part or all of one individual Order line from a Kernel-chosen source.

    The whole change is one ``TransactWriteItems``: the idempotency marker, the Order row
    (its line list with ``fulfilledQuantity`` moved, ``fulfillmentVersion`` incremented
    from the value the caller named, ``updatedAt``), and the append-only ``FULFILL``
    record — plus the balance delta and its ``INDIVIDUAL_FULFILL`` movement, but only for
    a ``KERNEL_STOCK`` source. That pairing is the point of AC-03/AC-05: stock that left
    a balance without a movement row, or a record that claims stock nothing moved, is a
    count no later report can reconcile (§8.5).

    The source is the Kernel's choice and it is honest by construction. ``KERNEL_STOCK``
    may only take *unassigned* stock, the same ceiling ``issueStockToScout`` applies
    (CUST-01): a Kernel standing at a door is not entitled to the Kernels tomorrow's Show
    & Sell is holding. ``EXTERNAL_COUNCIL`` records that the demand was met from outside
    the Unit's stock and writes no inventory row at all — including no balance row for a
    product the campaign has never received — while still incrementing the Order's
    ``fulfillmentVersion``, because §5.19 requires a version move for every fulfillment
    whether or not any inventory version moved. ``SCOUT_CUSTODY`` is refused here: that
    stock is consumed by the sale itself (§2.4.2), so it is not a choice the fulfillment
    screen gets to make twice.

    The version guard is what makes two Kernels filling one line from two screens safe.
    The pre-read of the line's unfulfilled quantity answers an impossible request with
    ``INVALID_INPUT`` the caller can act on; a request that was possible when it was read
    and is not now loses its condition and gets ``CONFLICT``, and nothing is written
    either way (VER-01).
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    order_id = _resource_id(payload, "orderId")
    line_item_id = _resource_id(payload, "lineItemId")
    quantity = inventory_models.normalize_quantity(payload.get("quantity"), "quantity", minimum=1)
    source = order_fulfillment_models.normalize_fulfillment_source(payload.get("source"))
    expected_version = _positive_int(payload, "expectedFulfillmentVersion", minimum=0)
    order = _order_for_fulfillment(order_id, caller_id)
    if source == order_fulfillment_models.SOURCE_SCOUT_CUSTODY:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "SCOUT_CUSTODY is consumed by the sale itself; a fulfillment takes KERNEL_STOCK or EXTERNAL_COUNCIL",
        )

    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()
    keys = _order_fulfillment_marker(
        caller_id=caller_id, operation=FULFILL_LINE_FIELD, order_id=order_id, idempotency_key=key
    )
    load_answer = _fulfillment_answer(order, "fulfillment")
    replayed = _replay(runner, keys, fingerprint, FULFILL_LINE_FIELD, load_answer)
    if replayed is not None:
        return replayed

    violation = order_fulfillment_models.line_quantity_violations(order, line_item_id, quantity)
    if violation is not None:
        raise AppError(ErrorCode.INVALID_INPUT, violation)
    line = order_fulfillment_models.find_order_line(order, line_item_id)
    product_id = line.get(order_fulfillment_models.PRODUCT_ID_ATTRIBUTE)
    if not product_id:
        raise AppError(ErrorCode.INVALID_INPUT, "that line item carries no productId to fulfill")
    product_id = str(product_id)
    moves_kernel_stock = source == order_fulfillment_models.SOURCE_KERNEL_STOCK
    unit_campaign_id = _require_fulfillment_scope(order) if moves_kernel_stock else ""

    balance: Optional[Dict[str, Any]] = None
    if moves_kernel_stock:
        sections = _position_sections(unit_campaign_id, product_id)
        balance = sections["balance"][0] if sections["balance"] else None
        _require_unassigned_stock(balance, sections["allocations"], quantity)

    fulfillment_id = order_fulfillment_models.new_fulfillment_id()
    movement_id = str(inventory_models.new_inventory_movement_id()) if moves_kernel_stock else None
    now_iso = utc_now_iso()
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=fulfillment_id)
    plan.add(
        *order_fulfillment_models.order_fulfillment_update_action(
            order=order,
            line_items=order_fulfillment_models.apply_line_fulfillment(order, line_item_id, quantity),
            expected_version=expected_version,
            occurred_at=now_iso,
        )
    )
    plan.add(
        *order_fulfillment_models.put_fulfillment_action(
            order_fulfillment_models.build_fulfillment_item(
                fulfillment_id=fulfillment_id,
                order_id=order_id,
                campaign_id=str(order[order_fulfillment_models.CAMPAIGN_ID_ATTRIBUTE]),
                profile_id=str(order[order_fulfillment_models.PROFILE_ID_ATTRIBUTE]),
                unit_id=order.get(order_fulfillment_models.UNIT_ID_ATTRIBUTE),
                unit_campaign_id=order.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE),
                line_item_id=line_item_id,
                product_id=product_id,
                record_type=order_fulfillment_models.RECORD_TYPE_FULFILL,
                quantity=quantity,
                source=source,
                actor_account_id=caller_id,
                created_at=now_iso,
                inventory_movement_id=movement_id,
            )
        )
    )
    if moves_kernel_stock:
        version = _stage_balance_change(
            plan,
            unit_campaign_id,
            product_id,
            balance,
            kernel_physical_delta=-quantity,
            council_on_order_delta=0,
            occurred_at=now_iso,
        )
        _stage_fulfillment_movement(
            plan,
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            movement_id=str(movement_id),
            movement_type=inventory_models.INDIVIDUAL_FULFILL,
            caller_id=caller_id,
            occurred_at=now_iso,
            idempotency_key=key,
            order_id=order_id,
            fulfillment_id=fulfillment_id,
            kernel_physical_delta=-quantity,
            with_scout_delta=0,
            profile_id=None,
            inventory_version=version,
        )

    build_result = _once(lambda: load_answer(fulfillment_id))
    runner.execute(
        keys,
        plan,
        operation=FULFILL_LINE_FIELD,
        fingerprint=fingerprint,
        result_id=fulfillment_id,
        load_result=load_answer,
        result_payload=build_result,
    )
    log.info(
        "Individual Order line fulfilled",
        order_id=order_id,
        line_item_id=line_item_id,
        product_id=product_id,
        quantity=quantity,
        source=source,
        fulfillment_id=fulfillment_id,
        caller_id=caller_id,
    )
    return build_result()


# --- reverseIndividualOrderFulfillment (§2.4.4) ------------------------------------


def _stage_reversal_stock_effect(
    plan: Any,
    *,
    source: str,
    original: Mapping[str, Any],
    quantity: int,
    product_id: str,
    profile_id: str,
    campaign_id: str,
    movement_id: Optional[str],
    caller_id: str,
    occurred_at: str,
    idempotency_key: str,
    order_id: str,
    fulfillment_id: str,
) -> None:
    """Stage the stock half of a reversal: back to exactly where it came from.

    The source on the record being undone is the whole decision, and it is why this is
    one helper rather than a branch in the caller: AC-06 fails if a reversal restores a
    balance the fulfillment never drew from. ``KERNEL_STOCK`` goes back to the campaign
    balance with its version guard, ``SCOUT_CUSTODY`` goes back to that Scout's custody
    row and names the Profile it returned to, and ``EXTERNAL_COUNCIL`` writes no
    inventory row at all — nothing Unit-owned moved for it, so a balance row here would
    invent a stock history the fulfillment never had.

    ``inventoryVersion`` rides only the Kernel half. A custody movement has no aggregate
    version to point at, and a number nothing can check it against does not belong in an
    audit trail.
    """
    if source not in order_fulfillment_models.SOURCE_MOVES_STOCK:
        return
    unit_campaign_id = _require_fulfillment_scope(original)
    if source == order_fulfillment_models.SOURCE_KERNEL_STOCK:
        balance = inventory_models.read_inventory_balance(unit_campaign_id, product_id)
        version = _stage_balance_change(
            plan,
            unit_campaign_id,
            product_id,
            balance,
            kernel_physical_delta=quantity,
            council_on_order_delta=0,
            occurred_at=occurred_at,
        )
        _stage_fulfillment_movement(
            plan,
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            movement_id=str(movement_id),
            movement_type=inventory_models.REVERSAL,
            caller_id=caller_id,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            order_id=order_id,
            fulfillment_id=fulfillment_id,
            kernel_physical_delta=quantity,
            with_scout_delta=0,
            profile_id=None,
            inventory_version=version,
        )
        return
    custody = inventory_models.read_scout_custody(unit_campaign_id, product_id, profile_id)
    _stage_custody_change(
        plan,
        unit_campaign_id,
        product_id,
        profile_id,
        campaign_id,
        custody,
        with_scout_delta=quantity,
        occurred_at=occurred_at,
    )
    _stage_fulfillment_movement(
        plan,
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        movement_id=str(movement_id),
        movement_type=inventory_models.REVERSAL,
        caller_id=caller_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        order_id=order_id,
        fulfillment_id=fulfillment_id,
        kernel_physical_delta=0,
        with_scout_delta=quantity,
        profile_id=profile_id,
        inventory_version=None,
    )


def _reverse_fulfillment(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Undo one fulfillment, restoring only the source that fulfillment took.

    A reversal is a new append-only record, never an edit: §5.19 makes the fulfillment
    history immutable and lets the ``REVERSAL`` row speak the correction, linked to what
    it undoes. The line's ``fulfilledQuantity`` goes back down, the Order's
    ``fulfillmentVersion`` moves again, and the stock effect is exactly the original
    record's source — Kernel stock back into the balance, Scout custody back into that
    Scout's row, external Council back into nothing, because nothing Unit-owned ever
    moved for it (AC-06). A balance or custody row is written only for a source that
    moved that row, so a reversal cannot create a stock history that the fulfillment did
    not have.

    "At most one reversal per fulfillment" is a key fact here, not a check. The reversal's
    sort key is ``REVERSAL#<reversalOfFulfillmentId>`` — derived from the id it reverses —
    so the second attempt at reversing one fulfillment collides with the first row's
    ``attribute_not_exists`` condition and the whole transaction cancels with
    ``CONFLICT``. Reading for an existing reversal and then deciding could not say that:
    two readers would both see none. The lookup below is scoped to the Order's own
    partition, so an id from another Order is ``NOT_FOUND`` rather than a reversal of
    someone else's record (the wrong-parent case).

    ``apply_line_fulfillment`` is both the arithmetic and the guard for the demand half:
    a line re-written since the fulfillment may no longer carry that much fulfilled
    stock, and a row that no longer permits the reversal moved underneath this request,
    which is ``CONFLICT`` (§5.19).
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    order_id = _resource_id(payload, "orderId")
    fulfillment_id = _resource_id(payload, "fulfillmentId")
    expected_version = _positive_int(payload, "expectedFulfillmentVersion", minimum=0)
    order = _order_for_fulfillment(order_id, caller_id)

    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    runner = IdempotentMutationRunner()
    keys = _order_fulfillment_marker(
        caller_id=caller_id, operation=REVERSE_FULFILLMENT_FIELD, order_id=order_id, idempotency_key=key
    )
    load_answer = _fulfillment_answer(order, "reversal")
    replayed = _replay(runner, keys, fingerprint, REVERSE_FULFILLMENT_FIELD, load_answer)
    if replayed is not None:
        return replayed

    original = order_fulfillment_models.find_fulfillment(order_id, fulfillment_id)
    if original is None:
        raise AppError(ErrorCode.NOT_FOUND, "this Order has no fulfillment record with that fulfillmentId")
    if str(original[order_fulfillment_models.RECORD_TYPE_ATTRIBUTE]) != order_fulfillment_models.RECORD_TYPE_FULFILL:
        raise AppError(ErrorCode.INVALID_INPUT, "a REVERSAL record cannot itself be reversed")
    source = str(original[order_fulfillment_models.SOURCE_ATTRIBUTE])
    quantity = _number(original[order_fulfillment_models.QUANTITY_ATTRIBUTE])
    line_item_id = str(original[order_fulfillment_models.LINE_ITEM_ID_ATTRIBUTE])
    product_id = str(original[order_fulfillment_models.PRODUCT_ID_ATTRIBUTE])
    profile_id = str(original[order_fulfillment_models.PROFILE_ID_ATTRIBUTE])
    campaign_id = str(original[order_fulfillment_models.CAMPAIGN_ID_ATTRIBUTE])
    line_items = order_fulfillment_models.apply_line_fulfillment(order, line_item_id, -quantity)

    moves_stock = source in order_fulfillment_models.SOURCE_MOVES_STOCK
    reversal_id = order_fulfillment_models.new_fulfillment_id()
    movement_id = str(inventory_models.new_inventory_movement_id()) if moves_stock else None
    now_iso = utc_now_iso()
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=reversal_id)
    plan.add(
        *order_fulfillment_models.order_fulfillment_update_action(
            order=order,
            line_items=line_items,
            expected_version=expected_version,
            occurred_at=now_iso,
        )
    )
    plan.add(
        *order_fulfillment_models.put_fulfillment_action(
            order_fulfillment_models.build_fulfillment_item(
                fulfillment_id=reversal_id,
                order_id=order_id,
                campaign_id=campaign_id,
                profile_id=profile_id,
                unit_id=original.get(order_fulfillment_models.UNIT_ID_ATTRIBUTE),
                unit_campaign_id=original.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE),
                line_item_id=line_item_id,
                product_id=product_id,
                record_type=order_fulfillment_models.RECORD_TYPE_REVERSAL,
                quantity=quantity,
                source=source,
                actor_account_id=caller_id,
                created_at=now_iso,
                inventory_movement_id=movement_id,
                reversal_of_fulfillment_id=fulfillment_id,
            )
        )
    )
    _stage_reversal_stock_effect(
        plan,
        source=source,
        original=original,
        quantity=quantity,
        product_id=product_id,
        profile_id=profile_id,
        campaign_id=campaign_id,
        movement_id=movement_id,
        caller_id=caller_id,
        occurred_at=now_iso,
        idempotency_key=key,
        order_id=order_id,
        fulfillment_id=fulfillment_id,
    )

    build_result = _once(lambda: load_answer(reversal_id))
    runner.execute(
        keys,
        plan,
        operation=REVERSE_FULFILLMENT_FIELD,
        fingerprint=fingerprint,
        result_id=reversal_id,
        load_result=load_answer,
        result_payload=build_result,
    )
    log.info(
        "Individual Order fulfillment reversed",
        order_id=order_id,
        fulfillment_id=fulfillment_id,
        reversal_id=reversal_id,
        product_id=product_id,
        quantity=quantity,
        source=source,
        caller_id=caller_id,
    )
    return build_result()


# --- orderFulfillments (§2.4.5) ----------------------------------------------------


def _order_fulfillments(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One Order's whole fulfillment and reversal audit, oldest first.

    The full administrative projection — ``actorAccountId`` and ``inventoryMovementId``
    included — is the point of this query, and it is why the query is Unit-Admin-only
    while ``Order.fulfillments`` answers every caller from the participant-safe
    projection (§10.2). The two answers are built apart on purpose: the only difference
    between them is the audit fields, so the separation is one denylist in
    :mod:`src.utils.order_fulfillment_models` that both projections share, and a future
    audit column cannot leak from the participant side by being left out of a
    hand-written allow-list.

    Authorization is the read the mutations use: the Order's immutable ``unitId`` decides
    whose admin may ask, so an admin of one Unit cannot pull another Unit's audit trail
    by naming an Order id from it (AUTH-U).

    Ordered by ``createdAt`` rather than by the partition's sort key. Fulfillment keys are
    ``FULFILLMENT#<createdAt>#<fulfillmentId>`` while reversals carry the deterministic
    ``REVERSAL#<reversalOfFulfillmentId>``, which would sort every reversal after every
    fulfillment and say nothing about when each one happened; an audit screen reads what
    occurred in the order it occurred, and those two spellings are storage detail. The
    cursor's scope is the Order, so a page of one Order's history cannot walk another's
    (PAGE-01).
    """
    order_id = _query_argument(event, "orderId")
    order = _order_for_fulfillment(order_id, caller_id)
    stored_order_id = str(order[order_fulfillment_models.ORDER_ID_ATTRIBUTE])
    rows = order_fulfillment_models.fulfillment_rows(stored_order_id)
    rows.sort(
        key=lambda row: (
            str(row.get(order_fulfillment_models.CREATED_AT_ATTRIBUTE, "")),
            str(row.get(order_fulfillment_models.FULFILLMENT_ID_ATTRIBUTE, "")),
        )
    )
    items = [order_fulfillment_models.fulfillment_payload(row) for row in rows]
    return dict(paginate_page(items, f"{ORDER_FULFILLMENTS_FIELD}#{stored_order_id}", _page_argument(event)))


# --- unitScoutCampaignOrders (§2.4.1, §2.6.3) -------------------------------------

#: The two Order-row attributes the fulfillment projection names that
#: :mod:`src.utils.order_fulfillment_models` has no constant for, because its own
#: arithmetic never reads them: the customer the Scout wrote the Order for, and the
#: product name as the Order recorded it.
ORDER_CUSTOMER_NAME_ATTRIBUTE = "customerName"
ORDER_PRODUCT_NAME_ATTRIBUTE = "productName"
#: The legacy Order row's own timestamps, either of which answers `orderDate`.
ORDER_DATE_ATTRIBUTE = "orderDate"
ORDER_CREATED_AT_ATTRIBUTE = "createdAt"


def _order_quantity(line: Mapping[str, Any], attribute: str) -> int:
    """One line's quantity attribute as an integer, with the pre-Wave-3 absence read as 0."""
    return int(line.get(attribute) or 0)


def _order_sort_instant(value: str) -> datetime:
    """The instant an Order's business moment names, as the list's sort key (§10.4).

    ``orderDate`` is whatever the caller supplied and the Order writers store it
    verbatim, so one instant can arrive as ``…Z`` and another as ``…+00:00``, and two
    Orders taken minutes apart can arrive with different offsets. Compared as text the
    offset decides the order, so a page boundary falls in the wrong place and the newest
    Order can land on page two. :func:`src.utils.inventory_models.normalize_moment`
    documents this hazard for the timestamps this service writes itself; these rows are
    the legacy ones, written before that rule existed, so the parse happens here instead.
    An instant that cannot be parsed sorts as the oldest thing in the list, which keeps it
    reachable at the end rather than parked in the middle of page one.
    """
    parsed = unit_models.parse_timestamp(value)
    return parsed if parsed is not None else datetime.min.replace(tzinfo=timezone.utc)


def _unit_order_line_payload(line: Mapping[str, Any]) -> Dict[str, Any]:
    """One Order line in the fulfillment projection: identity, product, and both quantities.

    ``lineItemId`` is passed through as it is stored, so a line written before Wave 3
    answers with none. That is the answer the screen needs: §5.19 lets a fulfillment name
    a line only by its stable id, so a line without one cannot be fulfilled and the
    control is withheld rather than guessed at from the line's position.
    """
    return {
        "lineItemId": line.get(order_fulfillment_models.LINE_ITEM_ID_ATTRIBUTE),
        "productId": str(line.get(order_fulfillment_models.PRODUCT_ID_ATTRIBUTE) or ""),
        "productName": str(line.get(ORDER_PRODUCT_NAME_ATTRIBUTE) or ""),
        "quantity": _order_quantity(line, order_fulfillment_models.QUANTITY_ATTRIBUTE),
        "fulfilledQuantity": _order_quantity(line, order_fulfillment_models.FULFILLED_QUANTITY_ATTRIBUTE),
    }


def _unit_order_payload(order: Mapping[str, Any]) -> Dict[str, Any]:
    """One Order row in the projection a Unit Admin fulfills from (§2.6.3).

    Narrower than the legacy ``Order`` type on purpose: no customer phone, no address, no
    payment method, no notes. Administering stock needs the Order's identity, its Unit
    scope, and its lines; a projection that carries nothing cannot disclose anything, and
    the fulfillment path never reads the difference.

    ``fulfillmentVersion`` is the field the next fulfillment conditions on, so absence is
    answered as ``0`` exactly as the legacy ``Order`` projection answers it and as
    ``currentFulfillmentVersion`` pins it for the write guard: the number the admin was
    shown and the number the guard checks are the same number, or a legacy Order could
    never be fulfilled at all. The field stays nullable in the SDL for the same reason the
    legacy one is — the attribute itself is optional in the row — but this read never
    answers null.
    """
    return {
        "orderId": str(order[order_fulfillment_models.ORDER_ID_ATTRIBUTE]),
        "profileId": str(order.get(order_fulfillment_models.PROFILE_ID_ATTRIBUTE) or ""),
        "campaignId": str(order.get(order_fulfillment_models.CAMPAIGN_ID_ATTRIBUTE) or ""),
        "unitId": str(order.get(order_fulfillment_models.UNIT_ID_ATTRIBUTE) or ""),
        "unitCampaignId": str(order.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE) or ""),
        "customerName": str(order.get(ORDER_CUSTOMER_NAME_ATTRIBUTE) or ""),
        "orderDate": str(order.get(ORDER_DATE_ATTRIBUTE) or order.get(ORDER_CREATED_AT_ATTRIBUTE) or ""),
        "fulfillmentVersion": _number(order.get(order_fulfillment_models.FULFILLMENT_VERSION_ATTRIBUTE) or 0),
        "lineItems": [_unit_order_line_payload(line) for line in order_fulfillment_models.order_line_items(order)],
    }


def _unit_scout_campaign_orders(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The individual Orders one Scout Campaign holds for this Unit Campaign.

    Why this read exists: the legacy ``listOrdersByCampaign`` and ``getOrder`` pipelines
    authorize Profile ownership and READ shares only. The Unit Admin who fulfills these
    Orders (§2.4.3, §2.4.4) is neither, so through those reads the screen they are built
    for is empty. Here the authorization is the Order's own origin instead: the caller
    must admin the Unit Campaign the sale was taken under.

    Three rules the answer follows:

    - Tenancy is each row's immutable ``unitCampaignId``, never a scope the caller claims.
      Rows whose origin is another Unit Campaign, and independent sales that carry no Unit
      scope at all, sit in the same partition and are not answered: naming a Scout
      Campaign is not an access path (AUTH-U).
    - The projection is what a fulfillment needs and nothing else (see
      :func:`_unit_order_payload`), so the same read serves the list and the fulfillment
      dialog without a second, wider Order read.
    - Newest first by the Order's own business moment, compared as an instant rather than
      as the text the caller wrote, with ``orderId`` breaking a tie so two pages of one
      list cannot disagree about where the cut falls. The cursor's scope is this Unit
      Campaign and Scout Campaign pair, so a page of one campaign's Orders cannot walk
      another's (PAGE-01).
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    scout_campaign_id = inventory_models.normalize_inventory_id(_query_argument(event, "campaignId"), "campaignId")
    rows = [
        row
        for row in order_fulfillment_models.scout_campaign_order_rows(scout_campaign_id)
        if str(row.get(order_fulfillment_models.UNIT_CAMPAIGN_ID_ATTRIBUTE) or "") == unit_campaign_id
    ]
    orders = [_unit_order_payload(row) for row in rows]
    orders.sort(
        key=lambda order: (_order_sort_instant(order["orderDate"]), order["orderId"]),
        reverse=True,
    )
    scope = f"{UNIT_SCOUT_ORDERS_FIELD}#{unit_campaign_id}#{scout_campaign_id}"
    return dict(paginate_page(orders, scope, _page_argument(event)))


# --- Show & Sell events (§3.1) -------------------------------------------------


def _show_and_sell_marker(*, caller_id: str, operation: str, scope: str, idempotency_key: str) -> Any:
    """Resolve this request's marker address on the event aggregate table.

    The marker rides the table the mutation writes, which is the rule every Show &
    Sell mutation follows (§8.9): a cancellation's marker and its event row are in
    the same transaction, so a replay can never be answered for a commit that did
    not happen, and the seven-day TTL on that table collects the marker with nothing
    else left dangling.
    """
    return marker_keys(
        table_key="show_and_sells",
        table_name=tables.show_and_sells.table_name,
        actor_id=caller_id,
        operation=operation,
        scope=scope,
        idempotency_key=idempotency_key,
    )


def _event_admin_guard(event: Dict[str, Any], caller_id: str, name: str = SHOW_AND_SELL_ID_ARGUMENT) -> Dict[str, Any]:
    """Load the addressed event and require admin of the Unit the event row names.

    Tenancy comes from the event's own ``unitId``, never from a Unit id the caller
    sends, and the denial is ``NOT_FOUND``: a caller who is not an admin of the
    owning Unit is told the same thing whether the event exists or not, so a
    cross-Unit id is never a resource-existence oracle (SEC-03, AUTH-U).
    """
    stored: Dict[str, Any] = dict(show_and_sell_models.load_show_and_sell_or_not_found(_query_argument(event, name)))
    unit_auth.require_unit_admin(caller_id, str(stored[show_and_sell_models.UNIT_ID_ATTRIBUTE]))
    return stored


def _event_detail(event_row: Mapping[str, Any]) -> Dict[str, Any]:
    """The administrative event answer: the aggregate plus its allocation and slot reads.

    ``allocations`` are read through the event's own ``productIds`` rather than
    through ``showAndSellId-index`` — that index is for display, and an eventually
    consistent index can lag a write the event has already committed, which would
    show an admin a stock reservation that no longer matches the balance it was
    taken against (SEC-06).

    The two child reads are part of this one answer on purpose. An admin deciding
    whether to cancel an event is deciding about its stock and its slots at the same
    time, and making the screen ask three times would let the three answers come
    from three different moments.
    """
    payload: Dict[str, Any] = dict(show_and_sell_models.event_admin_payload(event_row))
    payload["allocations"] = [
        show_and_sell_models.allocation_payload(row) for row in show_and_sell_models.event_allocations(event_row)
    ]
    payload["slots"] = [
        show_and_sell_models.slot_admin_payload(row)
        for row in sorted(
            show_and_sell_models.event_slot_rows(str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE])),
            key=lambda row: (str(row.get(show_and_sell_models.START_AT_ATTRIBUTE) or ""), str(row.get("slotId") or "")),
        )
    ]
    return payload


def _event_list_filters(event: Dict[str, Any]) -> Dict[str, Any]:
    """Read ``showAndSells``' optional state and date-window filters."""
    arguments = event.get("arguments")
    status = arguments.get("status") if isinstance(arguments, Mapping) else None
    range_value = arguments.get("dateRange") if isinstance(arguments, Mapping) else None
    start_at, end_at = inventory_models.normalize_date_range(range_value)
    return {
        "status": None if status is None else show_and_sell_models.normalize_event_status(status),
        "startAt": start_at,
        "endAt": end_at,
    }


def _event_in_window(event_row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    """Whether an event's start falls inside the requested window.

    The window is on ``startAt`` because that is what a schedule is ordered by and
    what the discovery index sorts on; the bound is inclusive at both ends, matching
    ``DateRangeFilter``'s documented shape.
    """
    start = str(event_row.get(show_and_sell_models.START_AT_ATTRIBUTE) or "")
    lower = filters.get("startAt")
    upper = filters.get("endAt")
    if isinstance(lower, str) and start < lower:
        return False
    return not (isinstance(upper, str) and start > upper)


def _event_has_state(event_row: Mapping[str, Any], wanted: Optional[str]) -> bool:
    """Compare the filter against the state the answer reports, not the stored one.

    A filter of ``ENDED`` has to match an event whose row still says ``SCHEDULED`` but
    whose interval has passed, because that is the state the same query reports: a
    filter that matched the stored spelling instead would answer "no ended events"
    about an event the caller can see listed as ended two lines above.
    """
    if wanted is None:
        return True
    return bool(show_and_sell_models.derive_event_status(event_row) == wanted)


def _create_show_and_sell(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Create an event on a Unit Campaign (§3.1.2, EVT-M-01).

    The caller chooses location, interval, split and We Owe; everything else is the
    server's to decide. Two of those choices are load-bearing:

    - The interval is validated once, here, and is never writable afterwards, so
      "cancellable only before ``startAt``" and every interval comparison in later
      stages are decisions about a value that cannot have moved.
    - ``splitMethod`` inherits the Unit's default unless the caller overrides it, so
      an event never silently acquires a split nobody chose for that Unit.

    Overlap is allowed and not even warned about (SSE-02): two events may run at the
    same time, and whether they may share stock is §3.2's concurrent-assignment rule,
    decided against real allocations rather than against a calendar guess here.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    unit_campaign_id = _resource_id(payload, "unitCampaignId")

    campaign = unit_campaign_models.load_unit_campaign_or_not_found(unit_campaign_id)
    unit = unit_models.load_unit_or_not_found(str(campaign["unitId"]))
    unit_auth.require_unit_admin(caller_id, str(campaign["unitId"]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(
        caller_id=caller_id, operation=CREATE_SHOW_AND_SELL_FIELD, scope=unit_campaign_id, idempotency_key=key
    )
    replayed = _replay(runner, keys, fingerprint, CREATE_SHOW_AND_SELL_FIELD, _load_event_answer)
    if replayed is not None:
        return replayed

    event_id = show_and_sell_models.new_show_and_sell_id()
    item = show_and_sell_models.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=str(campaign["unitId"]),
        unit_campaign_id=unit_campaign_id,
        location_name=payload.get("locationName"),
        address=payload.get("address"),
        start_at=payload.get("startAt"),
        end_at=payload.get("endAt"),
        split_method=payload.get("splitMethod") or unit.get("splitDefault"),
        we_owe_enabled=payload.get("weOweEnabled"),
        created_by_account_id=caller_id,
        now_iso=utc_now_iso(),
    )

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=event_id)
    plan.add(*show_and_sell_models.put_show_and_sell_action(item))
    build_result = _once(lambda: _event_detail(item))
    runner.execute(
        keys,
        plan,
        operation=CREATE_SHOW_AND_SELL_FIELD,
        fingerprint=fingerprint,
        result_id=event_id,
        load_result=_load_event_answer,
        result_payload=build_result,
    )
    created = build_result()
    log.info(
        "Show & Sell created",
        show_and_sell_id=event_id,
        unit_campaign_id=unit_campaign_id,
        caller_id=caller_id,
        start_at=created["startAt"],
    )
    return created


def _load_event_answer(stored_id: str) -> Dict[str, Any]:
    """Rebuild an event answer from the stored row, for a marker with no payload."""
    return _event_detail(show_and_sell_models.load_show_and_sell_or_not_found(stored_id))


def _event_update_changes(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """The writable fields this update actually offered, normalized.

    Three rules are stated here and nowhere else:

    - A field that is absent is left alone. ``address`` is the one field a caller may
      also send as null, and null means "clear it" — the difference between the two is
      the difference between an unchanged address and no address.
    - ``splitMethod`` and ``weOweEnabled`` are booleans-of-choice: sending null means
      nothing the caller wants changed, so it is not a change.
    - Any other name in the input is refused outright, which is where
      ``startAt``/``endAt`` die (EVT-M-02-01). The refusal is an invalid input rather
      than a silently ignored field: a caller who believes they rescheduled an event
      and is told nothing has an event they will show up at at the wrong time.
    """
    offered = {name: value for name, value in payload.items() if name not in _EVENT_INPUT_BOOKKEEPING}
    changes = show_and_sell_models.writable_changes(offered)
    normalized: Dict[str, Any] = {}
    if changes.get(show_and_sell_models.LOCATION_NAME_ATTRIBUTE) is not None:
        normalized[show_and_sell_models.LOCATION_NAME_ATTRIBUTE] = show_and_sell_models.normalize_location_name(
            changes[show_and_sell_models.LOCATION_NAME_ATTRIBUTE]
        )
    if show_and_sell_models.ADDRESS_ATTRIBUTE in changes:
        normalized[show_and_sell_models.ADDRESS_ATTRIBUTE] = show_and_sell_models.normalize_address(
            changes[show_and_sell_models.ADDRESS_ATTRIBUTE]
        )
    if changes.get(show_and_sell_models.SPLIT_METHOD_ATTRIBUTE) is not None:
        normalized[show_and_sell_models.SPLIT_METHOD_ATTRIBUTE] = show_and_sell_models.normalize_split_method(
            changes[show_and_sell_models.SPLIT_METHOD_ATTRIBUTE]
        )
    if changes.get(show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE) is not None:
        normalized[show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE] = show_and_sell_models.normalize_we_owe_enabled(
            changes[show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE]
        )
    if not normalized:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"At least one of {', '.join(sorted(show_and_sell_models.WRITABLE_FIELDS))} must be provided.",
        )
    return normalized


def _require_read_version(row: Mapping[str, Any], expected_version: int, noun: str = "event") -> None:
    """Refuse a mutation whose supplied version is not the row that was just read.

    The version condition on the write is what makes a race safe, but on its own it
    only proves that nobody moved the row since the *caller* read it. Every state rule
    in this handler — "still editable", "still cancellable" — is evaluated against the
    row *this request* read a moment earlier. If the caller's number is allowed to be a
    different one, those two reads come apart: a request holding version 2 can pass the
    editable check against a freshly-read SCHEDULED version 1, a competing cancellation
    then commits version 2, and the write's condition matches a row whose state was
    never checked. Requiring the supplied version to equal the row just read makes the
    state and the version one fact about one row, and the conditional write still
    guards the window between this read and the commit.
    """
    read_version = show_and_sell_models.normalize_required_version(row.get(show_and_sell_models.VERSION_ATTRIBUTE, 1))
    if expected_version == read_version:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        f"The {noun} changed since you read it. Re-read it and retry with the version the read answered.",
        details={
            "subcode": "VERSION_MISMATCH",
            "expectedVersion": expected_version,
            "currentVersion": read_version,
        },
    )


def _refuse_unsafe_we_owe_disable(event_row: Mapping[str, Any], changes: Mapping[str, Any], event_id: str) -> None:
    """Refuse a We Owe switch-off that would strand an open obligation (EVT-M-02-02).

    Turning We Owe off is not a display setting: it is the event saying it will not
    offer deferred payment. An obligation that is still OPEN is a Kernel the buyer is
    owed and the event has promised to account for, and an event that no longer offers
    We Owe has no legal way to finish it — so the change is refused while any
    obligation is open, and allowed once they are all closed, at which point they are
    history rather than a promise.
    """
    turning_off = changes.get(show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE) is False
    if not turning_off or not bool(event_row.get(show_and_sell_models.WE_OWE_ENABLED_ATTRIBUTE)):
        return
    obligations = show_and_sell_models.event_we_owe_rows(event_id)
    if not show_and_sell_models.we_owe_disable_blocked(obligations):
        return
    open_count = sum(
        1 for row in obligations if str(row.get("status") or "") == show_and_sell_models.WE_OWE_STATUS_OPEN
    )
    raise AppError(
        ErrorCode.CONFLICT,
        (
            f"This event still has {open_count} open We Owe obligation(s). Close or cancel them before "
            "turning We Owe off, so no buyer is left owing and unaccounted for."
        ),
        details={"subcode": "WE_OWE_OBLIGATIONS_OPEN", "openObligationCount": open_count},
    )


def _update_show_and_sell(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Edit an event's location, address, split, or We Owe setting (§3.1.3, EVT-M-02).

    The state matrix is checked before the write, and the version condition is what
    makes the check honest: between the read and the commit the event may have been
    finalized, cancelled, or edited by another Kernel, and in every one of those cases
    the version the caller read has moved and the transaction writes nothing. A
    state check that only ever ran against a fresh read would let two admins each
    believe they edited an event that had already been finalized.

    Replay is consulted before the state and version checks for the usual reason: the
    first attempt's own write moved the version, and a retry that re-ran the guard
    would answer ``CONFLICT`` about a request it already completed.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _update_fingerprint(payload)
    event_id = _resource_id(payload, show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE)
    expected_version = _expected_version(payload)

    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    unit_auth.require_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(
        caller_id=caller_id, operation=UPDATE_SHOW_AND_SELL_FIELD, scope=event_id, idempotency_key=key
    )
    replayed = _replay(runner, keys, fingerprint, UPDATE_SHOW_AND_SELL_FIELD, _load_event_answer)
    if replayed is not None:
        return replayed

    # After replay for the reason the docstring names: the first attempt's own write
    # moved the version, so a retry that re-ran this would answer CONFLICT about a
    # request it already completed.
    _require_read_version(event_row, expected_version)
    changes = _event_update_changes(payload)
    show_and_sell_models.require_editable(event_row)
    _refuse_unsafe_we_owe_disable(event_row, changes, event_id)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=event_id)
    plan.add(
        *show_and_sell_models.update_event_settings_action(
            show_and_sell_id=event_id,
            expected_version=expected_version,
            changes=changes,
            updated_by_account_id=caller_id,
            updated_at=utc_now_iso(),
        )
    )
    build_result = _once(lambda: _load_event_answer(event_id))
    runner.execute(
        keys,
        plan,
        operation=UPDATE_SHOW_AND_SELL_FIELD,
        fingerprint=fingerprint,
        result_id=event_id,
        load_result=_load_event_answer,
        result_payload=build_result,
    )
    updated = build_result()
    log.info(
        "Show & Sell updated",
        show_and_sell_id=event_id,
        caller_id=caller_id,
        version=updated["version"],
        changed=sorted(changes),
    )
    return updated


def _cancellation_reads(event_row: Mapping[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Everything a cancellation has to know before it writes anything (§8.8 step 1).

    Each read is the authoritative one: allocations come from the event's
    ``productIds`` through consistent reads, signups and slots from the event's own
    partition, and the commitment projections from the Scout's partition rather than
    from a signup index — because a commitment is what blocks a later overlapping
    signup, so the writer that releases one has to be looking at the row the blocker
    reads (SEC-06).
    """
    event_id = str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE])
    signups = show_and_sell_models.active_signups(event_id)
    profiles: List[str] = []
    commitments: List[Dict[str, Any]] = []
    for signup in signups:
        profile_id = str(signup[show_and_sell_models.PROFILE_ID_ATTRIBUTE])
        if profile_id not in profiles:
            profiles.append(profile_id)
        # Only the ACTIVE commitments are released. The projection keeps cancelled
        # rows as history (§5.13), and rewriting one would move an audit record this
        # request did not create — and spend a transaction action on it.
        commitments.extend(
            row
            for row in show_and_sell_models.active_commitments(profile_id, event_id)
            if str(row.get(show_and_sell_models.SLOT_ID_ATTRIBUTE) or "")
            == str(signup[show_and_sell_models.SLOT_ID_ATTRIBUTE])
        )
    return {
        "allocations": show_and_sell_models.open_allocations(event_row),
        "signups": signups,
        "profiles": profiles,
        "commitments": commitments,
        "slots": show_and_sell_models.slots_holding_signups(event_id),
    }


def _stage_cancellation_writes(
    plan: Any,
    event_row: Mapping[str, Any],
    reads: Mapping[str, List[Dict[str, Any]]],
    *,
    event_id: str,
    expected_version: int,
    caller_id: str,
    reason: str,
    now_iso: str,
    idempotency_key: str,
) -> None:
    """Stage §8.8 step 3 in one plan: the event, then everything it releases.

    Every action is conditioned on the version this request read — the event's, each
    allocation's, each signup's, each slot's, and each Scout's commitment guard. That
    is what turns a race with a concurrent signup or assignment into a cancelled
    transaction instead of a partially applied one, and it is why a cancellation that
    lost the race is retried against fresh state rather than resurrecting a record the
    other writer already closed (§8.8 step 4).

    The release movement is written next to each allocation write because an
    allocation that silently dropped its reservation would leave the audit trail unable
    to explain the balance it now adds up to. Its delta is the allocation's own
    remaining quantity — the quantity this request moves — and it is the only delta
    ``EVENT_RELEASE`` may move: a cancellation releases a reservation, it never moves a
    Kernel. The allocation row's ``releasedQty`` is the other number, the new
    cumulative total, and keeping the two apart is what lets the movement trail sum to
    the allocation instead of double-counting an earlier release.

    A signup and the commitment projection it mirrors move to one shared new version
    (§5.13: ``ScoutCommitment.version`` "matches source signup update"), so a reader
    who compares the pair sees one transition rather than two disagreeing versions.
    """
    plan.add(
        *show_and_sell_models.cancel_event_action(
            show_and_sell_id=event_id,
            expected_version=expected_version,
            cancelled_by_account_id=caller_id,
            cancelled_at=now_iso,
            reason=reason,
        )
    )
    for allocation in reads["allocations"]:
        remaining = int(allocation.get(inventory_models.REMAINING_QTY, 0) or 0)
        released_total = int(allocation.get(inventory_models.RELEASED_QTY, 0) or 0) + remaining
        plan.add(
            *show_and_sell_models.cancel_allocation_action(
                allocation=allocation, released_total=released_total, updated_at=now_iso
            )
        )
        plan.add(
            *show_and_sell_models.event_release_movement_action(
                event=event_row,
                allocation=allocation,
                released_qty=remaining,
                actor_account_id=caller_id,
                occurred_at=now_iso,
                idempotency_key=idempotency_key,
            )
        )
    new_signup_versions: Dict[Tuple[str, str], int] = {}
    for signup in reads["signups"]:
        signup_version = show_and_sell_models.normalize_required_version(signup.get("version", 1))
        slot_id = str(signup[show_and_sell_models.SLOT_ID_ATTRIBUTE])
        profile_id = str(signup[show_and_sell_models.PROFILE_ID_ATTRIBUTE])
        new_signup_versions[(profile_id, slot_id)] = signup_version + 1
        plan.add(
            *show_and_sell_models.cancel_signup_action(
                show_and_sell_id=event_id,
                slot_id=slot_id,
                profile_id=profile_id,
                expected_version=signup_version,
                new_version=signup_version + 1,
                updated_at=now_iso,
            )
        )
    for commitment in reads["commitments"]:
        pair = (
            str(commitment[show_and_sell_models.PROFILE_ID_ATTRIBUTE]),
            str(commitment[show_and_sell_models.SLOT_ID_ATTRIBUTE]),
        )
        plan.add(
            *show_and_sell_models.cancel_commitment_action(
                commitment=commitment,
                new_version=new_signup_versions[pair],
                updated_at=now_iso,
            )
        )
    for guard_profile_id in reads["profiles"]:
        # One guard bump per Scout, however many slots this cancellation released for
        # them: the guard serializes commitment changes across the Scout's whole set of
        # memberships, and one transaction that moved two of their commitments has to
        # advance that single number once (§5.13).
        plan.add(*show_and_sell_models.bump_commitment_guard_action(profile_id=guard_profile_id, updated_at=now_iso))
    for slot in reads["slots"]:
        plan.add(
            *show_and_sell_models.zero_slot_counter_action(
                show_and_sell_id=event_id,
                slot_id=str(slot[show_and_sell_models.SLOT_ID_ATTRIBUTE]),
                expected_version=show_and_sell_models.normalize_required_version(slot.get("version", 1)),
                updated_at=now_iso,
            )
        )


def _cancellation_answer(event_id: str) -> Dict[str, Any]:
    """The one coherent result a cancellation owes: the event, the stock, the Scouts.

    "Released" and "cancelled" mean *by this commit*. Every row this transaction wrote
    carries the same instant as the event's ``cancelledAt``, so that stamp is what
    separates the rows this request moved from the rows an earlier request closed —
    a signup a Scout cancelled themselves through §3.4, or an allocation §3.2 released
    before the event was called off. Reporting those as this cancellation's work would
    overstate what the caller did and, on a replay, would answer a different set of rows
    than the first attempt committed.

    The same rule makes the replay exact: the event row still carries ``cancelledAt``
    after the commit, so a retry rebuilds the identical answer from the rows the first
    attempt stamped.
    """
    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    stamp = str(event_row.get(show_and_sell_models.CANCELLED_AT_ATTRIBUTE) or "")
    released = [
        show_and_sell_models.allocation_payload(row)
        for row in show_and_sell_models.event_allocations(event_row)
        if _written_by_this_commit(row, stamp)
    ]
    signups = [
        show_and_sell_models.signup_admin_payload(row)
        for row in show_and_sell_models.event_signup_rows(event_id)
        if _written_by_this_commit(row, stamp)
    ]
    return {"event": _event_detail(event_row), "releasedAllocations": released, "cancelledSignups": signups}


def _written_by_this_commit(row: Mapping[str, Any], cancelled_at: str) -> bool:
    """Whether one row is a cancelled-state row carrying this cancellation's own instant.

    A row §3.2 closed on its own — ``RELEASED`` by an allocation mutation, or cancelled
    earlier — fails here on its state or on its instant, so it is never reported as this
    request's work. An event row with no ``cancelledAt`` can only answer an empty stamp,
    which no aggregate row carries, so the result is empty rather than a guess.
    """
    status = str(row.get(show_and_sell_models.STATUS_ATTRIBUTE) or "")
    if status not in (inventory_models.ALLOCATION_CANCELLED, show_and_sell_models.SIGNUP_CANCELLED):
        return False
    return str(row.get(show_and_sell_models.UPDATED_AT_ATTRIBUTE) or "") == cancelled_at


def _cancel_show_and_sell(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Cancel a future event and release everything it holds (§3.1.4, EVT-M-03).

    Two independent guards say the same thing in different ways, and both are needed:
    the state must still be ``SCHEDULED``, and the current instant must still precede
    ``startAt``. The first catches an event the clock has already moved past; the
    second catches a stored state that has not caught up to an event that has begun.
    Past ``startAt`` the answer is ``CONFLICT`` — Scouts have begun working, so the
    event is finished by finalizing it, and §8.8's release arithmetic no longer
    describes what happened (EVT-M-03-02).

    The reason is required and is written in the same write as the state change: an
    admin cancelling stock reservations and other people's signups owes a record of
    why, and a cancellation that committed and then lost its reason would be an
    untraceable state change.

    The plan size is not checked here. ``WritePlan`` counts every action as it is
    staged — the marker, the event, each allocation with its movement, each signup,
    each commitment, each guard, each slot counter — and refuses the 91st before a
    single DynamoDB call is made (§8.10, EVT-M-03-03). The reduction that makes an
    oversized event cancellable is real and available to the caller: cancel the
    signups first, then the event.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    event_id = _resource_id(payload, show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE)
    expected_version = _expected_version(payload)
    reason = show_and_sell_models.normalize_cancellation_reason(payload.get("reason"))

    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    unit_auth.require_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(
        caller_id=caller_id, operation=CANCEL_SHOW_AND_SELL_FIELD, scope=event_id, idempotency_key=key
    )
    replayed = _replay(runner, keys, fingerprint, CANCEL_SHOW_AND_SELL_FIELD, _cancellation_answer)
    if replayed is not None:
        return replayed

    # Replay first, then one fact about one row: the state guard and the version guard
    # are both evaluated against the row this request just read, so the conditional
    # write cannot match a row whose state was never checked.
    _require_read_version(event_row, expected_version)
    show_and_sell_models.require_cancellable(event_row)
    reads = _cancellation_reads(event_row)

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=event_id)
    _stage_cancellation_writes(
        plan,
        event_row,
        reads,
        event_id=event_id,
        expected_version=expected_version,
        caller_id=caller_id,
        reason=reason,
        now_iso=utc_now_iso(),
        idempotency_key=key,
    )
    build_result = _once(lambda: _cancellation_answer(event_id))
    runner.execute(
        keys,
        plan,
        operation=CANCEL_SHOW_AND_SELL_FIELD,
        fingerprint=fingerprint,
        result_id=event_id,
        load_result=_cancellation_answer,
        result_payload=build_result,
    )
    cancelled = build_result()
    log.info(
        "Show & Sell cancelled",
        show_and_sell_id=event_id,
        caller_id=caller_id,
        allocations=len(cancelled["releasedAllocations"]),
        signups=len(cancelled["cancelledSignups"]),
        planned_actions=plan.action_count,
    )
    return cancelled


# --- Event reads (§3.1.5) ------------------------------------------------------


def _show_and_sell(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One event's administrative detail (§6.1, EVT-Q-01-01)."""
    return _event_detail(_event_admin_guard(event, caller_id))


def _show_and_sells(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """A campaign's events, soonest first, with state and date-window filters.

    Discovery is the campaign GSI; the rows themselves come back through consistent
    reads, so the page reports the state the events are in now rather than the state
    an index had reached when it was last updated. Both filters are part of the
    cursor scope, so a cursor from a ``FINALIZED`` page cannot walk an unfiltered
    schedule (PAGE-01).

    The detail reads (allocations and slots) are built for the page's rows only,
    after the slice, so a one-page request does not pay for events it never sees.
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    filters = _event_list_filters(event)
    rows = [
        row for row in show_and_sell_models.list_campaign_events(unit_campaign_id) if _event_in_window(row, filters)
    ]
    rows = [row for row in rows if _event_has_state(row, filters["status"])]
    token = "#".join("" if filters[name] is None else str(filters[name]) for name in ("status", "startAt", "endAt"))
    page = dict(paginate_page(rows, f"{SHOW_AND_SELLS_FIELD}#{unit_campaign_id}#{token}", _page_argument(event)))
    page["items"] = [_event_detail(row) for row in page["items"]]
    return page


def _eligible_scout_ids(caller_id: str, unit_campaign_id: str) -> List[Dict[str, Any]]:
    """The roster rows on this campaign whose Scout this caller may read.

    The check is the existing Profile access rule — ownership or a READ/WRITE share —
    run over the campaign's own roster in one batch, so the candidate set is the
    campaign's members and never some profile id the caller typed. A Unit Admin is not
    eligible through this path: an admin reads ``showAndSells``, which answers the
    administrative type, and the participant surface stays participant-shaped.
    """
    # Consistent, because this read decides who may see anything. A stale ACTIVE row
    # that outlives a removal would put a former member back in ``active_ids``, and the
    # history-only rule for a removed Scout would then hand them the campaign's whole
    # upcoming schedule (EVT-Q-02-02).
    roster = unit_campaign_models.list_memberships(unit_campaign_id, consistent_read=True)
    profile_ids = [str(row["profileId"]) for row in roster]
    if not profile_ids:
        return []
    accessible = batch_check_profile_access(caller_id, profile_ids, "READ")
    return [row for row in roster if str(row["profileId"]) in accessible]


def _opportunity_answer(
    event_row: Mapping[str, Any], *, timezone_name: str, signups: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """The participant answer for one event: its slots, and the caller's signups.

    The slots are ordered by when they run, and a signup inherits its position from the
    slot it holds — the signup row carries no interval of its own (§5.13), so the slot
    partition is the only place that order exists.
    """
    slots = show_and_sell_models.event_slot_rows(str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]))
    ordered = sorted(slots, key=lambda row: (str(row.get("startAt") or ""), str(row.get("slotId") or "")))
    starts = {str(row.get("slotId") or ""): str(row.get("startAt") or "") for row in ordered}
    signups = sorted(
        signups, key=lambda row: (starts.get(str(row.get("slotId") or ""), ""), str(row.get("slotId") or ""))
    )
    return dict(
        show_and_sell_models.opportunity_payload(
            event_row,
            timezone_name=timezone_name,
            slots=ordered,
            signups=signups,
        )
    )


def _signup_rows_for(event_id: str, profile_ids: Sequence[str]) -> List[Dict[str, Any]]:
    """The event's signup rows belonging to any of these Scouts, in a stable order.

    One partition read per event covers every Scout in the caller's set, which is why
    the profile filter happens on the rows rather than in the key. The order is the
    slot and profile identity, not an interval: §5.13 gives a signup row no
    ``startAt``/``endAt``, and sorting on a missing attribute silently degenerates into
    insertion order (the slot's own order is applied when the payload is built).
    """
    wanted = set(profile_ids)
    rows = [
        row
        for row in show_and_sell_models.event_signup_rows(event_id)
        if str(row.get(show_and_sell_models.PROFILE_ID_ATTRIBUTE) or "") in wanted
    ]
    return sorted(rows, key=lambda row: (str(row.get("slotId") or ""), str(row.get("profileId") or "")))


def _roster_membership_split(eligible: Sequence[Mapping[str, Any]]) -> Tuple[List[str], List[str]]:
    """Split a caller's eligible roster rows into current and former members.

    The split decides visibility, not eligibility: an ACTIVE row is what lets a Scout
    be offered a new event, and a REMOVED row only ever shows what that Scout already
    took part in. Keeping the two lists apart is what makes that difference a fact
    about the rows rather than a flag a caller sets.
    """
    active: List[str] = []
    former: List[str] = []
    for row in eligible:
        profile_id = str(row["profileId"])
        if str(row.get("status") or "") == unit_campaign_models.MEMBERSHIP_STATUS_ACTIVE:
            active.append(profile_id)
        else:
            former.append(profile_id)
    return active, former


def _visible_opportunities(
    unit_campaign_id: str,
    *,
    active_ids: Sequence[str],
    former_ids: Sequence[str],
    include_past: bool,
) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """The campaign's events that are this caller's to see, soonest first.

    The answer is the candidate set — each event row paired with the signup rows that
    name it — rather than the built payloads. Hydrating a payload costs a slot partition
    read per event, so it happens after the page is cut: otherwise ``page.limit`` bounds
    what the caller receives and nothing bounds what the handler reads, and a campaign
    with a long history pays for every event on every page.

    Two exclusions, and both are about the Scout rather than the event:

    - A cancelled event is dropped. Its row is still listed for an admin through
      ``showAndSells``, with its reason and actor; on the participant surface it would
      read as a cancelled offer, which is nothing a Scout can act on.
    - With no current membership behind the caller, only the events actually holding
      one of the former member's signup rows come back (EVT-Q-02-02). A removed Scout
      keeps the participation history and gains no new opportunity.

    Signup rows are read per event, not per Scout, because the event's own partition
    covers every Scout in the caller's set at once.
    """
    all_ids = list(active_ids) + list(former_ids)
    candidates: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for event_row in show_and_sell_models.list_campaign_events(unit_campaign_id):
        state = show_and_sell_models.derive_event_status(event_row)
        if state == show_and_sell_models.STATUS_CANCELLED:
            continue
        if not include_past and state not in show_and_sell_models.OPEN_STATUSES:
            continue
        event_id = str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE])
        signups = _signup_rows_for(event_id, all_ids)
        if not active_ids and not any(str(row.get("profileId") or "") in former_ids for row in signups):
            continue
        candidates.append((dict(event_row), signups))
    return candidates


def _unit_campaign_opportunities(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """The events one campaign is offering to this caller's own Scouts (§6.1, EVT-Q-02).

    Who may ask, and what they are shown, are the same question. The caller is
    eligible through a Profile they can read that holds a roster row on this campaign;
    with no such Scout the answer is ``NOT_FOUND``, because naming a campaign is not an
    access path and the answer must not confirm that the campaign has events at all
    (SEC-03, AUTH-P).

    A Scout removed from the roster keeps visibility of what they already took part in
    and gains no new opportunity (EVT-Q-02-02): their membership row says ``REMOVED``,
    which blocks a new signup, so their events are exactly the ones holding one of
    their signup rows — cancelled ones included, because a cancelled signup is still
    the participation history that visibility is based on.

    A cancelled event is never an opportunity. Its row may still be listed for an
    admin, who reads it through ``showAndSells`` with its reason and actor; on the
    participant surface it would read as a cancelled offer, which is not a thing a
    Scout can act on.
    """
    campaign = unit_campaign_models.load_unit_campaign_or_not_found(_query_argument(event, "unitCampaignId"))
    unit_campaign_id = str(campaign["unitCampaignId"])
    include_past = bool((event.get("arguments") or {}).get("includePast"))

    eligible = _eligible_scout_ids(caller_id, unit_campaign_id)
    if not eligible:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")

    active_ids, former_ids = _roster_membership_split(eligible)
    unit = unit_models.load_unit_or_not_found(str(campaign["unitId"]))
    candidates = _visible_opportunities(
        unit_campaign_id,
        active_ids=active_ids,
        former_ids=former_ids,
        include_past=include_past,
    )
    scope = f"{UNIT_CAMPAIGN_OPPORTUNITIES_FIELD}#{unit_campaign_id}#{caller_id}#{int(include_past)}"
    timezone_name = str(unit.get("timezone") or "")
    page = dict(paginate_page(candidates, scope, _page_argument(event)))
    # Hydration after the slice: only the events on this page pay for their slots.
    page["items"] = [
        _opportunity_answer(event_row, timezone_name=timezone_name, signups=signups)
        for event_row, signups in page["items"]
    ]
    return page


def _show_and_sell_opportunity(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One event's participant view for one Scout (§6.1, EVT-Q-03).

    Every denial here is ``NOT_FOUND`` and every denial is decided before any
    participant fact is returned: an unjoined Scout, a Scout the caller cannot read,
    and an event in another Unit are answered identically, so nothing about the
    existence of someone else's event or roster row is disclosed (SEC-03, EVT-Q-03-02).

    A Unit Admin may read the same view, which is the one case where the caller is not
    the Scout's Profile holder — and even then the Scout must hold a roster row on the
    event's campaign, because "ineligible Scout receives ``NOT_FOUND``" is about the
    Scout's eligibility, not about who is asking.
    """
    event_row = show_and_sell_models.load_show_and_sell_or_not_found(_query_argument(event, SHOW_AND_SELL_ID_ARGUMENT))
    profile_id = _query_argument(event, "profileId")
    unit_campaign_id = str(event_row[show_and_sell_models.UNIT_CAMPAIGN_ID_ATTRIBUTE])

    membership = unit_campaign_models.read_membership(unit_campaign_id, profile_id)
    if membership is None:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    is_admin = unit_auth.is_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))
    if not is_admin and not check_profile_access(caller_id, profile_id, "READ"):
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")

    # A cancelled event is answered exactly like an event that was never there. The
    # campaign-level read already drops it, and this field answers the participant type
    # rather than the administrative one: leaving it readable would give a Scout a
    # per-event path to a cancelled offer that the list refuses, so the two surfaces
    # would disagree about the same row (EVT-Q-02-02, EVT-Q-03-02).
    if show_and_sell_models.derive_event_status(event_row) == show_and_sell_models.STATUS_CANCELLED:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")

    signups = _signup_rows_for(str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]), [profile_id])
    removed = str(membership.get("status") or "") != unit_campaign_models.MEMBERSHIP_STATUS_ACTIVE
    if removed and not signups:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")

    unit = unit_models.load_unit_or_not_found(str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))
    timezone_name = str(unit.get("timezone") or "")
    return _opportunity_answer(event_row, timezone_name=timezone_name, signups=signups)


# --- Event stock assignment (§3.2.3) ---------------------------------------------


def _assignment_targets(payload: Mapping[str, Any]) -> List[allocation_models.AllocationTarget]:
    """This batch's per-product stock targets, validated (§6.2 ``AllocationTargetInput``).

    The quantity is the event's whole target for that product, never an amount to add:
    two Kernels both reading 3 and both typing 5 must not produce 8. §3.2.1's target-not-
    delta rule is enforced by the planner, which turns a target into the one delta a
    movement is allowed to report.
    """
    return cast(
        List[allocation_models.AllocationTarget],
        allocation_models.normalize_allocation_targets(payload.get("items")),
    )


def _assignment_sections(
    unit_campaign_id: str, product_ids: Sequence[str]
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Every row each addressed product's position is made of, in one consistent read each.

    The balance and the campaign's allocation rows for that product must come from the
    same read (§8.4): the concurrent-overlap rule compares a candidate target against the
    campaign's other commitments of that product, and a balance read from a different
    moment than the allocations that compete with it is the bug where four boxes carry
    three to each of two events. Reading per product rather than the whole campaign
    partition is what keeps a two-product save cheap on a campaign with a long history,
    and it keys every product the caller named: one with no rows at all answers with an
    empty section, so a caller never has to guess whether a missing key means "not
    stocked" or "not asked for".
    """
    return dict(inventory_models.campaign_product_sections(unit_campaign_id, product_ids))


def _section_balance(section: Mapping[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """One product's ``InventoryBalance`` row, or ``None`` before the first receipt."""
    return section["balance"][0] if section["balance"] else None


def _event_allocation_row(allocations: Sequence[Mapping[str, Any]], event_id: str) -> Optional[Dict[str, Any]]:
    """This event's allocation row for one product, out of that product's allocation rows."""
    for row in allocations:
        if str(row.get(show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE) or "") == event_id:
            return cast(Dict[str, Any], row)
    return None


def _refuse_concurrent_over_assignment(conflict: allocation_models.ConcurrentConflict) -> None:
    """Refuse an assignment that over-assigns at a shared instant, and say where (ALLOC-02).

    The refusal carries the four numbers AC-09 asks the screen to be able to state — the
    product, the stock that is really there, the assigned total, and the overage — plus
    the instant they collide at, which is the fact a sampled check would have to guess.
    """
    raise AppError(
        ErrorCode.CONFLICT,
        allocation_models.conflict_message(conflict),
        details={
            "subcode": allocation_models.CONCURRENT_OVER_ASSIGNMENT,
            "productId": conflict.product_id,
            "currentStockQty": conflict.current_stock_qty,
            "assignedQty": conflict.assigned_qty,
            "overageQty": conflict.overage_qty,
            "at": conflict.at,
        },
    )


def _plan_live_assignments(
    event_row: Mapping[str, Any],
    targets: Sequence[allocation_models.AllocationTarget],
    sections: Mapping[str, Mapping[str, List[Dict[str, Any]]]],
    event_id: str,
) -> List[allocation_models.AllocationChange]:
    """Plan every product in the batch and refuse the batch if any of it collides (§8.4).

    All of the planning happens before any of the staging, because a request that is
    refused must change nothing: with the writes staged first, a product accepted early
    in the batch would already be in the transaction when a later product's target turned
    out to over-assign. The concurrency rule is evaluated on the campaign's other open
    allocations for that product, with this event's own row excluded from them because the
    candidate replaces it rather than stacks on top of it, and passed to the evaluator as
    the state each instant carried before this write — ALLOC-02 is a per-instant rule, so
    the question is what each instant committed before and after, not how large the
    campaign's single worst instant is.

    A target that restates what the row already carries yields no change and is simply
    absent from the plan: it spends no movement and no allocation write, while the request
    still commits its marker and moves the event version.
    """
    existing_by_product = {
        target.product_id: _event_allocation_row(
            sections[target.product_id]["allocations"],
            event_id,
        )
        for target in targets
    }
    changes: List[allocation_models.AllocationChange] = allocation_models.plan_allocation_targets(
        event_row, targets, existing_by_product
    )
    for change in changes:
        section = sections[change.product_id]
        existing = existing_by_product[change.product_id]
        conflict = allocation_models.concurrent_conflict(
            product_id=change.product_id,
            sellable_qty=inventory_models.sellable_kernel_qty(_section_balance(section)),
            start_at=change.start_at,
            end_at=change.end_at,
            remaining_qty=change.remaining_qty,
            other_allocations=[row for row in section["allocations"] if row is not existing],
            current_allocation=existing,
        )
        if conflict is not None:
            _refuse_concurrent_over_assignment(conflict)
    return changes


def _stage_assignment_writes(
    plan: Any,
    event_row: Mapping[str, Any],
    changes: Sequence[allocation_models.AllocationChange],
    sections: Mapping[str, Mapping[str, List[Dict[str, Any]]]],
    *,
    event_id: str,
    product_ids: Sequence[str],
    expected_version: int,
    caller_id: str,
    idempotency_key: str,
    now_iso: str,
) -> None:
    """Stage §3.2.3's live-state write plan: allocations, movements, balance versions, event row.

    One product's three writes and their order:

    - the balance row's ``version`` moves with no quantity changed. §3.2.3 names balance
      versions, and it is what a position reader needs: ``assignedOpenQty`` is derived
      from allocation rows (§7), so without the version moving, a caller holding a
      position could not tell that the number they derived had changed underneath them.
      ``kernelPhysicalQty`` is not touched, which is EVT-M-04's "physical stock never
      changes" as a property of the staged writes rather than of the planner alone.
    - the allocation row, a conditional ``Put`` when the event holds this product for the
      first time and a versioned ``Update`` otherwise — one row per (campaign, product,
      event) is §5.11's uniqueness, and the condition is what enforces it under a
      concurrent assignment of the same product to the same event.
    - the movement, whose ``assignedDelta`` is what this request moved and whose
      ``inventoryVersion`` names the balance version the bump just produced.

    A product the campaign has never received has no balance row to bump, so its movement
    names no ``inventoryVersion`` — SDL §5.8 makes that field non-null exactly when a
    position row moved, and none did. The event row is staged last and carries the
    cumulative ``productIds`` plus ``version``: the locator and the rows it points at
    commit together, so an allocation can never be unreachable (§8.4).
    """
    for change in changes:
        section = sections[change.product_id]
        balance = _section_balance(section)
        balance_version: Optional[int] = None
        if balance is not None:
            balance_expected_version = _number(balance[inventory_models.VERSION_ATTRIBUTE])
            balance_version = balance_expected_version + 1
            plan.add(
                *inventory_models.inventory_balance_delta_action(
                    unit_campaign_id=change.unit_campaign_id,
                    product_id=change.product_id,
                    existing=balance,
                    expected_version=balance_expected_version,
                    now_iso=now_iso,
                )
            )
        if change.creates_row:
            plan.add(
                *show_and_sell_models.put_allocation_action(
                    inventory_models.build_event_inventory_allocation_item(
                        unit_campaign_id=change.unit_campaign_id,
                        product_id=change.product_id,
                        show_and_sell_id=change.show_and_sell_id,
                        start_at=change.start_at,
                        end_at=change.end_at,
                        allocated_qty=change.allocated_qty,
                        status=change.status,
                        sold_qty=change.sold_qty,
                        released_qty=change.released_qty,
                        now_iso=now_iso,
                    )
                )
            )
        else:
            existing = _event_allocation_row(section["allocations"], event_id)
            if existing is None:  # pragma: no cover - the planner only answers "update" for a row it read
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"{change.product_id} allocation row disappeared between this request's read and its write",
                )
            plan.add(
                *show_and_sell_models.assignment_allocation_action(
                    allocation=existing,
                    allocated_qty=change.allocated_qty,
                    remaining_qty=change.remaining_qty,
                    updated_at=now_iso,
                )
            )
        plan.add(
            *show_and_sell_models.event_assignment_movement_action(
                event=event_row,
                product_id=change.product_id,
                movement_type=change.movement_type,
                assigned_delta=change.assigned_delta,
                inventory_version=balance_version,
                actor_account_id=caller_id,
                occurred_at=now_iso,
                idempotency_key=idempotency_key,
            )
        )
    plan.add(
        *show_and_sell_models.assignment_event_action(
            show_and_sell_id=event_id,
            expected_version=expected_version,
            product_ids=product_ids,
            updated_by_account_id=caller_id,
            updated_at=now_iso,
        )
    )


def _assignment_answer(event_row: Mapping[str, Any]) -> Dict[str, Any]:
    """The assignment result: the event's allocations, positions, and warnings (§6.2).

    Everything is read back from rows rather than assembled from the plan, for the reason
    :func:`_once` states — the stored replay answer and the answer the caller received
    have to be one answer — and because the warnings are a fact about the campaign's
    allocation rows as this write leaves them (ALLOC-03). A product the event lists but
    has no rows for answers at zero, and an over-assignment that is sequential rather than
    concurrent is reported here, with the product, the current stock, the assigned total
    and the overage, exactly as AC-10 requires the screen to state them.
    """
    event_id = str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE])
    unit_campaign_id = str(event_row[show_and_sell_models.UNIT_CAMPAIGN_ID_ATTRIBUTE])
    product_ids = show_and_sell_models.normalize_product_ids(event_row.get(show_and_sell_models.PRODUCT_IDS_ATTRIBUTE))
    sections = inventory_models.campaign_product_sections(unit_campaign_id, product_ids)
    allocations: List[Dict[str, Any]] = []
    positions: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for product_id in product_ids:
        section = sections[product_id]
        allocations.extend(
            show_and_sell_models.allocation_payload(row)
            for row in section["allocations"]
            if str(row.get(show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE) or "") == event_id
        )
        positions.append(_position_payload(unit_campaign_id, product_id, section))
        warning = allocation_models.sequential_warning(
            product_id=product_id,
            sellable_qty=inventory_models.sellable_kernel_qty(_section_balance(section)),
            allocations=section["allocations"],
        )
        if warning is not None:
            warnings.append(warning)
    return {"allocations": allocations, "inventoryPositions": positions, "warnings": warnings}


def _load_assignment_answer(stored_id: str) -> Dict[str, Any]:
    """Rebuild an assignment answer from the stored event row, for a marker with no payload."""
    return _assignment_answer(show_and_sell_models.load_show_and_sell_or_not_found(stored_id))


def _assign_show_and_sell_inventory(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Set a live event's stock target per product (§3.2.3, EVT-M-04, SS-API-01).

    The gate order is the one every Show & Sell write uses, and for the same reasons: the
    event row is the tenancy answer (``unitId`` comes from the row, never from the caller,
    so a cross-Unit event id is ``NOT_FOUND`` — AUTH-U), replay is consulted before the
    version and state guards because the first attempt's own write moved both, the caller's
    version must equal the row just read (``_require_read_version``), and the state must be
    one §3.5 allows an assignment in.

    Two write shapes, decided by that state:

    - ``SCHEDULED``/``ACTIVE``/``ENDED`` write the stock answer — allocation rows, one
      ``EVENT_ASSIGN``/``EVENT_MANUAL_REDUCE`` movement each, a balance version bump, the
      cumulative ``productIds``, and the event version — in one transaction, with the
      concurrent-overlap refusal and the finalization-feasibility preflight both evaluated
      before a single action is staged.
    - ``REOPENED`` writes the admin's inputs only: the draft target map, the cumulative
      ``productIds``, and the version. No allocation, movement, or balance row moves,
      because a reopened event's approved stock answer is the finalization that was
      suspended, and §8.6 gives re-finalization the job of validating and applying what
      was entered meanwhile.

    A batch that changes no allocation still commits its marker and moves the event
    version: the caller asked for a save, and the version is that save's receipt.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    event_id = _resource_id(payload, SHOW_AND_SELL_ID_ARGUMENT)
    expected_version = _expected_version(payload)
    targets = _assignment_targets(payload)

    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    unit_auth.require_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(
        caller_id=caller_id,
        operation=ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
        scope=event_id,
        idempotency_key=key,
    )
    replayed = _replay(runner, keys, fingerprint, ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD, _load_assignment_answer)
    if replayed is not None:
        return replayed

    # After replay for the reason _update_show_and_sell states: this request's own write
    # moved the version, so a retry that re-ran the guard would answer CONFLICT about a
    # request it already completed.
    _require_read_version(event_row, expected_version)
    state = show_and_sell_models.require_editable(event_row)
    reopened = state == show_and_sell_models.STATUS_REOPENED
    campaign_id = str(event_row[show_and_sell_models.UNIT_CAMPAIGN_ID_ATTRIBUTE])
    campaign = unit_campaign_models.load_unit_campaign_or_not_found(campaign_id)
    _require_catalog_products(campaign, [target.product_id for target in targets])
    sections = _assignment_sections(campaign_id, [target.product_id for target in targets])
    now_iso = utc_now_iso()

    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=event_id)
    if reopened:
        product_ids = allocation_models.draft_product_ids(event_row, targets)
        allocation_models.require_finalization_feasible(len(product_ids), MAX_TRANSACTION_ACTIONS)
        plan.add(
            *show_and_sell_models.assignment_draft_action(
                show_and_sell_id=event_id,
                expected_version=expected_version,
                product_ids=product_ids,
                draft=allocation_models.draft_allocation_targets(event_row, targets),
                updated_by_account_id=caller_id,
                updated_at=now_iso,
            )
        )
        changes: List[allocation_models.AllocationChange] = []
    else:
        changes = _plan_live_assignments(event_row, targets, sections, event_id)
        product_ids = allocation_models.planned_product_ids(event_row, changes)
        allocation_models.require_finalization_feasible(len(product_ids), MAX_TRANSACTION_ACTIONS)
        _stage_assignment_writes(
            plan,
            event_row,
            changes,
            sections,
            event_id=event_id,
            product_ids=product_ids,
            expected_version=expected_version,
            caller_id=caller_id,
            idempotency_key=key,
            now_iso=now_iso,
        )

    build_result = _once(lambda: _load_assignment_answer(event_id))
    runner.execute(
        keys,
        plan,
        operation=ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
        fingerprint=fingerprint,
        result_id=event_id,
        load_result=_load_assignment_answer,
        result_payload=build_result,
    )
    answer = build_result()
    log.info(
        "Show & Sell inventory assigned",
        show_and_sell_id=event_id,
        caller_id=caller_id,
        products=len(changes),
        warnings=len(answer["warnings"]),
        draft_only=reopened,
    )
    return answer


# --- Raw allocation read (§3.2.4) ------------------------------------------------


def _allocation_filters(event: Dict[str, Any]) -> Dict[str, Any]:
    """The validated ``eventInventoryAllocations`` filter set."""
    values: Dict[str, Any] = {}
    for name in ("productId", "showAndSellId"):
        raw = _optional_argument(event, name)
        values[name] = None if raw is None else inventory_models.normalize_inventory_id(raw, name)
    raw_status = _optional_argument(event, "status")
    values["status"] = None if raw_status is None else inventory_models.normalize_allocation_status(raw_status)
    return values


def _event_inventory_allocations(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """One campaign's allocation intervals, raw and paginated, with no aggregation (§3.2.4).

    The answer is the rows: ``allocatedQty``/``soldQty``/``releasedQty``/``remainingQty``,
    status, ``version``, and the denormalized interval each row competes on. Assigned,
    unassigned and overage totals are NOT computed here — §9 and AC-36 put that arithmetic
    in the browser over exactly these fields, so a report view and the inventory board
    cannot drift apart by deriving the same number twice, and a saved report keeps
    reconciling after the campaign's stock moves (DATA-Q-03).

    Every filter is part of the cursor scope, so a cursor from a product-filtered page
    cannot walk the campaign's whole allocation set (PAGE-01). The read is the consistent
    campaign partition read rather than a GSI, which is what lets a caller read back the
    rows a mutation just committed and reconcile against them.
    """
    campaign = _campaign_admin_guard(event, caller_id, "unitCampaignId")
    unit_campaign_id = str(campaign["unitCampaignId"])
    filters = _allocation_filters(event)
    rows = inventory_models.campaign_allocation_rows(
        unit_campaign_id,
        product_id=filters["productId"],
        show_and_sell_id=filters["showAndSellId"],
        status=filters["status"],
    )
    token = "#".join("" if filters[name] is None else str(filters[name]) for name in _ALLOCATION_FILTER_ORDER)
    page = dict(
        paginate_page(rows, f"{EVENT_INVENTORY_ALLOCATIONS_FIELD}#{unit_campaign_id}#{token}", _page_argument(event))
    )
    page["items"] = [show_and_sell_models.allocation_payload(row) for row in page["items"]]
    return page


# --- Show & Sell slots (§3.3) ----------------------------------------------------


def _slot_target(payload: Mapping[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    """Which slot this request addresses, and the version the caller read for it.

    A ``slotId`` with no ``slotVersion`` is not a create that happens to carry an
    extra field: it is an edit of a row the caller has already read, and guessing its
    version would make §3.3.2's ``expectedSlotVersion`` requirement decorative
    (VER-01). A ``slotVersion`` with no ``slotId`` is the mirror mistake — a number
    for a row the request never named.
    """
    raw_slot = payload.get("slotId")
    slot_id = None if raw_slot is None else show_and_sell_models.normalize_slot_id(raw_slot)
    expected_slot_version = _read_expected_version(payload, "slotVersion")
    if slot_id is None:
        if expected_slot_version is not None:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "slotVersion is only for an existing slot; omit it when creating one.",
            )
        return None, None
    if expected_slot_version is None:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "slotVersion.expectedVersion is required when updating an existing slot.",
        )
    return slot_id, expected_slot_version


def _slot_offer(event_row: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """The slot this request offers, normalized, and refused if the event cannot hold it.

    Normalized once here so the revalidation, the write, and the fingerprint all
    reason about the same interval and capacity the caller will get back. The bound is
    §5.12's — the slot sits inside the event's immutable interval — and it is decided
    against the event row this request just read, so an interval that cannot hold the
    slot is refused before any write rather than stored and discovered by a signup.
    """
    start_at, end_at = show_and_sell_models.normalize_interval(payload.get("startAt"), payload.get("endAt"))
    capacity = show_and_sell_models.normalize_capacity(payload.get("capacity"))
    bounds = show_and_sell_models.slot_bounds_violations(event_row, start_at, end_at)
    if bounds:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"This slot does not fit the event: {'; '.join(bounds)}.",
            details={"subcode": "SLOT_BOUNDS", "startAt": start_at, "endAt": end_at},
        )
    return {
        "startAt": start_at,
        "endAt": end_at,
        "capacity": capacity,
        "label": show_and_sell_models.normalize_label(payload.get("label")),
    }


def _slot_board(event_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The event's slot rows and its ACTIVE signups, both read consistently.

    Two questions are answered from this one read pair: whether there is room for
    another slot at all, and whether the change keeps every existing signup legal.
    Both come from the event's own partition rather than an index, so the answer is
    the same rows the write conditions on (SEC-06).
    """
    return show_and_sell_models.event_slot_rows(event_id), show_and_sell_models.active_signups(event_id)


def _revalidation_commitments(signups: Sequence[Mapping[str, Any]], slot_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Every commitment held by a Scout signed up for this slot, from the Scout's partition.

    The commitment projection — not the signup row — is what a later signup consults
    before admitting a Scout to an overlapping slot, and it is partitioned by Scout so
    the cross-campaign question (SLOT-04) is one consistent read. Deciding a slot move
    per Unit Campaign would answer "no conflict" about the Scout already working a
    different campaign at that hour.

    One read serves both halves of a slot edit: the revalidation below asks "would this
    new time put one of these Scouts somewhere they already are", and the move below
    asks "which projection has to move because this slot's time changed".
    """
    return {
        profile_id: show_and_sell_models.commitment_rows(profile_id)
        for profile_id in show_and_sell_models.active_signup_profiles(signups, slot_id)
    }


def _refuse_slot_limit(slots: Sequence[Mapping[str, Any]]) -> None:
    """Refuse a 21st slot (§3.3.2's cap) before writing it.

    The cap is counted, not conditioned — DynamoDB has no count condition — and it is
    still race-safe, because the same transaction bumps the event version against the
    caller's ``expectedEventVersion``: two creates read the same 20 slots, and only the
    one holding the current event version commits, so the loser retries against a board
    that now shows 21.
    """
    if len(slots) < show_and_sell_models.MAX_SLOTS_PER_EVENT:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        (
            f"This event already has {len(slots)} slots, and one event may hold at most "
            f"{show_and_sell_models.MAX_SLOTS_PER_EVENT}. Delete a slot that is not in use first."
        ),
        details={"subcode": "SLOT_LIMIT", "slotCount": len(slots), "limit": show_and_sell_models.MAX_SLOTS_PER_EVENT},
    )


def _refuse_slot_revalidation(
    event_row: Mapping[str, Any],
    slot_id: str,
    offer: Mapping[str, Any],
    slots: Sequence[Mapping[str, Any]],
    signups: Sequence[Mapping[str, Any]],
    commitments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """Refuse a slot change that would break a signup that already exists (§3.3.2).

    The rules and their sentences come from the model, so a signup write later decides
    "is this Scout free at that time" the same way (§3.4), and the refusal names the
    real Scout, slot, and event the change collides with rather than a count.
    """
    violations = show_and_sell_models.slot_revalidation_violations(
        show_and_sell_id=str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]),
        slot_id=slot_id,
        start_at=str(offer["startAt"]),
        end_at=str(offer["endAt"]),
        capacity=int(offer["capacity"]),
        slots=slots,
        signups=signups,
        commitments_by_profile=commitments,
    )
    if not violations:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        f"This slot change would break an existing signup: {'; '.join(violations)}. Nothing was written.",
        details={"subcode": "SLOT_REVALIDATION", "slotId": slot_id, "violations": violations},
    )


def _slot_commitment(commitments: Sequence[Mapping[str, Any]], event_id: str, slot_id: str) -> Optional[Dict[str, Any]]:
    """The Scout's ACTIVE projection for this slot, when the aggregate holds one.

    A signup with no projection is a broken aggregate, not something this write repairs:
    inventing a row would need a version to condition on, and the projection's version is
    its source signup's, which is exactly the agreement §3.7's validation exists to check.
    """
    for row in commitments:
        if (
            str(row.get(show_and_sell_models.STATUS_ATTRIBUTE) or "") == show_and_sell_models.SIGNUP_ACTIVE
            and str(row.get(show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE) or "") == event_id
            and str(row.get(show_and_sell_models.SLOT_ID_ATTRIBUTE) or "") == slot_id
        ):
            return dict(row)
    return None


def _commitment_moves(
    *,
    event_row: Mapping[str, Any],
    slot_id: str,
    signups: Sequence[Mapping[str, Any]],
    commitments: Mapping[str, Sequence[Mapping[str, Any]]],
    offer: Mapping[str, Any],
    now_iso: str,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """``(stale row, replacement row)`` for every Scout whose slot moved through time.

    A commitment's sort key IS its interval (§6.2), so an event-bounded time change moves
    the projection rather than editing it. Leaving it where it was would be the worse
    answer: the cross-campaign overlap rule (SLOT-04) reads that row, so a later signup
    would be refused for hours nobody is working any more and admitted beside a Scout who
    is now working them — AC-14's "no overlapping commitments at the same or different
    Show & Sells" is decided against the projection, so §3.3 keeps it truthful in the same
    transaction that moved the slot.

    The version rides unchanged: §5.13 defines the projection's version as its source
    signup's, and the signup did not move. Each affected Scout's commitment guard still
    increments, because the commitment changed — and that is what makes a signup planned
    against the old guard fail rather than commit beside a board that moved under it.
    """
    event_id = str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE])
    unit_campaign_id = str(event_row[show_and_sell_models.UNIT_CAMPAIGN_ID_ATTRIBUTE])
    moves: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for profile_id in show_and_sell_models.active_signup_profiles(signups, slot_id):
        stale = _slot_commitment(commitments.get(profile_id, ()), event_id, slot_id)
        if stale is None or _interval_matches(stale, offer):
            continue
        moves.append(
            (
                stale,
                show_and_sell_models.build_scout_commitment_item(
                    profile_id=profile_id,
                    unit_campaign_id=unit_campaign_id,
                    show_and_sell_id=event_id,
                    slot_id=slot_id,
                    start_at=offer["startAt"],
                    end_at=offer["endAt"],
                    now_iso=now_iso,
                    version=show_and_sell_models.normalize_required_version(
                        stale.get(show_and_sell_models.VERSION_ATTRIBUTE, 1)
                    ),
                    status=str(stale.get(show_and_sell_models.STATUS_ATTRIBUTE) or show_and_sell_models.SIGNUP_ACTIVE),
                ),
            )
        )
    return moves


def _interval_matches(stale: Mapping[str, Any], offer: Mapping[str, Any]) -> bool:
    """Whether the projection already describes the offered interval.

    A slot edit that only changes a label or a capacity moves no commitment, and staging
    a delete-and-put pair for a row that is not moving would spend two transaction actions
    and a guard bump on a row that cannot change.
    """
    return bool(
        str(stale.get(show_and_sell_models.START_AT_ATTRIBUTE) or "") == str(offer["startAt"])
        and str(stale.get(show_and_sell_models.END_AT_ATTRIBUTE) or "") == str(offer["endAt"])
    )


def _refuse_oversized_slot_move(moves: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
    """Refuse a time change whose commitment moves cannot fit one transaction.

    The move is atomic or it does not happen: a slot at its new time beside stale
    commitments is the exact disagreement AC-14 exists to prevent, so the plan is never
    split. The pair plus the guard is three actions per Scout inside the plan's 90-action
    ceiling, and the refusal says so and points at §3.4's cancellation as the way to free
    room.
    """
    actions = 3 * len(moves) + 3
    if actions <= MAX_TRANSACTION_ACTIONS:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        (
            f"This slot has {len(moves)} active signup(s), and moving its time re-commits each of them; "
            f"that is more than one transaction can carry ({MAX_TRANSACTION_ACTIONS} writes). Cancel the "
            "signups first, then move the slot."
        ),
        details={"subcode": "SLOT_MOVE_TOO_LARGE", "signupCount": len(moves), "maxActions": MAX_TRANSACTION_ACTIONS},
    )


def _stage_slot_writes(
    plan: Any,
    runner: Any,
    *,
    keys: Any,
    fingerprint: str,
    slot_id: str,
    existing: Optional[Mapping[str, Any]],
    event_row: Mapping[str, Any],
    offer: Mapping[str, Any],
    caller_id: str,
    expected_event_version: int,
    expected_slot_version: Optional[int],
    moves: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    now_iso: str,
) -> None:
    """Stage the whole slot change: marker, slot row, the commitments the move carries, event version.

    One plan, one commit. The marker goes first (API contract §8.9) so a replay can never
    be answered for a write that did not happen, and the event version goes last so every
    concurrent slot write on this event settles against one serialization point.
    """
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=slot_id)
    if existing is None:
        plan.add(
            *show_and_sell_models.put_slot_action(
                show_and_sell_models.build_show_and_sell_slot_item(
                    event=event_row,
                    slot_id=slot_id,
                    start_at=offer["startAt"],
                    end_at=offer["endAt"],
                    capacity=offer["capacity"],
                    label=offer["label"],
                    now_iso=now_iso,
                )
            )
        )
    else:
        plan.add(
            *show_and_sell_models.update_slot_action(
                show_and_sell_id=str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]),
                slot_id=slot_id,
                expected_version=cast(int, expected_slot_version),
                label=offer["label"],
                start_at=offer["startAt"],
                end_at=offer["endAt"],
                capacity=offer["capacity"],
                updated_at=now_iso,
            )
        )
    for stale, replacement in moves:
        plan.add(*show_and_sell_models.move_commitment_action(commitment=stale))
        plan.add(*show_and_sell_models.put_commitment_action(item=replacement))
    for profile_id in sorted({str(stale.get(show_and_sell_models.PROFILE_ID_ATTRIBUTE) or "") for stale, _ in moves}):
        plan.add(*show_and_sell_models.bump_commitment_guard_action(profile_id=profile_id, updated_at=now_iso))
    plan.add(
        *show_and_sell_models.bump_event_version_action(
            show_and_sell_id=str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]),
            expected_version=expected_event_version,
            updated_by_account_id=caller_id,
            updated_at=now_iso,
        )
    )


def _load_slot_answer(event_id: str, stored_slot_id: str) -> Dict[str, Any]:
    """Rebuild one slot answer from the stored row, for a replay or a post-write read."""
    return dict(
        show_and_sell_models.slot_admin_payload(show_and_sell_models.load_slot_or_not_found(event_id, stored_slot_id))
    )


def _upsert_show_and_sell_slot(event: Dict[str, Any], caller_id: str) -> Dict[str, Any]:
    """Create or edit one slot of an event (§3.3.2, SLOT-M-01).

    One request, one versioned write plan: the marker, the slot row, and the event
    version bump commit together or not at all. The three guards run in the order that
    keeps each honest:

    - Replay first, because the first attempt's own write moved both versions and a
      retry that re-ran a version guard would answer ``CONFLICT`` about a request it
      already completed.
    - Then the event's version and its state, then the slot's own version. §3.3 allows
      slot writes only while the event is ``SCHEDULED`` — after the start its slots are
      facts the Scouts already worked against — and ``REOPENED`` is refused too, because
      what a reopened event edits is the finalization draft, not the shift board.
    - Then the bounds, the 20-slot cap, and the existing-signup revalidation, before
      anything is staged.

    A create carries no ``slotId`` and no ``slotVersion``; the id is the server's, and
    the conditional insert is the duplicate guard. An update carries both, and its
    version condition is what makes the state check apply to the row the caller read.
    The capacity floor is checked twice on purpose: against the counter this request
    read, and as a condition on the write itself, which catches a signup that moved the
    counter between the read and the commit without touching the version the caller
    sent.

    A slot whose time actually changed also carries its signups' commitment projections
    to the new interval — the projection's key IS its interval, so leaving it behind
    would answer the next cross-campaign overlap question about hours nobody works
    (AC-14). That move is part of this one plan, guard bumps included, and a re-time with
    more signups than one transaction can hold is refused rather than split.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    event_id = _resource_id(payload, show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE)
    expected_event_version = _expected_version(payload)
    slot_id, expected_slot_version = _slot_target(payload)

    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    unit_auth.require_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(caller_id=caller_id, operation=UPSERT_SLOT_FIELD, scope=event_id, idempotency_key=key)
    replayed = _replay(runner, keys, fingerprint, UPSERT_SLOT_FIELD, lambda stored: _load_slot_answer(event_id, stored))
    if replayed is not None:
        return replayed

    # After replay for the reason the docstring names: the completed attempt moved the
    # event version and, for an update, the slot's too.
    _require_read_version(event_row, expected_event_version)
    show_and_sell_models.require_slots_writable(event_row)
    offer = _slot_offer(event_row, payload)
    slots, signups = _slot_board(event_id)

    existing: Optional[Dict[str, Any]] = None
    if slot_id is None:
        _refuse_slot_limit(slots)
        slot_id = show_and_sell_models.new_slot_id()
    else:
        existing = show_and_sell_models.load_slot_or_not_found(event_id, slot_id)
        _require_read_version(existing, cast(int, expected_slot_version), noun="slot")
    commitments = _revalidation_commitments(signups, slot_id)
    _refuse_slot_revalidation(event_row, slot_id, offer, slots, signups, commitments)

    now_iso = utc_now_iso()
    moves = _commitment_moves(
        event_row=event_row, slot_id=slot_id, signups=signups, commitments=commitments, offer=offer, now_iso=now_iso
    )
    _refuse_oversized_slot_move(moves)

    plan = WritePlan()
    _stage_slot_writes(
        plan,
        runner,
        keys=keys,
        fingerprint=fingerprint,
        slot_id=slot_id,
        existing=existing,
        event_row=event_row,
        offer=offer,
        caller_id=caller_id,
        expected_event_version=expected_event_version,
        expected_slot_version=expected_slot_version,
        moves=moves,
        now_iso=now_iso,
    )

    build_result = _once(lambda: _load_slot_answer(event_id, slot_id))
    runner.execute(
        keys,
        plan,
        operation=UPSERT_SLOT_FIELD,
        fingerprint=fingerprint,
        result_id=slot_id,
        load_result=lambda stored: _load_slot_answer(event_id, stored),
        result_payload=build_result,
    )
    answer = build_result()
    log.info(
        "Show & Sell slot upserted",
        show_and_sell_id=event_id,
        slot_id=slot_id,
        caller_id=caller_id,
        version=answer["version"],
        created=existing is None,
        commitments_moved=len(moves),
    )
    return answer


def _refuse_deleting_a_held_slot(
    event_row: Mapping[str, Any], slot_id: str, signups: Sequence[Mapping[str, Any]]
) -> None:
    """Refuse a deletion that would drop a participant (§3.3.3, SLOT-M-02-02).

    A signup is a Scout's place in a slot, and cancelling one is its own mutation with
    its own audit and its own commitment release (§3.4). Deleting a slot that holds
    Scouts would cancel them without either, leaving signup rows pointing at a slot that
    no longer exists.

    The count is the signup ROWS, not the slot's ``activeSignupCount``: §5.13's rows are
    the participants and the counter is the projection kept for the board's arithmetic, so
    a guard decided on the counter would delete a slot beside the Scouts it holds the
    moment that counter drifted. The write conditions on the counter anyway
    (``#activeSignupCount = :zero``), and that is what catches the opposite drift — a
    signup that landed between this read and the commit — cancelling the plan instead of
    dropping the Scout who just signed up.
    """
    held = len(show_and_sell_models.active_slot_signups(signups, slot_id))
    if held == 0:
        return
    raise AppError(
        ErrorCode.CONFLICT,
        (
            f"This slot has {held} active signup(s). Cancel the signups before deleting the slot; "
            "deleting it would drop those Scouts without a cancellation of their own."
        ),
        details={
            "subcode": "SLOT_HAS_SIGNUPS",
            "showAndSellId": str(event_row[show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE]),
            "slotId": slot_id,
            "activeSignupCount": held,
        },
    )


def _delete_show_and_sell_slot(event: Dict[str, Any], caller_id: str) -> bool:
    """Delete one unused slot (§3.3.3, SLOT-M-02).

    The parent id is part of the key, which is what makes the wrong-parent case a key
    fact rather than a comparison: a slot id from another event has no row under this
    event's partition, so the answer is ``NOT_FOUND`` — the same answer as for a slot
    that never existed. The caller's version is the event's, because that is the number
    the schedule screen holds, and the slot row's own version comes from the consistent
    read this request just made: either one moving means the plan writes nothing.

    The event version bumps with the delete, so a caller holding the version from
    before the delete cannot then finalize or cancel against a slot set it never saw.
    """
    log = get_logger(__name__)
    payload = _require_input(event)
    key = _idempotency_key(payload)
    fingerprint = _fingerprint(payload)
    event_id = _resource_id(payload, show_and_sell_models.SHOW_AND_SELL_ID_ATTRIBUTE)
    slot_id = show_and_sell_models.normalize_slot_id(payload.get("slotId"))
    expected_event_version = _expected_version(payload)

    event_row = show_and_sell_models.load_show_and_sell_or_not_found(event_id)
    unit_auth.require_unit_admin(caller_id, str(event_row[show_and_sell_models.UNIT_ID_ATTRIBUTE]))

    runner = IdempotentMutationRunner()
    keys = _show_and_sell_marker(caller_id=caller_id, operation=DELETE_SLOT_FIELD, scope=event_id, idempotency_key=key)
    replayed = _replay(runner, keys, fingerprint, DELETE_SLOT_FIELD, lambda stored: True)
    if replayed is not None:
        return True

    _require_read_version(event_row, expected_event_version)
    show_and_sell_models.require_slots_writable(event_row)
    slot_row = show_and_sell_models.load_slot_or_not_found(event_id, slot_id)
    _refuse_deleting_a_held_slot(event_row, slot_id, show_and_sell_models.active_signups(event_id))

    now_iso = utc_now_iso()
    plan = WritePlan()
    runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id=slot_id)
    plan.add(
        *show_and_sell_models.delete_slot_action(
            show_and_sell_id=event_id,
            slot_id=slot_id,
            expected_version=show_and_sell_models.normalize_required_version(slot_row.get("version", 1)),
        )
    )
    plan.add(
        *show_and_sell_models.bump_event_version_action(
            show_and_sell_id=event_id,
            expected_version=expected_event_version,
            updated_by_account_id=caller_id,
            updated_at=now_iso,
        )
    )
    runner.execute(
        keys,
        plan,
        operation=DELETE_SLOT_FIELD,
        fingerprint=fingerprint,
        result_id=slot_id,
        load_result=lambda stored: True,
        result_payload=lambda: True,
    )
    log.info("Show & Sell slot deleted", show_and_sell_id=event_id, slot_id=slot_id, caller_id=caller_id)
    return True


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
    CREATE_UNIT_CAMPAIGN_FIELD: _create_campaign,
    UPDATE_UNIT_CAMPAIGN_FIELD: _update_campaign,
    JOIN_PREVIEW_FIELD: _join_info,
    JOIN_UNIT_CAMPAIGN_FIELD: _join_campaign,
    REMOVE_MEMBERSHIP_FIELD: _remove_membership,
    UNIT_CAMPAIGN_FIELD: _get_campaign,
    UNIT_CAMPAIGNS_FIELD: _list_campaigns,
    UNIT_CAMPAIGN_CATALOG_FIELD: _campaign_catalog,
    UNIT_CAMPAIGN_ROSTER_FIELD: _list_roster,
    RECORD_RECEIPT_FIELD: _record_receipt,
    ADJUST_INVENTORY_FIELD: _adjust_inventory,
    ADJUST_COUNCIL_FIELD: _adjust_council,
    INVENTORY_POSITIONS_FIELD: _inventory_positions,
    INVENTORY_MOVEMENTS_FIELD: _inventory_movements,
    ISSUE_STOCK_FIELD: _issue_stock,
    RETURN_STOCK_FIELD: _return_stock,
    SCOUT_CUSTODY_FIELD: _scout_custody_balances,
    MY_SCOUT_CUSTODY_FIELD: _my_scout_custody,
    FULFILL_LINE_FIELD: _fulfill_line,
    REVERSE_FULFILLMENT_FIELD: _reverse_fulfillment,
    ORDER_FULFILLMENTS_FIELD: _order_fulfillments,
    UNIT_SCOUT_ORDERS_FIELD: _unit_scout_campaign_orders,
    CREATE_SHOW_AND_SELL_FIELD: _create_show_and_sell,
    UPDATE_SHOW_AND_SELL_FIELD: _update_show_and_sell,
    CANCEL_SHOW_AND_SELL_FIELD: _cancel_show_and_sell,
    SHOW_AND_SELL_FIELD: _show_and_sell,
    SHOW_AND_SELLS_FIELD: _show_and_sells,
    UNIT_CAMPAIGN_OPPORTUNITIES_FIELD: _unit_campaign_opportunities,
    SHOW_AND_SELL_OPPORTUNITY_FIELD: _show_and_sell_opportunity,
    ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD: _assign_show_and_sell_inventory,
    EVENT_INVENTORY_ALLOCATIONS_FIELD: _event_inventory_allocations,
    UPSERT_SLOT_FIELD: _upsert_show_and_sell_slot,
    DELETE_SLOT_FIELD: _delete_show_and_sell_slot,
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
