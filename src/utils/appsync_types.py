"""
Helpers for reading AppSync Lambda events.

``get_caller_id`` centralizes caller-ID extraction, and the ``require_*``
readers enforce the schema types and bounds a resolver relies on before it
indexes into the raw event.
"""

import math
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import AppError, ErrorCode
from .validation import validate_unit_number

# Helper functions for safe extraction


def get_caller_id(event: Dict[str, Any]) -> Optional[str]:
    """
    Extract caller's Cognito sub (user ID) from event.

    Every handler reads the caller through this helper (see
    tests/unit/test_caller_id_helper.py): hand-inlining
    ``event["identity"]["sub"]`` raises ``KeyError`` on a malformed event,
    where this returns None. The ``isinstance`` guard covers the remaining
    shape -- a present but non-mapping ``identity`` -- where reading ``sub``
    would raise ``AttributeError`` instead of returning None.

    Args:
        event: AppSync event

    Returns:
        Caller ID or None if not present or not readable
    """
    identity = event.get("identity")
    if not isinstance(identity, Mapping):
        return None
    result: Optional[str] = identity.get("sub")
    return result


# Argument readers for the raw AppSync event: they enforce the schema types and
# bounds the resolver relies on, raising a typed INVALID_INPUT AppError so a
# malformed or missing argument surfaces to the client as INVALID_INPUT rather
# than the generic INTERNAL_ERROR the lambda_handler decorator would otherwise
# produce (#552).


def require_str(arguments: Mapping[str, Any], name: str) -> str:
    """
    Require a present, non-null string argument.

    Args:
        arguments: The resolver's argument mapping (event["arguments"] or a nested input object)
        name: Argument name

    Returns:
        The argument value

    Raises:
        AppError: INVALID_INPUT if the argument is missing, null, or not a string
    """
    value = arguments.get(name)
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' is required")
    if not isinstance(value, str) or not value:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be a non-empty string")
    return value


def require_int(arguments: Mapping[str, Any], name: str) -> int:
    """
    Require a present argument that converts to an integer.

    Args:
        arguments: The resolver's argument mapping (event["arguments"] or a nested input object)
        name: Argument name

    Returns:
        The argument value as an int

    Raises:
        AppError: INVALID_INPUT if the argument is missing, null, or not an integer
    """
    value = arguments.get(name)
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' is required")
    try:
        return int(value)
    except ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be an integer") from None


def require_unit_number(arguments: Mapping[str, Any], name: str) -> int:
    """
    Require a present scout unit number within the valid bounds.

    Delegates to validation.validate_unit_number so the "positive integer" rule lives in one
    place; a missing, empty, non-numeric, or non-positive value raises INVALID_INPUT naming
    unitNumber rather than flowing into the GSI key condition as a bogus-but-empty result.

    Args:
        arguments: The resolver's argument mapping (event["arguments"] or a nested input object)
        name: Argument name ("unitNumber")

    Returns:
        The unit number as an int

    Raises:
        AppError: INVALID_INPUT if the value is missing, empty, non-numeric, or < 1
    """
    return cast(int, validate_unit_number(arguments.get(name), required=True))


