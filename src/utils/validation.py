"""
Input validation utilities.

The module holds the shared "positive integer" rule for a scout unit number.
``utils.appsync_types.require_unit_number`` delegates to
``validate_unit_number`` so the rule lives in one place, and the AppSync
resolvers enforce the same bounds in ``js-resolvers/``.

Everything else that used to live here (seller-name length, unit-type enum,
address/invite-code/phone/date validation and the typed ``*Input`` models) had
no production caller and was removed in #527: the live validation paths enforce
those rules in the AppSync resolvers, and the typed models were never wired
into request handling.

The multi-type handler in this module (``except ValueError, TypeError:``) is
PEP 758 syntax, valid on the pinned Python 3.14 floor. It is a tuple of
exception types, NOT Python 2's ``except Exception, name:`` catch-and-bind
form, and does not bind anything. This is also the spelling ``ruff format``
produces at that target version, so do not add parentheses: the formatter
strips them, and the file cannot be parsed at all by a 3.13-or-earlier tool.
See tests/unit/test_except_syntax.py.
"""

from typing import Any, Optional

from .errors import AppError, ErrorCode


def validate_unit_number(value: Any, required: bool = False) -> Optional[int]:
    """
    Validate and convert unit number to integer.

    Args:
        value: Value to validate (may be string, int, or None)
        required: Whether value is required

    Returns:
        Validated integer or None if not required and not provided

    Raises:
        AppError: If validation fails
    """
    if value is None or value == "":
        if required:
            raise AppError(ErrorCode.INVALID_INPUT, "unitNumber is required when unitType is provided")
        return None

    try:
        number = int(value)
        if number < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "unitNumber must be a positive integer")
        return number
    except ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "unitNumber must be a valid integer")
