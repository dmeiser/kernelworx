"""
Unit payment method operations handlers (Show & Sell wave 5 fast-follow:
the wave-2-deferred surface).

Unit payment methods are rows in the UNITS table under the owning unit:
PAYMENT#<paymentMethodId> with versioned optimistic concurrency. Built-in
Cash/Check/Other are COMPUTED in projections, never stored as custom rows
(spec API section 4.3): at most 50 ACTIVE custom methods, Other is
reserved, names carry a 100-character bound.

QR codes use the impact-map 4.3 key contract on the EXISTING exports
bucket — payment-qr-codes/units/<unitId>/<paymentMethodId>/<filename> —
so frontend/index.html CSP needs no change. Uploads are presigned
(server never proxies bytes); confirm records the key after the client
lands the object; delete removes the object and clears the key.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_version,
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
    from utils.logging import get_logger
    from utils.unit_auth import require_unit_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import (
        get_caller_id,
        require_bounded_str,
        require_idempotency_key,
        require_version,
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
    from ..utils.logging import get_logger
    from ..utils.unit_auth import require_unit_admin

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)

IDEM_HASH = "__IDEM__"
PAYMENT_PREFIX = "PAYMENT#"
MAX_ACTIVE_METHODS = 50  # spec API section 4.3
NAME_MAX = 100
BUILTIN_CODES = ("CASH", "CHECK", "OTHER")
QR_PREFIX = "payment-qr-codes/units"
QR_CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp")
ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return str(moment.isoformat()).replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _fingerprint(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _require_caller(event: Dict[str, Any]) -> str:
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return str(caller)


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
    key = args.get("idempotencyKey")
    if key is None and isinstance(args.get("input"), dict):
        key = args["input"].get("idempotencyKey")
    replayed = _check_marker(_get_marker(caller, scope, str(key or "")), fingerprint)
    return caller, fingerprint, replayed


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
# Reads and projections
# ---------------------------------------------------------------------------


def _custom_methods(unit_id: str) -> List[Dict[str, Any]]:
    response = tables.units.query(
        KeyConditionExpression="unitId = :u AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":u": unit_id, ":prefix": PAYMENT_PREFIX},
    )
    return [dict(item) for item in response.get("Items", []) if item.get("itemKey", "").startswith(PAYMENT_PREFIX)]


def _method_to_graphql(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "paymentMethodId": item["paymentMethodId"],
        "unitId": item["unitId"],
        "displayName": item["displayName"],
        "normalizedName": item.get("normalizedName", item["displayName"].strip().upper()),
        "isBuiltin": False,
        "qrCodeS3Key": item.get("qrCodeS3Key"),
        "isActive": item.get("status", ACTIVE) == ACTIVE,
        "version": int(item.get("version", 0)),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }


def _builtin_method(unit_id: str, code: str) -> Dict[str, Any]:
    return {
        "paymentMethodId": f"BUILTIN#{code}",
        "unitId": unit_id,
        "displayName": code.title(),
        "normalizedName": code,
        "isBuiltin": True,
        "qrCodeS3Key": None,
        "isActive": True,
        "version": 0,
        "createdAt": "",
        "updatedAt": "",
    }


def _list_payment_methods(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    caller = _require_caller(event)
    require_unit_admin(tables.units, unit_id, caller)
    methods = [_builtin_method(unit_id, code) for code in BUILTIN_CODES]
    methods.extend(_method_to_graphql(item) for item in _custom_methods(unit_id))
    return methods


def _load_method(unit_id: str, payment_method_id: str) -> Dict[str, Any]:
    item = tables.units.get_item(
        Key={"unitId": unit_id, "itemKey": f"{PAYMENT_PREFIX}{payment_method_id}"}, ConsistentRead=True
    ).get("Item")
    if not isinstance(item, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Payment method not found")
    return dict(item)


def _guard_builtin(payment_method_id: str) -> None:
    if payment_method_id.startswith("BUILTIN#"):
        raise AppError(ErrorCode.INVALID_INPUT, "Built-in payment methods cannot be modified")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _create_payment_method(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    display_name = require_bounded_str(args, "displayName", NAME_MAX)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "createUnitPaymentMethod")
    if replayed is not None:
        return replayed
    require_unit_admin(tables.units, unit_id, caller)

    active = [m for m in _custom_methods(unit_id) if m.get("status", ACTIVE) == ACTIVE]
    if len(active) >= MAX_ACTIVE_METHODS:
        raise AppError(
            ErrorCode.CONFLICT,
            f"A Unit can have at most {MAX_ACTIVE_METHODS} active payment methods",
            details={"reason": "PAYMENT_METHOD_LIMIT"},
        )

    now = _utcnow()
    stamp = _iso(now)
    payment_method_id = str(uuid.uuid4())
    item = {
        "unitId": unit_id,
        "itemKey": f"{PAYMENT_PREFIX}{payment_method_id}",
        "paymentMethodId": payment_method_id,
        "displayName": display_name,
        "normalizedName": display_name.strip().upper(),
        "status": ACTIVE,
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
        "createdByAccountId": caller,
    }
    result = _method_to_graphql(item)
    marker = _marker_put(caller, "createUnitPaymentMethod", key, fingerprint, result, _epoch(now))
    _execute_replayable(
        [
            {
                "Put": {
                    "TableName": tables.units.table_name,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(itemKey)",
                }
            },
            marker,
        ],
        marker,
    )
    return result


def _update_payment_method(event: Dict[str, Any], context: Any, *, deactivate: bool = False) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    payment_method_id = require_bounded_str(args, "paymentMethodId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)
    display_name: Optional[str] = None
    if not deactivate:
        display_name = require_bounded_str(args, "displayName", NAME_MAX)

    scope = "deactivateUnitPaymentMethod" if deactivate else "updateUnitPaymentMethod"
    caller, fingerprint, replayed = _idempotency_begin(event, args, scope)
    if replayed is not None:
        return replayed
    require_unit_admin(tables.units, unit_id, caller)
    _guard_builtin(payment_method_id)
    current = _load_method(unit_id, payment_method_id)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "Payment method was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        )

    now = _utcnow()
    stamp = _iso(now)
    merged = {**current, "version": expected_version + 1, "updatedAt": stamp, "updatedByAccountId": caller}
    if deactivate:
        merged["status"] = INACTIVE
        expression = "SET #status = :inactive, #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub"
        names = {
            "#status": "status",
            "#version": "version",
            "#updatedAt": "updatedAt",
            "#updatedByAccountId": "updatedByAccountId",
        }
        values: Dict[str, Any] = {
            ":inactive": INACTIVE,
            ":next": expected_version + 1,
            ":ua": stamp,
            ":ub": caller,
            ":expected": expected_version,
        }
    else:
        assert display_name is not None
        merged["displayName"] = display_name
        merged["normalizedName"] = display_name.strip().upper()
        expression = "SET #displayName = :dn, #normalizedName = :nn, #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub"
        names = {
            "#displayName": "displayName",
            "#normalizedName": "normalizedName",
            "#version": "version",
            "#updatedAt": "updatedAt",
            "#updatedByAccountId": "updatedByAccountId",
        }
        values = {
            ":dn": display_name,
            ":nn": display_name.strip().upper(),
            ":next": expected_version + 1,
            ":ua": stamp,
            ":ub": caller,
            ":expected": expected_version,
        }
    update = {
        "Update": {
            "TableName": tables.units.table_name,
            "Key": {"unitId": unit_id, "itemKey": f"{PAYMENT_PREFIX}{payment_method_id}"},
            "UpdateExpression": expression,
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
    }
    result = _method_to_graphql(merged)
    marker = _marker_put(caller, scope, key, fingerprint, result, _epoch(now))
    _execute_replayable([update, marker], marker)
    return result


def _qr_key(unit_id: str, payment_method_id: str, filename: str) -> str:
    return f"{QR_PREFIX}/{unit_id}/{payment_method_id}/{filename}"


def _request_qr_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    payment_method_id = require_bounded_str(args, "paymentMethodId", 100)
    content_type = require_bounded_str(args, "contentType", 100)
    key = require_idempotency_key(args)
    if content_type not in QR_CONTENT_TYPES:
        raise AppError(ErrorCode.INVALID_INPUT, f"contentType must be one of: {', '.join(QR_CONTENT_TYPES)}")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "requestUnitPaymentMethodQrUpload")
    if replayed is not None:
        return replayed
    require_unit_admin(tables.units, unit_id, caller)
    _guard_builtin(payment_method_id)
    method = _load_method(unit_id, payment_method_id)
    if method.get("status", ACTIVE) != ACTIVE:
        raise AppError(
            ErrorCode.CONFLICT, "An inactive payment method cannot take a QR upload", details={"reason": "ACTIVE_GUARD"}
        )

    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[content_type]
    s3_key = _qr_key(unit_id, payment_method_id, f"{uuid.uuid4().hex}.{extension}")
    bucket = os.environ.get("EXPORTS_BUCKET", "")
    if not bucket:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Exports bucket is not configured")
    presigner = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    upload_url = presigner.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=300,
    )
    result = {"uploadUrl": upload_url, "s3Key": s3_key}
    # No transaction: the request is a pure read + presign; the marker only
    # pins the RESPONSE for replay (no effect to commit).
    now = _utcnow()
    marker = _marker_put(caller, "requestUnitPaymentMethodQrUpload", key, fingerprint, result, _epoch(now))
    execute_transaction([marker])
    return result


def _confirm_qr_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    payment_method_id = require_bounded_str(args, "paymentMethodId", 100)
    expected_version = require_version(args)
    s3_key = require_bounded_str(args, "s3Key", 300)
    key = require_idempotency_key(args)
    if not s3_key.startswith(f"{QR_PREFIX}/{unit_id}/{payment_method_id}/"):
        raise AppError(ErrorCode.INVALID_INPUT, "s3Key must live under the Unit QR prefix for this method")

    caller, fingerprint, replayed = _idempotency_begin(event, args, "confirmUnitPaymentMethodQrUpload")
    if replayed is not None:
        return replayed
    require_unit_admin(tables.units, unit_id, caller)
    _guard_builtin(payment_method_id)
    current = _load_method(unit_id, payment_method_id)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "Payment method was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        )

    now = _utcnow()
    stamp = _iso(now)
    merged = {
        **current,
        "qrCodeS3Key": s3_key,
        "version": expected_version + 1,
        "updatedAt": stamp,
        "updatedByAccountId": caller,
    }
    update = {
        "Update": {
            "TableName": tables.units.table_name,
            "Key": {"unitId": unit_id, "itemKey": f"{PAYMENT_PREFIX}{payment_method_id}"},
            "UpdateExpression": "SET #qrCodeS3Key = :qk, #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub",
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#qrCodeS3Key": "qrCodeS3Key",
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":qk": s3_key,
                ":next": expected_version + 1,
                ":ua": stamp,
                ":ub": caller,
                ":expected": expected_version,
            },
        }
    }
    result = _method_to_graphql(merged)
    marker = _marker_put(caller, "confirmUnitPaymentMethodQrUpload", key, fingerprint, result, _epoch(now))
    _execute_replayable([update, marker], marker)
    return result


def _delete_qr_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    args = event.get("arguments", {})
    unit_id = require_bounded_str(args, "unitId", 100)
    payment_method_id = require_bounded_str(args, "paymentMethodId", 100)
    expected_version = require_version(args)
    key = require_idempotency_key(args)

    caller, fingerprint, replayed = _idempotency_begin(event, args, "deleteUnitPaymentMethodQrCode")
    if replayed is not None:
        return replayed
    require_unit_admin(tables.units, unit_id, caller)
    _guard_builtin(payment_method_id)
    current = _load_method(unit_id, payment_method_id)
    if int(current.get("version", 0)) != expected_version:
        raise AppError(
            ErrorCode.CONFLICT, "Payment method was modified concurrently", details={"reason": "VERSION_MISMATCH"}
        )

    bucket = os.environ.get("EXPORTS_BUCKET", "")
    s3_key = current.get("qrCodeS3Key")
    if s3_key and bucket:
        boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1")).delete_object(
            Bucket=bucket, Key=s3_key
        )

    now = _utcnow()
    stamp = _iso(now)
    merged = {
        **current,
        "qrCodeS3Key": None,
        "version": expected_version + 1,
        "updatedAt": stamp,
        "updatedByAccountId": caller,
    }
    update = {
        "Update": {
            "TableName": tables.units.table_name,
            "Key": {"unitId": unit_id, "itemKey": f"{PAYMENT_PREFIX}{payment_method_id}"},
            "UpdateExpression": "REMOVE #qrCodeS3Key SET #version = :next, #updatedAt = :ua, #updatedByAccountId = :ub",
            "ConditionExpression": "#version = :expected",
            "ExpressionAttributeNames": {
                "#qrCodeS3Key": "qrCodeS3Key",
                "#version": "version",
                "#updatedAt": "updatedAt",
                "#updatedByAccountId": "updatedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":next": expected_version + 1,
                ":ua": stamp,
                ":ub": caller,
                ":expected": expected_version,
            },
        }
    }
    result = _method_to_graphql(merged)
    marker = _marker_put(caller, "deleteUnitPaymentMethodQrCode", key, fingerprint, result, _epoch(now))
    _execute_replayable([update, marker], marker)
    return result


import boto3  # noqa: E402

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {
    "unitPaymentMethods": _list_payment_methods,
    "createUnitPaymentMethod": _create_payment_method,
    "updateUnitPaymentMethod": lambda event, context: _update_payment_method(event, context, deactivate=False),
    "deactivateUnitPaymentMethod": lambda event, context: _update_payment_method(event, context, deactivate=True),
    "requestUnitPaymentMethodQrUpload": _request_qr_upload,
    "confirmUnitPaymentMethodQrUpload": _confirm_qr_upload,
    "deleteUnitPaymentMethodQrCode": _delete_qr_code,
}


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch a payment-method operation by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    operation = _DISPATCH.get(field_name)
    if operation is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported payment-method operation: {field_name}")
    return operation(event, context)
