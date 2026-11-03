"""Lambda resolver for Show & Sell Unit operations (batch A)."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

try:  # pragma: no cover
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.import_fallback import import_from_utils

get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
try:
    from utils.mutations import WritePlan, marker_keys, normalized_fingerprint
except ModuleNotFoundError:
    from ..utils.mutations import WritePlan, marker_keys, normalized_fingerprint

AppError, ErrorCode = import_from_utils("errors", "AppError", "ErrorCode")
with_error_handling = import_from_utils("handlers", "lambda_handler")
get_logger = import_from_utils("logging", "get_logger")
# mutations optional
try:
    from utils.mutations import IdempotentMutationRunner
except ModuleNotFoundError:
    from ..utils.mutations import IdempotentMutationRunner

if TYPE_CHECKING:  # pragma: no cover
    pass


def _serialize(value):
    from boto3.dynamodb.types import TypeSerializer

    return TypeSerializer().serialize(value)


logger = get_logger(__name__)
_ts = None
VALID_SPLIT = {"EQUAL", "TIME_WORKED"}
VALID_BASIS = {"PHYSICAL_STOCK", "AFTER_ASSIGNMENTS"}


def _units():
    return tables.units


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_unit(unit_id: str):
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    return resp.get("Item")


def _unit_pk(unit_id: str) -> str:
    return f"UNIT#{unit_id}"


def _validate_timezone(tz: str) -> bool:
    if tz == "UTC":
        return True
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _metadata_key(unit_type, unit_number, city, state) -> str:
    return f"{unit_type}#{unit_number}#{city}#{state}".lower()


def _is_unit_admin(caller_id: str, unit_id: str) -> bool:
    try:
        resp = _units().get_item(Key={"pk": f"UNIT#{unit_id}", "sk": f"GRANT#{caller_id}"}, ConsistentRead=True)
    except Exception:
        return False
    return resp.get("Item") is not None


def create_unit(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity is required")
    unit_type = args.get("unitType")
    unit_number = args.get("unitNumber")
    try:
        from decimal import Decimal

        if isinstance(unit_number, Decimal):
            unit_number = int(unit_number)
    except Exception:
        pass
    city = args.get("city")
    if isinstance(city, str):
        city = city.strip()
    state = args.get("state")
    timezone_ = args.get("timezone")
    if not (unit_type and unit_number is not None and city and state and timezone_):
        raise AppError(ErrorCode.INVALID_INPUT, "Missing required unit fields")
    if not _validate_timezone(timezone_):
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid timezone")
    split_default = args.get("splitDefault") or "EQUAL"
    if split_default not in VALID_SPLIT:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid splitDefault")
    council = args.get("councilNeedBasis") or "PHYSICAL_STOCK"
    if council not in VALID_BASIS:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid councilNeedBasis")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    runner = IdempotentMutationRunner()
    mk = marker_keys(
        actor_id=caller,
        operation="createUnit",
        scope="BOOTSTRAP",
        idempotency_key=key,
        table_key="units",
        table_name=_units().name if hasattr(_units(), "name") else "units",
    )
    fp = normalized_fingerprint(
        {
            "unitType": unit_type,
            "unitNumber": int(unit_number) if unit_number is not None else None,
            "city": city,
            "state": state,
        },
        drop_none=True,
    )
    existing_marker = runner.load_marker(mk)
    if existing_marker:
        handled, replayed = runner.replay_or_reject(
            mk,
            fp,
            operation="createUnit",
            load_result=lambda r: {
                "unit": _get_unit(r),
                "grant": _units()
                .get_item(Key={"pk": _unit_pk(r), "sk": f"GRANT#{caller}"}, ConsistentRead=True)
                .get("Item"),
            },
        )
        if handled:
            return replayed
    duplicate_confirmed = bool(args.get("duplicateConfirmed", False))
    md_key = _metadata_key(unit_type, unit_number, city, state)
    try:
        resp = _units().query(
            IndexName="metadataKey-createdAt-index",
            KeyConditionExpression="metadataKey = :m",
            ExpressionAttributeValues={":m": md_key},
        )
        existing = resp.get("Items", [])
    except Exception:
        existing = []
    if existing and not duplicate_confirmed:
        raise AppError(ErrorCode.CONFLICT, "Exact metadata match requires duplicateConfirmed")
    unit_id = str(uuid.uuid4())
    now = _now()
    display = args.get("displayName") or f"{unit_type} {unit_number} - {city}, {state}"
    item = {
        "pk": _unit_pk(unit_id),
        "sk": "METADATA",
        "unitId": unit_id,
        "unitType": unit_type,
        "unitNumber": unit_number,
        "city": city,
        "state": state,
        "displayName": display,
        "metadataKey": md_key,
        "timezone": timezone_,
        "splitDefault": split_default,
        "councilNeedBasis": council,
        "adminCount": 1,
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
        "createdByAccountId": caller,
    }
    grant_item = {
        "pk": _unit_pk(unit_id),
        "sk": f"GRANT#{caller}",
        "unitId": unit_id,
        "accountId": caller,
        "role": "UNIT_ADMIN",
        "createdByAccountId": caller,
        "createdAt": now,
    }
    runner = IdempotentMutationRunner()
    mk = marker_keys(
        actor_id=caller,
        operation="createUnit",
        scope="BOOTSTRAP",
        idempotency_key=key,
        table_key="units",
        table_name=_units().name if hasattr(_units(), "name") else "units",
    )
    fp = normalized_fingerprint(
        {
            "unitType": unit_type,
            "unitNumber": int(unit_number) if unit_number is not None else None,
            "city": city,
            "state": state,
        },
        drop_none=True,
    )
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in item.items()}})
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in grant_item.items()}})
    runner.execute(
        mk,
        plan,
        operation="createUnit",
        fingerprint=fp,
        result_id=unit_id,
        load_result=lambda rid: {
            "unit": _get_unit(rid),
            "grant": _units()
            .get_item(Key={"pk": _unit_pk(rid), "sk": f"GRANT#{caller}"}, ConsistentRead=True)
            .get("Item"),
        },
    )
    return {"unit": item, "grant": grant_item}


def update_unit(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    if not unit_id:
        raise AppError(ErrorCode.INVALID_INPUT, "unitId is required")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    runner = IdempotentMutationRunner()
    mk = marker_keys(
        actor_id=caller,
        operation="updateUnit",
        scope=unit_id,
        idempotency_key=key,
        table_key="units",
        table_name=_units().name if hasattr(_units(), "name") else "units",
    )
    fp = normalized_fingerprint(args)
    existing = runner.load_marker(mk)
    if existing:
        rid = (
            existing.get("resultId", {}).get("S")
            if isinstance(existing.get("resultId"), dict)
            else existing.get("resultId")
        )
        return _get_unit(rid) if rid else _get_unit(unit_id)
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "Unit not found")
    version_input = args.get("version", {}) or {}
    expected = version_input.get("expectedVersion")
    if expected is None:
        expected = args.get("expectedVersion")
    if expected is not None and int(expected) != int(item.get("version", 0)):
        raise AppError(ErrorCode.CONFLICT, "Version mismatch")
    # apply updates
    for f in ("unitType", "unitNumber", "city", "state", "displayName", "timezone", "splitDefault", "councilNeedBasis"):
        if args.get(f) is not None:
            item[f] = args[f]
    item["version"] = int(item.get("version", 0)) + 1
    item["updatedAt"] = _now()
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in item.items()}})
    try:
        runner.execute(
            mk, plan, operation="updateUnit", fingerprint=fp, result_id=unit_id, load_result=lambda rid: _get_unit(rid)
        )
    except Exception:
        _units().put_item(Item=item)
    return item


def revoke_unit_access_grant(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    account_id = args.get("accountId")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    runner = IdempotentMutationRunner()
    mk = marker_keys(
        actor_id=caller,
        operation="revokeUnitAccessGrant",
        scope=f"{unit_id}#{account_id}",
        idempotency_key=key,
        table_key="units",
        table_name=_units().name if hasattr(_units(), "name") else "units",
    )
    fp = normalized_fingerprint({"unitId": unit_id, "accountId": account_id})
    existing = runner.load_marker(mk)
    if existing:
        rid = (
            existing.get("resultId", {}).get("S")
            if isinstance(existing.get("resultId"), dict)
            else existing.get("resultId")
        )
        return _get_unit(rid) if rid else _get_unit(unit_id)
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "Unit not found")
    if int(item.get("adminCount", 0)) <= 1:
        raise AppError(ErrorCode.CONFLICT, "Cannot revoke last admin")
    # delete grant
    _units().delete_item(Key={"pk": _unit_pk(unit_id), "sk": f"GRANT#{account_id}"})
    item["adminCount"] = int(item["adminCount"]) - 1
    item["version"] = int(item.get("version", 0)) + 1
    item["updatedAt"] = _now()
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in item.items()}})
    try:
        runner.execute(
            mk,
            plan,
            operation="revokeUnitAccessGrant",
            fingerprint=fp,
            result_id=unit_id,
            load_result=lambda rid: _get_unit(rid),
        )
    except Exception:
        _units().put_item(Item=item)
    return item


def create_unit_invite(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    code = uuid.uuid4().hex[:16].upper()
    now = _now()
    # expiry 14 days
    from datetime import timedelta

    expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    expires_epoch = int((datetime.now(timezone.utc) + timedelta(days=14)).timestamp())
    item = {
        "pk": f"INVITE#{code}",
        "sk": f"UNIT#{unit_id}",
        "inviteCode": code,
        "unitId": unit_id,
        "createdByAccountId": caller,
        "createdAt": now,
        "expiresAt": expires,
        "expiresAtEpoch": expires_epoch,
    }
    _units().put_item(Item=item)
    return item


def revoke_unit_invite(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    code = args.get("inviteCode")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    _units().delete_item(Key={"pk": f"INVITE#{code}", "sk": f"UNIT#{unit_id}"})
    return True


def redeem_unit_invite(event, context):
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity required")
    code = args.get("inviteCode")
    resp = (
        _units().get_item(
            Key={"pk": f"INVITE#{code}", "sk": None} if False else {"pk": f"INVITE#{code}"}, ConsistentRead=True
        )
        if False
        else None
    )
    # query by pk prefix
    try:
        resp = _units().query(
            KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"INVITE#{code}"}, ConsistentRead=True
        )
    except Exception:
        resp = _units().query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"INVITE#{code}"})
    items = resp.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    inv = items[0]
    unit_id = inv["unitId"]
    # expiry check
    from datetime import datetime as dt

    try:
        exp = dt.fromisoformat(inv["expiresAt"].replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    except AppError:
        raise
    except Exception:
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    # create grant
    now = _now()
    grant_item = {
        "pk": _unit_pk(unit_id),
        "sk": f"GRANT#{caller}",
        "unitId": unit_id,
        "accountId": caller,
        "role": "UNIT_ADMIN",
        "createdByAccountId": inv.get("createdByAccountId", caller),
        "createdAt": now,
    }
    _units().put_item(Item=grant_item)
    # delete invite
    _units().delete_item(Key={"pk": f"INVITE#{code}", "sk": inv["sk"]})
    # increment adminCount
    meta = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True).get("Item")
    if meta:
        meta["adminCount"] = int(meta.get("adminCount", 1)) + 1
        meta["version"] = int(meta.get("version", 0)) + 1
        meta["updatedAt"] = _now()
        _units().put_item(Item=meta)
    return grant_item


def my_units(event, context):
    caller = get_caller_id(event)
    # query GSI accountId-unitId-index
    try:
        resp = _units().query(
            IndexName="accountId-unitId-index",
            KeyConditionExpression="accountId = :a",
            ExpressionAttributeValues={":a": caller},
        )
    except Exception:
        resp = {"Items": []}
    grants = resp.get("Items", [])
    units = []
    for g in grants:
        uid = g.get("unitId")
        if not uid:
            continue
        meta = _units().get_item(Key={"pk": _unit_pk(uid), "sk": "METADATA"}, ConsistentRead=True).get("Item")
        if meta:
            units.append(meta)
    return {"items": units, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def unit(event, context):
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        return None
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    return resp.get("Item")


def unit_admins(event, context):
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    resp = _units().query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": _unit_pk(unit_id), ":sk": "GRANT#"},
    )
    items = resp.get("Items", [])
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def unit_invites(event, context):
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    # query GSI unitId-createdAt-index (sparse)
    try:
        resp = _units().query(
            IndexName="unitId-createdAt-index",
            KeyConditionExpression="unitId = :u",
            ExpressionAttributeValues={":u": unit_id},
        )
    except Exception:
        resp = {"Items": []}
    return {"items": resp.get("Items", []), "pageInfo": {"endCursor": None, "hasNextPage": False}}


_HANDLERS = {
    "createUnit": create_unit,
    "updateUnit": update_unit,
    "revokeUnitAccessGrant": revoke_unit_access_grant,
    "createUnitInvite": create_unit_invite,
    "revokeUnitInvite": revoke_unit_invite,
    "redeemUnitInvite": redeem_unit_invite,
    "myUnits": my_units,
    "unit": unit,
    "unitAdmins": unit_admins,
    "unitInvites": unit_invites,
}


@with_error_handling(error_message="Failed to execute unit operation")
def lambda_handler(event, context):
    field = event.get("info", {}).get("fieldName", "")
    handler = _HANDLERS.get(field)
    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown unit operation: {field}")
    return handler(event, context)
