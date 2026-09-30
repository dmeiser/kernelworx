"""
Type definitions for AppSync Lambda events.

Provides TypedDict definitions for strongly typing AppSync resolver events,
reducing runtime errors from incorrect event structure assumptions.
"""

from collections.abc import Mapping
from typing import Any, Dict, Optional, cast

from .errors import AppError, ErrorCode
from .validation import validate_unit_number

# Helper functions for safe extraction


def get_caller_id(event: Dict[str, Any]) -> Optional[str]:
    """
    Extract caller's Cognito sub (user ID) from event.

    Args:
        event: AppSync event

    Returns:
        Caller ID or None if not present
    """
    identity: Dict[str, Any] = event.get("identity", {})
    result: Optional[str] = identity.get("sub")
    return result


def get_caller_id_required(event: Dict[str, Any]) -> str:
    """
    Extract caller's Cognito sub (user ID) from event.

    Args:
        event: AppSync event

    Returns:
        Caller ID

    Raises:
        ValueError: If caller ID is not present
    """
    caller_id = get_caller_id(event)
    if not caller_id:
        raise ValueError("Caller ID (identity.sub) is required")
    return caller_id


def get_argument(event: Dict[str, Any], name: str, default: Any = None) -> Any:
    """
    Extract an argument from the event.

    Args:
        event: AppSync event
        name: Argument name
        default: Default value if not present

    Returns:
        Argument value or default
    """
    return event.get("arguments", {}).get(name, default)


def get_argument_required(event: Dict[str, Any], name: str) -> Any:
    """
    Extract a required argument from the event.

    Args:
        event: AppSync event
        name: Argument name

    Returns:
        Argument value

    Raises:
        ValueError: If argument is not present
    """
    value = get_argument(event, name)
    if value is None:
        raise ValueError(f"Argument '{name}' is required")
    return value


# Argument readers for the raw AppSync event. Unlike get_argument/get_argument_required
# (which only test for presence and return whatever shape the caller sent), these enforce
# the schema types and bounds the resolver relies on, raising a typed INVALID_INPUT AppError
# so a malformed or missing argument surfaces to the client as INVALID_INPUT rather than the
# generic INTERNAL_ERROR the lambda_handler decorator would otherwise produce (#552).


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


def get_prev_result(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract previous pipeline step result.

    Args:
        event: AppSync pipeline event

    Returns:
        Previous result dict (empty if not present)
    """
    prev: Dict[str, Any] = event.get("prev", {})
    result: Dict[str, Any] = prev.get("result", {})
    return result
