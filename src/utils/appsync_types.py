"""
Helpers for reading AppSync Lambda events.

``get_caller_id`` centralizes caller-ID extraction, and the ``require_*``
readers enforce the schema types and bounds a resolver relies on before it
indexes into the raw event.
"""

import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Dict, Optional, cast

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
