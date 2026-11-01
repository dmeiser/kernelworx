"""
Single source of truth for Cognito ListUsers filter expressions.

Cognito's ListUsers ``Filter`` is the only string-interpolated query language this
codebase builds: a caller-supplied value is spliced between double quotes into an
expression such as ``sub = "..."``. Cognito treats a backslash as the escape
character for an inner double quote, so a value carrying a quote or a trailing
backslash can escape the terminating quote and break out of the literal.

Every filter call site goes through :func:`cognito_user_filter`, which both
validates the value *and* returns the complete expression, so the value that was
checked is by construction the value that is sent. Adding a call site means
picking a field, not picking one of several validators (#124, #560).
"""

import re
from typing import Literal

from .errors import AppError, ErrorCode

# The Cognito attributes a user filter can match on. ``email_prefix`` uses Cognito's
# ``^=`` starts-with operator; the other two use exact ``=``.
CognitoFilterField = Literal["sub", "email", "email_prefix"]

# Which email shape to enforce for the ``email`` field. The two call paths that
# interpolate an email have different trust levels, so the difference is an explicit
# argument rather than an accident of which validator a call site happened to reach
# for:
#   "loose"  - an address an admin typed in order to act on it. Only a
#              whitespace-free ``local@domain.tld`` is required; widening or
#              narrowing this changes which admin actions reach Cognito.
#   "strict" - an address asserted by an external identity provider on the pre-signup
#              path (#426). The character set is restricted and the TLD must be
#              alphabetic, so a provider attribute that merely looks like an address
#              is not treated as one.
CognitoEmailShape = Literal["loose", "strict"]

# The double quote that terminates the filter literal and the backslash that escapes
# it, plus whitespace (rejected so a value cannot smuggle terms past the literal).
_COGNITO_FILTER_METACHARS = frozenset('"\\')

# RFC 5321 caps a forward path at 256 characters; a Cognito sub is shorter in
# practice but is not constrained to be a UUID (see _SUB_SHAPE below).
_MAX_LENGTH = {"sub": 256, "email": 254, "email_prefix": 254}

# The Cognito attribute each field matches on. ``email_prefix`` and ``email`` share
# the ``email`` attribute; they differ only in the operator applied to it.
_FIELD_ATTRIBUTE = {"sub": "sub", "email": "email", "email_prefix": "email"}

_REQUIRED_MESSAGE = {
    "sub": "Account ID is required",
    "email": "Email is required",
    "email_prefix": "Search query is required",
}

_INVALID_MESSAGE = {
    "sub": "Invalid account ID",
    "email": "Invalid email",
    "email_prefix": "Invalid search query",
}

# A whitespace-free address with a dotted domain, no further restriction.
_LOOSE_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Local part and domain restricted to the characters a deliverable address uses, and
# an alphabetic TLD of at least two characters.
_STRICT_EMAIL_SHAPE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_EMAIL_SHAPE = {"loose": _LOOSE_EMAIL_SHAPE, "strict": _STRICT_EMAIL_SHAPE}

# A local part, optionally followed by an ``@`` and a (possibly partial) domain, for
# Cognito's ``email ^=`` starts-with search.
_EMAIL_PREFIX_SHAPE = re.compile(r"[a-zA-Z0-9._%+-]+(?:@[a-zA-Z0-9.-]*)?")


def _check_shape(field: CognitoFilterField, value: str, email_shape: CognitoEmailShape) -> None:
    """Enforce the per-field shape after the shared length/metacharacter guard passed."""
    if field == "sub":
        # Deliberately no shape check: a deletion or reset for a non-existent user must
        # resolve to NOT_FOUND at the lookup rather than INVALID_INPUT at validation.
        return
    pattern = _EMAIL_SHAPE[email_shape] if field == "email" else _EMAIL_PREFIX_SHAPE
    if pattern.fullmatch(value) is None:
        raise AppError(ErrorCode.INVALID_INPUT, _INVALID_MESSAGE[field])


def cognito_user_filter(
    field: CognitoFilterField,
    value: str,
    *,
    email_shape: CognitoEmailShape = "loose",
) -> str:
    """Validate ``value`` for ``field`` and return the complete, quoted Cognito filter.

    Args:
        field: The Cognito attribute the filter matches on.
        value: The raw caller-supplied value to validate and interpolate.
        email_shape: Which email shape to require when ``field`` is ``"email"``; ignored
            for the other fields. See :data:`CognitoEmailShape`.

    Returns:
        The complete filter expression, e.g. ``sub = "abc"`` or ``email ^= "a"``.

    Raises:
        AppError: ``INVALID_INPUT`` when the value is not a string, is empty, exceeds
            the field's length cap, contains a Cognito filter metacharacter or
            whitespace, or does not match the field's shape.
    """
    if not isinstance(value, str) or not value or len(value) > _MAX_LENGTH[field]:
        raise AppError(ErrorCode.INVALID_INPUT, _REQUIRED_MESSAGE[field])
    if any(ch in _COGNITO_FILTER_METACHARS or ch.isspace() for ch in value):
        raise AppError(ErrorCode.INVALID_INPUT, _INVALID_MESSAGE[field])
    _check_shape(field, value, email_shape)

    operator = "^=" if field == "email_prefix" else "="
    return f'{_FIELD_ATTRIBUTE[field]} {operator} "{value}"'
