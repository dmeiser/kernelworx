"""
Type definitions for AppSync Lambda events.

Provides TypedDict definitions for strongly typing AppSync resolver events,
reducing runtime errors from incorrect event structure assumptions.
"""

from typing import Any, Dict, Optional

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