def _is_int(value: Any) -> bool:
    """True only for genuine integers: bools and floats are rejected.

    ``isinstance(True, int)`` is True in Python, so the bool check is not
    redundant: a JSON ``true`` must never satisfy an integer contract.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def require_strict_int(arguments: Mapping[str, Any], name: str) -> int:
    """Require a present argument that IS an integer, not merely converts to one.

    Unlike ``require_int`` (which coerces numeric strings and floats), this
    validator enforces the wire contract for Show & Sell fields: AppSync
    delivers integers as JSON ints, so a float or numeric string means the
    caller sent the wrong type and the value is rejected rather than
    silently narrowed (impact map 3.4).
    """
    value = arguments.get(name)
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' is required")
    if not _is_int(value):
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be an integer")
    return cast(int, value)


def require_bounded_str(arguments: Mapping[str, Any], name: str, max_length: int, *, allow_empty: bool = False) -> str:
    """Require a present string within an explicit length bound.

    Show & Sell free-text fields carry spec bounds (impact map 3.4); the
    bound is a parameter so each resolver states its contract at the call
    site instead of a module-global table drifting from the spec.
    """
    value = arguments.get(name)
    if value is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' is required")
    if not isinstance(value, str):
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be a string")
    if not allow_empty and not value:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be a non-empty string")
    if len(value) > max_length:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' exceeds the maximum length of {max_length}")
    return value


def require_cents(arguments: Mapping[str, Any], name: str, *, maximum: Optional[int] = None) -> int:
    """Require a present integer-cents money value (non-negative).

    Show & Sell money is integer cents, never Float (impact map 3.1). This
    is the type/range floor: strictly an int, not a bool, >= 0, and bounded
    by ``maximum`` when the caller passes one. Per-field caps (sale totals,
    line limits) stay in the owning handler so the generic validator never
    invents product policy.
    """
    value = require_strict_int(arguments, name)
    if value < 0:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must not be negative")
    if maximum is not None and value > maximum:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' exceeds the maximum of {maximum}")
    return value


def require_version(arguments: Mapping[str, Any], name: str = "expectedVersion") -> int:
    """Require a present optimistic-concurrency version: a strict int >= 1.

    Versions are assigned by the server starting at 1; a caller-supplied 0
    or negative version cannot match any row and indicates a contract
    violation rather than a conflict.
    """
    value = require_strict_int(arguments, name)
    if value < 1:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be a positive integer")
    return value


def require_timestamp(arguments: Mapping[str, Any], name: str) -> str:
    """Require a present RFC 3339 timestamp string with an explicit offset.

    Returns the validated string unchanged. Naive timestamps (no offset)
    are rejected: Show & Sell event math spans zones, and a naive value
    silently means "someone's local wall clock".
    """
    value = require_str(arguments, name)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be an RFC 3339 timestamp") from None
    if parsed.tzinfo is None:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must include a UTC offset")
    return value


def require_timezone(arguments: Mapping[str, Any], name: str) -> str:
    """Require a present IANA timezone name (e.g. ``America/Denver``).

    Event scheduling math (spec 9.1) keys off named zones; fixed-offset
    abbreviations like ``MST`` are ambiguous and rejected by zoneinfo.
    """
    value = require_str(arguments, name)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError, ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be an IANA timezone name") from None
    return value


def require_idempotency_key(arguments: Mapping[str, Any], name: str = "idempotencyKey") -> str:
    """Require a present client idempotency key: 8-128 visible-ASCII characters.

    The key is an opaque marker identity (spec: invite alphabet is A-Z0-9;
    general keys stay printable ASCII so they are safe in item keys, logs,
    and caches). Uniqueness semantics live in the idempotency layer; this
    validator only enforces the shape contract.
    """
    value = require_str(arguments, name)
    if not 8 <= len(value) <= 128:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be between 8 and 128 characters")
    if not value.isprintable() or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must contain only printable ASCII characters")
    return value


def require_str_enum(arguments: Mapping[str, Any], name: str, allowed: tuple[str, ...]) -> str:
    """Require a present string belonging to an explicit enumeration.

    ``allowed`` is stated at the call site (schema enum values) so the
    validator cannot drift from the SDL; the check is exact and
    case-sensitive — wire enums are uppercase by contract.
    """
    value = require_str(arguments, name)
    if value not in allowed:
        raise AppError(ErrorCode.INVALID_INPUT, f"Argument '{name}' must be one of: {', '.join(allowed)}")
    return value


def as_float(value: Any) -> Optional[float]:
    """Coerce a stored DynamoDB number to float, or None when it is not one.

    Accepts int, float, str, and Decimal (the form DynamoDB returns). Any
    value that cannot be converted to float returns None rather than raising,
    so a single malformed stored value cannot fail an entire response.
    ``Decimal("NaN")`` and the infinities ARE convertible by ``float()`` but
    are not money: a NaN price or total survives every downstream comparison
    and reaches the buyer as garbage, so non-finite values are rejected here
    like any other malformed stored number (FUNC-17).
    """
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None
