"""Lambda resolver for Show & Sell Unit operations (batch A)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import BotoCoreError, ClientError

try:  # pragma: no cover
    from utils.import_fallback import import_from_utils
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.import_fallback import import_from_utils

get_caller_id = import_from_utils("appsync_types", "get_caller_id")
tables = import_from_utils("dynamodb", "tables")
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


def _serialize(value: Any) -> Any:
    from boto3.dynamodb.types import TypeSerializer

    return TypeSerializer().serialize(value)


logger = get_logger(__name__)
VALID_SPLIT = {"EQUAL", "TIME_WORKED"}
VALID_BASIS = {"PHYSICAL_STOCK", "AFTER_ASSIGNMENTS"}

# Unit administration caps (API contract: createUnitInvite allows at most 20
# active unused invites; data model §6.6: 10 failed redemption attempts per
# UTC hour, attempt 11 is RATE_LIMIT_EXCEEDED).
_MAX_ACTIVE_INVITES = 20
_FAILURE_WINDOW_LIMIT = 10
_FAILURE_WINDOW_HOURS = 2


def _units() -> Any:
    return tables.units


def _throttles() -> Any:
    return tables.public_order_throttles


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_unit(unit_id: str) -> Any:
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    return resp.get("Item")


def _unit_pk(unit_id: Any) -> str:
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


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _metadata_key(unit_type: Any, unit_number: Any, city: Any, state: Any) -> str:
    return f"{_trim(unit_type)}#{unit_number}#{_trim(city)}#{_trim(state)}".lower()


def _is_unit_admin(caller_id: Any, unit_id: Any) -> bool:
    try:
        resp = _units().get_item(Key={"pk": f"UNIT#{unit_id}", "sk": f"GRANT#{caller_id}"}, ConsistentRead=True)
    except Exception:
        return False
    return resp.get("Item") is not None


def _marker_keys(actor: Any, operation: str, scope: Any, key: str) -> Any:
    return marker_keys(
        actor_id=actor,
        operation=operation,
        scope=scope,
        idempotency_key=key,
        table_key="units",
        table_name=_units().name if hasattr(_units(), "name") else "units",
    )


def create_unit(event: Dict[str, Any], context: Any) -> Any:
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
    mk = _marker_keys(caller, "createUnit", "BOOTSTRAP", key)
    fp = normalized_fingerprint(
        {
            "unitType": unit_type,
            "unitNumber": int(unit_number) if unit_number is not None else None,
            "city": city,
            "state": state,
        },
        drop_none=True,
    )

    def load_bootstrap_result(rid: str) -> Dict[str, Any]:
        return {
            "unit": _get_unit(rid),
            "grant": _units()
            .get_item(Key={"pk": _unit_pk(rid), "sk": f"GRANT#{caller}"}, ConsistentRead=True)
            .get("Item"),
        }

    handled, replayed = runner.replay_or_reject(mk, fp, operation="createUnit", load_result=load_bootstrap_result)
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
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in item.items()}})
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in grant_item.items()}})
    try:
        exec_result = runner.execute(
            mk,
            plan,
            operation="createUnit",
            fingerprint=fp,
            result_id=unit_id,
            load_result=load_bootstrap_result,
        )
    except AppError as exc:
        if not isinstance(exc.__cause__, BotoCoreError):
            raise
        _units().put_item(Item=item)
        _units().put_item(Item=grant_item)
        exec_result = None
    if isinstance(exec_result, dict):
        return exec_result
    return {"unit": item, "grant": grant_item}


def update_unit(event: Dict[str, Any], context: Any) -> Any:
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    if not unit_id:
        raise AppError(ErrorCode.INVALID_INPUT, "unitId is required")
    try:
        from decimal import Decimal

        if isinstance(args.get("unitNumber"), Decimal):
            args["unitNumber"] = int(args["unitNumber"])
    except Exception:
        pass
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "updateUnit", unit_id, key)
    fp = normalized_fingerprint(
        {k: v for k, v in args.items() if k not in ("idempotency", "version", "expectedVersion")}
    )
    handled, replayed = runner.replay_or_reject(mk, fp, operation="updateUnit", load_result=lambda rid: _get_unit(rid))
    if handled:
        return replayed
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
    # settings validation
    if args.get("timezone") is not None and not _validate_timezone(args["timezone"]):
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid timezone")
    if args.get("splitDefault") is not None and args["splitDefault"] not in VALID_SPLIT:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid splitDefault")
    if args.get("councilNeedBasis") is not None and args["councilNeedBasis"] not in VALID_BASIS:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid councilNeedBasis")
    # duplicate check
    new_type = item.get("unitType") if args.get("unitType") is None else args.get("unitType")
    new_number = item.get("unitNumber") if args.get("unitNumber") is None else args.get("unitNumber")
    new_city = item.get("city") if args.get("city") is None else args.get("city")
    new_state = item.get("state") if args.get("state") is None else args.get("state")
    if isinstance(new_city, str):
        new_city = new_city.strip()
    md_key = _metadata_key(new_type, new_number, new_city, new_state)
    duplicate_confirmed = bool(args.get("duplicateConfirmed", False))
    if md_key != item.get("metadataKey"):
        try:
            resp = _units().query(
                IndexName="metadataKey-createdAt-index",
                KeyConditionExpression="metadataKey = :m",
                ExpressionAttributeValues={":m": md_key},
            )
            existing = [x for x in resp.get("Items", []) if x.get("unitId") != unit_id]
        except Exception:
            existing = []
        if existing and not duplicate_confirmed:
            raise AppError(ErrorCode.CONFLICT, "Exact metadata match requires duplicateConfirmed")
    # apply updates
    snapshot_version = int(item.get("version", 0))
    for f in ("unitType", "unitNumber", "city", "state", "displayName", "timezone", "splitDefault", "councilNeedBasis"):
        if args.get(f) is not None:
            item[f] = args[f]
    item["metadataKey"] = md_key
    item["version"] = snapshot_version + 1
    item["updatedAt"] = _now()
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add(
        "Put",
        {
            "TableName": _units().name,
            "Item": {k: _serialize(v) for k, v in item.items()},
            "ConditionExpression": "#v = :v",
            "ExpressionAttributeNames": {"#v": "version"},
            "ExpressionAttributeValues": {":v": _serialize(snapshot_version)},
        },
    )
    try:
        runner.execute(
            mk,
            plan,
            operation="updateUnit",
            fingerprint=fp,
            result_id=unit_id,
            load_result=lambda rid: _get_unit(rid),
        )
        return item
    except AppError as exc:
        if not isinstance(exc.__cause__, BotoCoreError):
            raise
        try:
            _units().put_item(
                Item=item,
                ConditionExpression="#v = :v",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":v": snapshot_version},
            )
        except ClientError as put_exc:
            if put_exc.response.get("Error", {}).get("Code", "") != "ConditionalCheckFailedException":
                raise
            committed = _get_unit(unit_id)
            if committed is None:
                raise
            return committed
        return item


def revoke_unit_access_grant(event: Dict[str, Any], context: Any) -> Any:
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
    mk = _marker_keys(caller, "revokeUnitAccessGrant", f"{unit_id}#{account_id}", key)
    fp = normalized_fingerprint({"unitId": unit_id, "accountId": account_id})
    handled, replayed = runner.replay_or_reject(
        mk, fp, operation="revokeUnitAccessGrant", load_result=lambda rid: _get_unit(rid)
    )
    if handled:
        return replayed
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
    if int(item.get("adminCount", 0)) <= 1:
        raise AppError(ErrorCode.CONFLICT, "Cannot revoke last admin")
    grant = (
        _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": f"GRANT#{account_id}"}, ConsistentRead=True).get("Item")
    )
    if not grant:
        return item
    item["adminCount"] = int(item["adminCount"]) - 1
    item["version"] = int(item.get("version", 0)) + 1
    item["updatedAt"] = _now()
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add(
        "Delete",
        {
            "TableName": _units().name,
            "Key": {"pk": _serialize(grant["pk"]), "sk": _serialize(grant["sk"])},
        },
    )
    plan.add(
        "Put",
        {
            "TableName": _units().name,
            "Item": {k: _serialize(v) for k, v in item.items()},
            "ConditionExpression": "#v = :v",
            "ExpressionAttributeNames": {"#v": "version"},
            "ExpressionAttributeValues": {":v": _serialize(int(item["version"]) - 1)},
        },
    )
    runner.execute(
        mk,
        plan,
        operation="revokeUnitAccessGrant",
        fingerprint=fp,
        result_id=unit_id,
        load_result=lambda rid: _get_unit(rid),
    )
    return item


def create_unit_invite(event: Dict[str, Any], context: Any) -> Any:
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey")
    if not key:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey is required")
    active = 0
    try:
        resp = _units().query(
            IndexName="unitId-createdAt-index",
            KeyConditionExpression="unitId = :u",
            ExpressionAttributeValues={":u": unit_id},
        )
        for x in resp.get("Items", []):
            if not str(x.get("pk", "")).startswith("INVITE#"):
                continue
            try:
                exp = datetime.fromisoformat(str(x.get("expiresAt")).replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    continue
            except Exception:
                pass
            active += 1
    except Exception as exc:
        raise AppError(
            ErrorCode.RESOURCE_BUSY,
            "Temporarily unable to count active invites. Please retry.",
        ) from exc
    if active >= _MAX_ACTIVE_INVITES:
        raise AppError(ErrorCode.CONFLICT, "Too many active invites")
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "createUnitInvite", unit_id, key)
    fp = normalized_fingerprint({"unitId": unit_id})

    def load_invite(rid: str) -> Any:
        return _units().get_item(Key={"pk": f"INVITE#{rid}", "sk": f"UNIT#{unit_id}"}, ConsistentRead=True).get("Item")

    handled, repl = runner.replay_or_reject(mk, fp, operation="createUnitInvite", load_result=load_invite)
    if handled:
        return repl
    code = uuid.uuid4().hex[:16].upper()
    now = _now()
    # expiry 14 days
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
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=code)
    plan.add("Put", {"TableName": _units().name, "Item": {k: _serialize(v) for k, v in item.items()}})
    runner.execute(
        mk,
        plan,
        operation="createUnitInvite",
        fingerprint=fp,
        result_id=code,
        load_result=load_invite,
    )
    return item


def revoke_unit_invite(event: Dict[str, Any], context: Any) -> bool:
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    unit_id = args.get("unitId")
    code = args.get("inviteCode")
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    resp = _units().get_item(Key={"pk": f"INVITE#{code}", "sk": f"UNIT#{unit_id}"}, ConsistentRead=True)
    if not resp.get("Item"):
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    _units().delete_item(Key={"pk": f"INVITE#{code}", "sk": f"UNIT#{unit_id}"})
    return True


def _count_redeem_failure(account_id: str) -> None:
    """Atomically count one failed redemption attempt (data model §6.6).

    One conditional UpdateItem both enforces and increments the window: the
    condition holds only for the item's absence (first attempt this hour) or
    attempts below the limit, so the 11th failure's add is rejected and the
    verdict is RATE_LIMIT_EXCEEDED instead of the write. Genuinely
    unavailability of the counter is best-effort: the failure verdict stands.
    """
    now = datetime.now(timezone.utc)
    window = now.strftime("%Y-%m-%dT%H")
    try:
        _throttles().update_item(
            Key={"key": f"UNIT_INVITE_REDEMPTION#{account_id}#WINDOW#{window}"},
            UpdateExpression="ADD attempts :one SET windowStart = :start, expiresAt = :ttl",
            ConditionExpression="attribute_not_exists(#k) OR attempts < :max",
            ExpressionAttributeNames={"#k": "key"},
            ExpressionAttributeValues={
                ":one": 1,
                ":start": window,
                ":ttl": int((now + timedelta(hours=_FAILURE_WINDOW_HOURS)).timestamp()),
                ":max": _FAILURE_WINDOW_LIMIT,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code", "") == "ConditionalCheckFailedException":
            raise AppError(ErrorCode.RATE_LIMIT_EXCEEDED, "Too many failed attempts") from exc
        logger.warning(
            "Redemption failure counter update was skipped",
            operation="countRedeemFailure",
            error_code=exc.response.get("Error", {}).get("Code", ""),
        )


def redeem_unit_invite(event: Dict[str, Any], context: Any) -> Any:
    args = event.get("arguments", {}).get("input", {}) or {}
    caller = get_caller_id(event)
    if not caller:
        raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity required")
    code = args.get("inviteCode")
    idempotency = args.get("idempotency", {}) or {}
    key = idempotency.get("idempotencyKey") or "default"
    runner = IdempotentMutationRunner()
    mk = _marker_keys(caller, "redeemUnitInvite", code, key)
    fp = normalized_fingerprint({"inviteCode": code})

    def load_redeem_grant(rid: str) -> Any:
        return _units().get_item(Key={"pk": _unit_pk(rid), "sk": f"GRANT#{caller}"}, ConsistentRead=True).get("Item")

    handled, repl = runner.replay_or_reject(mk, fp, operation="redeemUnitInvite", load_result=load_redeem_grant)
    if handled:
        return repl
    # query by pk prefix
    try:
        resp = _units().query(
            KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"INVITE#{code}"}, ConsistentRead=True
        )
    except Exception:
        resp = _units().query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"INVITE#{code}"})
    items = resp.get("Items", [])
    if not items:
        _count_redeem_failure(caller)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    inv = items[0]
    unit_id = inv["unitId"]
    # existing grant?
    try:
        gresp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": f"GRANT#{caller}"}, ConsistentRead=True)
        existing_grant = gresp.get("Item")
    except Exception:
        existing_grant = None
    if existing_grant:
        return existing_grant
    # expiry check
    from datetime import datetime as dt

    try:
        exp = dt.fromisoformat(inv["expiresAt"].replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            _count_redeem_failure(caller)
            raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    except AppError:
        raise
    except Exception:
        _count_redeem_failure(caller)
        raise AppError(ErrorCode.NOT_FOUND, "Invite not found")
    # one transaction: marker insert, grant, invite burn, adminCount sync
    grant_item = {
        "pk": _unit_pk(unit_id),
        "sk": f"GRANT#{caller}",
        "unitId": unit_id,
        "accountId": caller,
        "role": "UNIT_ADMIN",
        "createdByAccountId": inv.get("createdByAccountId", caller),
        "createdAt": _now(),
    }
    plan = WritePlan()
    runner.stage_marker(plan, mk, fingerprint=fp, result_id=unit_id)
    plan.add(
        "Put",
        {
            "TableName": _units().name,
            "Item": {k: _serialize(v) for k, v in grant_item.items()},
            "ConditionExpression": "attribute_not_exists(#pk)",
            "ExpressionAttributeNames": {"#pk": "pk"},
        },
    )
    plan.add(
        "Delete",
        {
            "TableName": _units().name,
            "Key": {"pk": _serialize(inv["pk"]), "sk": _serialize(inv["sk"])},
            "ConditionExpression": "attribute_exists(#pk)",
            "ExpressionAttributeNames": {"#pk": "pk"},
        },
    )
    meta = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True).get("Item")
    if meta:
        snapshot_version = int(meta.get("version", 0))
        meta["adminCount"] = int(meta.get("adminCount", 1)) + 1
        meta["version"] = snapshot_version + 1
        meta["updatedAt"] = _now()
        plan.add(
            "Put",
            {
                "TableName": _units().name,
                "Item": {k: _serialize(v) for k, v in meta.items()},
                "ConditionExpression": "#v = :v",
                "ExpressionAttributeNames": {"#v": "version"},
                "ExpressionAttributeValues": {":v": _serialize(snapshot_version)},
            },
        )
    runner.execute(
        mk,
        plan,
        operation="redeemUnitInvite",
        fingerprint=fp,
        result_id=unit_id,
        load_result=load_redeem_grant,
    )
    return grant_item


def my_units(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}) or {}
    caller = get_caller_id(event)
    grants = []
    try:
        resp = _units().query(
            IndexName="accountId-unitId-index",
            KeyConditionExpression="accountId = :a",
            ExpressionAttributeValues={":a": caller},
        )
        grants = resp.get("Items", [])
    except Exception:
        grants = []
    grants.sort(key=lambda g: g.get("unitId", ""))
    limit, cursor = _parse_page(args)
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0
    else:
        start = 0
    page_grants = grants[start : start + limit]
    units = []
    for g in page_grants:
        uid = g.get("unitId")
        if not uid:
            continue
        meta = _units().get_item(Key={"pk": _unit_pk(uid), "sk": "METADATA"}, ConsistentRead=True).get("Item")
        if meta:
            units.append(meta)
    next_cursor = str(start + limit) if start + limit < len(grants) else None
    return {"items": units, "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None}}


def unit(event: Dict[str, Any], context: Any) -> Any:
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        return None
    resp = _units().get_item(Key={"pk": _unit_pk(unit_id), "sk": "METADATA"}, ConsistentRead=True)
    return resp.get("Item")


def unit_admins(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    grants = []
    try:
        resp = _units().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :grants)",
            ExpressionAttributeValues={":pk": _unit_pk(unit_id), ":grants": "GRANT#"},
            ConsistentRead=True,
        )
        grants = resp.get("Items", [])
    except Exception:
        grants = []
    grants.sort(key=lambda g: g.get("sk", ""))
    limit, cursor = _parse_page(args)
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0
    else:
        start = 0
    page_items = grants[start : start + limit]
    next_cursor = str(start + limit) if start + limit < len(grants) else None
    return {"items": page_items, "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None}}


def _parse_page(args: Dict[str, Any]) -> tuple[int, Any]:
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


def unit_invites(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {}) or {}
    unit_id = args.get("unitId")
    caller = get_caller_id(event)
    if not _is_unit_admin(caller, unit_id):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin required")
    try:
        resp = _units().query(
            IndexName="unitId-createdAt-index",
            KeyConditionExpression="unitId = :u",
            ExpressionAttributeValues={":u": unit_id},
        )
    except Exception:
        resp = {"Items": []}
    now = datetime.now(timezone.utc)
    items = []
    for x in resp.get("Items", []):
        if not str(x.get("pk", "")).startswith("INVITE#"):
            continue
        try:
            exp = datetime.fromisoformat(str(x.get("expiresAt")).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                continue
        except Exception:
            pass
        items.append(x)
    limit, cursor = _parse_page(args)
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0
    else:
        start = 0
    page_items = items[start : start + limit]
    next_cursor = str(start + limit) if start + limit < len(items) else None
    return {"items": page_items, "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None}}


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
def lambda_handler(event: Dict[str, Any], context: Any) -> Any:
    field = event.get("info", {}).get("fieldName", "")
    handler = _HANDLERS.get(field)
    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown unit operation: {field}")
    return handler(event, context)
